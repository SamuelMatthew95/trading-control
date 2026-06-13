"""End-to-end proof that in-memory mode works: a BUY → SELL round-trip flows
all the way to the dashboard payloads.

Drives the real ExecutionEngine in memory mode (real PaperBroker on fakeredis)
and asserts the dashboard sees what actually happened: the open position after
a BUY, then realized PnL / win rate / closed trade / daily-change after the SELL.
This is the live mode (Postgres down), so it is the path the operator sees.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from api.constants import FieldName
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.runtime_state import get_runtime_store
from api.services.dashboard.pnl import _in_memory_pnl_payload
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine

pytestmark = pytest.mark.asyncio


@pytest.fixture
def memory_engine(monkeypatch):
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.setnx = AsyncMock(return_value=True)
    broker = PaperBroker(redis_client=fakeredis.aioredis.FakeRedis(decode_responses=True))
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)
    return engine, broker


def _order(side: str, qty: float, price: float, ts: str) -> dict:
    return {
        "strategy_id": "strat-e2e",
        "symbol": "BTC/USD",
        "side": side,
        "qty": qty,
        "price": price,
        "timestamp": ts,
        "trace_id": f"trace-{side}-{ts}",
        "composite_score": 0.75,
        "signal_type": "MOMENTUM",
    }


async def test_buy_then_sell_round_trip_reaches_the_dashboard(memory_engine):
    engine, _broker = memory_engine
    store = get_runtime_store()

    # --- BUY: opens a position the dashboard can see -----------------------
    await engine.process(_order("buy", 1.0, 100.0, "2024-01-01T12:00:00+00:00"))

    snapshot = store.dashboard_fallback_snapshot()
    assert len(snapshot[FieldName.POSITIONS]) == 1
    assert store.get_active_position_count() == 1

    pnl_after_buy = _in_memory_pnl_payload()
    assert pnl_after_buy[FieldName.ACTIVE_POSITIONS] == 1
    assert pnl_after_buy[FieldName.WINNING_TRADES] == 0  # open fill is not a closed trade
    assert pnl_after_buy[FieldName.TOTAL_PNL] == 0.0  # no realized PnL yet

    # --- SELL: closes it → realized PnL shows on the dashboard -------------
    await engine.process(_order("sell", 1.0, 110.0, "2024-01-01T12:05:00+00:00"))

    assert store.get_active_position_count() == 0  # flat after full close
    pnl_after_sell = _in_memory_pnl_payload()
    assert pnl_after_sell[FieldName.ACTIVE_POSITIONS] == 0
    assert pnl_after_sell[FieldName.TOTAL_PNL] > 0  # bought ~100, sold ~110
    assert pnl_after_sell[FieldName.WINNING_TRADES] == 1
    assert pnl_after_sell["win_rate"] == 1.0  # 1 winner / (1 winner + 0 losers)

    # Closed-trade list + daily-change tile reflect the round-trip.
    assert len(store.closed_trades) == 1
    final_snapshot = store.dashboard_fallback_snapshot()
    assert len(final_snapshot[FieldName.POSITIONS]) == 0
    assert final_snapshot[FieldName.DAILY_CHANGE_PCT] > 0
    assert final_snapshot[FieldName.DAILY_PNL] > 0


async def test_sell_with_no_position_leaves_dashboard_empty(memory_engine):
    """The other half of the original symptom: a SELL with no holding produces
    no order, no position, no PnL — the dashboard stays honestly empty."""
    engine, _broker = memory_engine
    await engine.process(_order("sell", 1.0, 100.0, "2024-01-01T12:00:00+00:00"))

    store = get_runtime_store()
    assert store.orders == []
    assert store.get_active_position_count() == 0
    pnl = _in_memory_pnl_payload()
    assert pnl[FieldName.TOTAL_PNL] == 0.0
    assert pnl[FieldName.ACTIVE_POSITIONS] == 0


async def test_round_trip_close_mirrors_identity_fields_to_redis(memory_engine):
    """Regression: mirror entries carried no order/trace ids, so startup
    hydration could not rebuild renderable Trade Feed rows from them — the
    feed normalizer drops id-less rows and the panel blanked after restarts."""
    from api.services.redis_store import RedisStore, get_redis_store, set_redis_store

    engine, broker = memory_engine
    previous = get_redis_store()
    set_redis_store(RedisStore(broker.redis))
    try:
        await engine.process(_order("buy", 1.0, 100.0, "2024-01-01T12:00:00+00:00"))
        await engine.process(_order("sell", 1.0, 110.0, "2024-01-01T12:05:00+00:00"))

        mirrored = await get_redis_store().list_closed_trades()
    finally:
        set_redis_store(previous)

    assert len(mirrored) == 1
    entry = mirrored[0]
    assert entry[FieldName.SYMBOL] == "BTC/USD"
    assert entry[FieldName.EXECUTION_TRACE_ID] == "trace-sell-2024-01-01T12:05:00+00:00"
    assert entry[FieldName.ORDER_ID]
    assert entry[FieldName.SESSION_ID] == "strat-e2e"
    assert entry[FieldName.STATUS] == "filled"
