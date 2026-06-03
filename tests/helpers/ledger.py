"""Test-only decision-replay helper (formerly ``InMemoryStore.apply_decision``).

Replays an advisory decision INTO the ledger (dedup + open/close + realized
PnL) so dashboard tests can seed store state without driving the full
ExecutionEngine. This is NOT a production path — the live engine records fills
via ``ExecutionEngine._record_fill_to_store`` (broker-mirrored positions).
Realized PnL uses the same canonical ``compute_realized_pnl`` so the replay can
never diverge numerically from production.

It was moved out of ``api/in_memory_store.py`` so the production store carries
only canonical mutators (``add_order`` / ``mirror_broker_position`` /
``add_closed_trade`` / ``record_decision``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.constants import FieldName, LogType, OrderSide, PositionSide
from api.in_memory_store import DEFAULT_TRADE_NOTIONAL, POSITION_EPSILON, InMemoryStore
from api.services.execution.position_math import compute_realized_pnl


def apply_decision(store: InMemoryStore, payload: dict[str, Any]) -> dict[str, Any]:
    """Replay one decision into ``store``; returns the recorded decision event."""
    decision_key = store._decision_key(payload)
    if decision_key in store.applied_decision_keys:
        return {
            FieldName.ID: payload.get(FieldName.ID)
            or payload.get(FieldName.TRACE_ID)
            or decision_key,
            FieldName.DEDUPLICATED: True,
        }
    store.applied_decision_keys.add(decision_key)
    action = str(payload.get(FieldName.ACTION, "hold")).upper()
    symbol = str(payload.get(FieldName.SYMBOL) or "").strip()
    price = store._safe_float(payload.get(FieldName.PRICE)) or 0.0
    explicit_quantity = store._safe_float(payload.get(FieldName.QTY))
    event = {
        FieldName.ID: payload.get(FieldName.ID)
        or payload.get(FieldName.TRACE_ID)
        or f"mem-dec-{len(store.decisions) + 1}",
        FieldName.TRACE_ID: payload.get(FieldName.TRACE_ID),
        "timestamp": payload.get(FieldName.TIMESTAMP) or datetime.now(timezone.utc).isoformat(),
        FieldName.SYMBOL: symbol,
        FieldName.ACTION: action,
        FieldName.PRICE: price,
        FieldName.QTY: explicit_quantity or 0.0,
        FieldName.CONFIDENCE: store._safe_float(payload.get(FieldName.CONFIDENCE)),
        FieldName.AGENT: payload.get(FieldName.AGENT) or "reasoning_agent",
        FieldName.REASON: payload.get(LogType.REASONING_SUMMARY) or payload.get(FieldName.REASON),
    }
    store.decisions.append(event)
    if len(store.decisions) > 500:
        store.decisions = store.decisions[-500:]
    if action not in {"BUY", "SELL"} or not symbol or price <= 0:
        return event
    pos = store.positions.get(
        symbol, {FieldName.SYMBOL: symbol, FieldName.QTY: 0.0, FieldName.AVG_ENTRY_PRICE: 0.0}
    )
    pos_qty = store._safe_float(pos.get(FieldName.QTY)) or 0.0
    avg = store._safe_float(pos.get(FieldName.AVG_ENTRY_PRICE)) or price
    if action == "BUY":
        quantity = explicit_quantity
        if (quantity is None or quantity <= 0) and price > 0:
            quantity = DEFAULT_TRADE_NOTIONAL / price
        if quantity is None or quantity <= 0:
            return event
        event[FieldName.QTY] = quantity
        new_qty = pos_qty + quantity
        new_avg = ((avg * pos_qty) + (price * quantity)) / new_qty if new_qty > 0 else price
        pos.update(
            {
                FieldName.SIDE: "long",
                FieldName.QTY: new_qty,
                FieldName.AVG_ENTRY_PRICE: new_avg,
                FieldName.UNREALIZED_PNL: 0.0,
                FieldName.PRICE: price,
            }
        )
        store.positions[symbol] = pos
    else:
        if explicit_quantity is None or explicit_quantity <= 0:
            sell_qty = pos_qty
        else:
            sell_qty = min(pos_qty, explicit_quantity)
        event[FieldName.QTY] = sell_qty
        if sell_qty <= 0:
            return event
        # Canonical realized-PnL math, shared with the execution fill path.
        realized = compute_realized_pnl(
            {
                FieldName.SIDE: PositionSide.LONG,
                FieldName.ENTRY_PRICE: avg,
                FieldName.QTY: pos_qty,
            },
            OrderSide.SELL,
            sell_qty,
            price,
        )
        remaining = max(pos_qty - sell_qty, 0.0)
        store.closed_trades.append(
            {
                FieldName.SYMBOL: symbol,
                "entry_price": avg,
                "exit_price": price,
                FieldName.QTY: sell_qty,
                FieldName.PNL: realized,
                FieldName.TIMESTAMP: event[FieldName.TIMESTAMP],
            }
        )
        store.orders.append(
            {
                FieldName.SYMBOL: symbol,
                FieldName.PNL: realized,
                "status": "closed",
                FieldName.CREATED_AT: event[FieldName.TIMESTAMP],
            }
        )
        if remaining <= POSITION_EPSILON:
            store.positions.pop(symbol, None)
        else:
            pos.update(
                {
                    FieldName.QTY: remaining,
                    FieldName.AVG_ENTRY_PRICE: avg,
                    FieldName.PRICE: price,
                }
            )
            store.positions[symbol] = pos
    paired = store.paired_pnl_payload()[FieldName.SUMMARY]
    store.equity_curve.append(
        {
            FieldName.TIMESTAMP: event[FieldName.TIMESTAMP],
            FieldName.VALUE: paired[FieldName.TOTAL_PNL],
            FieldName.REALIZED_PNL: paired[FieldName.REALIZED_PNL],
            FieldName.UNREALIZED_PNL: paired[FieldName.UNREALIZED_PNL],
            FieldName.TOTAL_PNL: paired[FieldName.TOTAL_PNL],
        }
    )
    if len(store.equity_curve) > 1000:
        store.equity_curve = store.equity_curve[-1000:]
    return event
