"""Live positions + PnL endpoints sourced from the PaperBroker.

The PaperBroker (Redis ``paper:positions``) is the single source of truth for
open positions. On each request we refresh the in-memory runtime-store mirror
from the broker, then serve the normalized view the dashboard consumes — so the
positions list and PnL summary can never drift from what the execution engine
actually holds. Survives a cold restart: the broker repopulates from Redis and
the mirror is rebuilt on the next read.

Falls back to the runtime-store mirror (hydrated at startup) when the broker is
not wired yet, so the endpoints always return real data and never 500.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from api.constants import DEFAULT_PAPER_CASH, REDIS_KEY_PRICES, VALID_SYMBOLS, FieldName
from api.main_state import get_paper_broker
from api.observability import log_structured
from api.runtime_state import get_runtime_store
from api.utils import now_iso

router = APIRouter(tags=["positions"])


async def _refresh_mirror_from_broker() -> str:
    """Pull every supported symbol's position from the broker into the mirror.

    Returns the data source label ("paper_broker" or "in_memory") so callers can
    surface provenance on the UI.
    """
    broker = get_paper_broker()
    if broker is None:
        return "in_memory"
    store = get_runtime_store()
    try:
        # One MGET for every symbol instead of a GET per symbol — keeps the
        # request from holding many pooled Redis connections in series.
        positions = await broker.get_positions(list(VALID_SYMBOLS))
    except Exception:
        log_structured("warning", "positions_broker_read_failed", exc_info=True)
        return "in_memory"
    for symbol, position in positions.items():
        store.mirror_broker_position(symbol, position)
    return "paper_broker"


@router.get("/positions")
async def list_positions() -> dict[str, Any]:
    source = await _refresh_mirror_from_broker()
    store = get_runtime_store()
    positions = store.open_positions()
    return {
        FieldName.POSITIONS: positions,
        FieldName.COUNT: len(positions),
        FieldName.SOURCE: source,
        FieldName.TIMESTAMP: now_iso(),
    }


def _account_unavailable(now_iso_str: str) -> dict[str, Any]:
    """Honest shape when broker truth cannot be read: nulls, never fabricated $."""
    return {
        FieldName.CASH: None,
        FieldName.EQUITY: None,
        FieldName.BUYING_POWER: None,
        FieldName.TOTAL_PNL: None,
        FieldName.STARTING_CASH: DEFAULT_PAPER_CASH,
        FieldName.SOURCE: "unavailable",
        FieldName.TIMESTAMP: now_iso_str,
    }


@router.get("/account")
async def get_account() -> dict[str, Any]:
    """Real paper-account snapshot straight from broker truth.

    Cash is the PaperBroker's actual balance (Redis ``paper:cash`` — every agent
    fill ever, surviving restarts), and equity marks the broker's open positions
    to the live price cache. This replaces deriving equity client-side from the
    localStorage-capped order history, which drifted from broker truth over long
    sessions. Buying power equals cash: the paper account is cash-only (no margin).
    """
    now_iso_str = now_iso()
    broker = get_paper_broker()
    if broker is None:
        return _account_unavailable(now_iso_str)
    try:
        symbols = sorted(VALID_SYMBOLS)
        cash = await broker.get_cash()
        positions = await broker.get_positions(symbols)
        price_raws = await broker.redis.mget([REDIS_KEY_PRICES.format(symbol=s) for s in symbols])
        marks: dict[str, float] = {}
        for symbol, raw in zip(symbols, price_raws, strict=True):
            if not raw:
                continue
            try:
                live = float(json.loads(raw).get(FieldName.PRICE) or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if live > 0:
                marks[symbol] = live

        positions_value = 0.0
        for symbol, position in positions.items():
            qty = float(position.get(FieldName.QTY, 0) or 0)  # signed; shorts < 0
            if abs(qty) < 1e-12:
                continue
            mark = (
                marks.get(symbol)
                or float(position.get(FieldName.CURRENT_PRICE, 0) or 0)
                or float(position.get(FieldName.ENTRY_PRICE, 0) or 0)
            )
            positions_value += qty * mark

        equity = cash + positions_value
        return {
            FieldName.CASH: round(cash, 2),
            FieldName.EQUITY: round(equity, 2),
            FieldName.BUYING_POWER: round(cash, 2),
            FieldName.TOTAL_PNL: round(equity - DEFAULT_PAPER_CASH, 2),
            FieldName.STARTING_CASH: DEFAULT_PAPER_CASH,
            FieldName.SOURCE: "paper_broker",
            FieldName.TIMESTAMP: now_iso_str,
        }
    except Exception:
        log_structured("warning", "account_broker_read_failed", exc_info=True)
        return _account_unavailable(now_iso_str)


@router.get("/pnl")
async def get_pnl() -> dict[str, Any]:
    source = await _refresh_mirror_from_broker()
    store = get_runtime_store()
    payload = store.paired_pnl_payload()
    return {
        FieldName.CLOSED_TRADES: payload[FieldName.CLOSED_TRADES],
        FieldName.OPEN_POSITIONS: payload[FieldName.OPEN_POSITIONS],
        FieldName.SUMMARY: payload[FieldName.SUMMARY],
        FieldName.SOURCE: source,
        FieldName.TIMESTAMP: now_iso(),
    }
