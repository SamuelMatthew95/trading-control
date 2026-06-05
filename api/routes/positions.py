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

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from api.constants import VALID_SYMBOLS, FieldName
from api.main_state import get_paper_broker
from api.observability import log_structured
from api.runtime_state import get_runtime_store

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
        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
    }


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
        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
    }
