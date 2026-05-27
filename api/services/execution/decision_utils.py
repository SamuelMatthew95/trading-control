"""Pure utility functions for validating and scoring execution decisions.

All functions here are side-effect free: no async, no logging, no Redis or DB calls.
The ExecutionEngine methods call these and add logging / heartbeat writes on top.
"""

from __future__ import annotations

import uuid
from typing import Any, NamedTuple

from api.constants import (
    EXECUTION_DECISION_THRESHOLD,
    NO_ORDER_ACTIONS,
    SIGNAL_CONFIDENCE_MIN_GATE,
    SLIPPAGE_PCT_PER_SIDE,
    FieldName,
)


class ParsedDecision(NamedTuple):
    """Validated fields extracted from a raw decision payload."""

    side: str
    symbol: str
    qty: float
    price: float
    strategy_id: str
    trace_id: str


def parse_decision_fields(data: dict) -> tuple[ParsedDecision | None, str | None]:
    """Validate and extract required fields from a decision payload.

    Returns ``(ParsedDecision, None)`` on success or ``(None, error_code)`` on
    failure.  Error codes match the ``exec_status`` values understood by
    ``ExecutionEngine._write_idle_heartbeat``.
    """
    side_or_action = str(data.get(FieldName.ACTION) or data.get(FieldName.SIDE) or "").lower()
    missing = [f for f in (FieldName.SYMBOL, FieldName.QTY, FieldName.PRICE) if not data.get(f)]
    if not side_or_action:
        missing.append("action/side")
    if missing:
        return None, f"error:missing_fields:{','.join(missing)}"

    strategy_id = str(data.get(FieldName.STRATEGY_ID) or uuid.uuid4())
    symbol = str(data[FieldName.SYMBOL])
    side = side_or_action
    try:
        qty = float(data[FieldName.QTY])
        price = float(data[FieldName.PRICE])
    except (TypeError, ValueError):
        return None, "error:invalid_fields"
    if qty <= 0 or price <= 0:
        return None, "error:non_positive_fields"
    trace_id = str(data.get(FieldName.TRACE_ID) or uuid.uuid4())
    return (
        ParsedDecision(
            side=side,
            symbol=symbol,
            qty=qty,
            price=price,
            strategy_id=strategy_id,
            trace_id=trace_id,
        ),
        None,
    )


def _as_score(v: Any) -> float | None:
    """Parse a score value from any wire format into a float, or None if absent/invalid.

    Handles:
    - None / "" (EventBus serialises None → "") → None (treat as absent)
    - "0.0" (Redis string for zero confidence) → 0.0 (preserved, not promoted)
    - 0.0 (Python float, e.g. from tests) → 0.0 (preserved, not promoted)
    - "n/a" or any non-numeric string → None (treat as absent, never raises)
    """
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract_decision_scores(data: dict) -> tuple[float, float]:
    """Return ``(signal_confidence, reasoning_score)`` from a decision payload.

    Falls back to 0.5 only when the field is truly absent (None or "").
    Python float 0.0 and Redis string "0.0" both correctly stay at 0.0 so a
    zero-confidence signal stays gated and is never promoted to the default.
    Malformed values like "n/a" are treated as absent (fall through) rather
    than raising ValueError and sending the decision to the DLQ.
    """
    _sc_keys = [FieldName.SIGNAL_CONFIDENCE, FieldName.COMPOSITE_SCORE, FieldName.CONFIDENCE]
    signal_confidence = next(
        (s for k in _sc_keys if (s := _as_score(data.get(k))) is not None),
        0.5,
    )
    rs = _as_score(data.get(FieldName.REASONING_SCORE))
    reasoning_score = rs if rs is not None else signal_confidence
    return signal_confidence, reasoning_score


def compute_execution_score(
    signal_confidence: float,
    reasoning_score: float,
    historical_perf: float = 0.6,
) -> float:
    """Weighted execution gate score: signal 50%, reasoning 30%, historical 20%.

    ``historical_perf`` defaults to 0.6 (slight optimism when there is no
    trading history) so that MOMENTUM-tier signals (confidence ≈ 0.55) can
    clear the 0.55 threshold:
    ``0.55 * 0.5 + 0.55 * 0.3 + 0.6 * 0.2 = 0.56 > 0.55``.
    """
    return (signal_confidence * 0.50) + (reasoning_score * 0.30) + (historical_perf * 0.20)


def check_execution_gate(
    side: str,
    symbol: str,
    final_score: float,
    threshold: float = EXECUTION_DECISION_THRESHOLD,
    market_open: bool = True,
) -> str | None:
    """Run the three pre-execution gates without side effects.

    Returns a gate-reason string if the decision should be blocked, or
    ``None`` if all gates pass and the order may proceed.

    Gate 1 — advisory actions (hold / reject / flat): skipped without submitting.
    Gate 2 — weighted score threshold: weak signals are filtered.
    Gate 3 — market clock: equities only; crypto is always open.
    """
    if side in NO_ORDER_ACTIONS:
        return f"hold:{side}"
    if final_score < threshold:
        return f"gated:score:{final_score:.3f}"
    if not market_open:
        return "blocked:market_closed"
    return None


def check_confidence_gate(
    signal_confidence: float,
    side: str,
    threshold: float = SIGNAL_CONFIDENCE_MIN_GATE,
) -> str | None:
    """Return gate reason string if signal confidence is below threshold.

    Advisory actions (hold/reject/flat) bypass this gate — they don't trade.
    Returns None if the trade may proceed.
    """
    if side in NO_ORDER_ACTIONS:
        return None
    if signal_confidence < threshold:
        return f"gated:low_confidence:{signal_confidence:.3f}"
    return None


def check_net_ev_gate(
    signal_confidence: float,
    abs_pct_move: float,
    slippage_pct: float = SLIPPAGE_PCT_PER_SIDE,
) -> str | None:
    """Return gate reason if net expected value after costs is negative.

    Expected return is approximated as confidence × |pct_move| / 100.
    Round-trip cost is 2 × slippage_pct.
    Returns None if the trade has positive net expected value.
    """
    if abs_pct_move <= 0:
        return None  # No price data — skip gate
    expected_return = signal_confidence * (abs_pct_move / 100.0)
    round_trip_cost = slippage_pct * 2
    net_ev = expected_return - round_trip_cost
    if net_ev < 0:
        return f"gated:negative_net_ev:{net_ev:.5f}"
    return None
