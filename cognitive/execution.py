"""EXECUTION ENGINE — receives ONLY the final decision. Deterministic, no reasoning.

It does not interpret signals, re-check risk, or call an LLM. Given an approved
decision, the fill price, and the account equity, it deterministically computes
the order size and records a fill. A blocked or HOLD decision yields a SKIPPED
record (qty 0) — so every decision still produces one auditable execution event.

In production this is the seam where the real Alpaca PaperBroker is invoked; the
SIZE and SIDE computed here stay deterministic, only the fill price/latency come
from the broker. The offline backtest gate uses the same arithmetic with a
seeded slippage model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.decision import Decision
from cognitive.events import EventType
from cognitive.risk import RiskGate

FILLED = "filled"
SKIPPED = "skipped"


@dataclass(frozen=True)
class Execution:
    """Deterministic record of what the broker was asked to do."""

    symbol: str
    side: str
    qty: float
    price: float
    notional: float
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.EXECUTION.value,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "price": self.price,
            "notional": self.notional,
            "status": self.status,
        }


def execute(
    decision: Decision,
    gate: RiskGate,
    *,
    symbol: str,
    price: float,
    equity: float,
) -> Execution:
    """Size and record the order. SKIPPED if the gate blocked it or price is bad."""
    if not gate.allowed or price <= 0:
        return Execution(
            symbol=symbol,
            side=decision.action,
            qty=0.0,
            price=price,
            notional=0.0,
            status=SKIPPED,
        )
    notional = equity * gate.requested_position_pct
    qty = round(notional / price, 8)
    return Execution(
        symbol=symbol,
        side=decision.action,
        qty=qty,
        price=price,
        notional=round(notional, 2),
        status=FILLED,
    )
