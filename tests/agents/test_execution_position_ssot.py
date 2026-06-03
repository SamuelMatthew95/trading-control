"""Invariants for the PaperBroker-as-position-source-of-truth refactor.

The InMemoryStore position is a mirror of the PaperBroker (Redis), updated only
via the single post-fill hook. These tests prove the mirror never drifts from
the broker — including the add-to-position case where the old apply_signed_delta
kept the first entry price while the broker uses a weighted average — and that a
round-trip close records realized PnL on an order.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from api.constants import FieldName
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.runtime_state import get_runtime_store
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.metrics_calc import closed_trade_stats
from api.startup import _hydrate_positions_from_broker

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_dlq():
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # kill switch / pause off
    redis.set = AsyncMock(return_value=True)  # locks + dedup acquire
    redis.delete = AsyncMock()
    redis.setnx = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def memory_engine(mock_bus, mock_dlq, mock_redis, monkeypatch):
    """An ExecutionEngine in memory mode backed by a REAL PaperBroker on fakeredis."""
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)
    broker = PaperBroker(redis_client=fakeredis.aioredis.FakeRedis(decode_responses=True))
    engine = ExecutionEngine(bus=mock_bus, dlq=mock_dlq, redis_client=mock_redis, broker=broker)
    return engine, broker


def _order(side: str, qty: float, price: float, ts: str) -> dict:
    return {
        "strategy_id": "strat-ssot",
        "symbol": "BTC/USD",
        "side": side,
        "qty": qty,
        "price": price,
        "timestamp": ts,
        "trace_id": f"trace-{side}-{ts}",
        "composite_score": 0.75,
        "signal_type": "MOMENTUM",
    }


async def test_store_position_mirrors_broker_after_add(memory_engine):
    """After adding to a long, the store's avg cost equals the broker's weighted
    average — not the first fill price (the old apply_signed_delta drift)."""
    engine, broker = memory_engine
    await engine.process(_order("buy", 10.0, 100.0, "2024-01-01T12:00:00+00:00"))
    await engine.process(_order("buy", 10.0, 120.0, "2024-01-01T12:01:00+00:00"))

    store_pos = get_runtime_store().positions["BTC/USD"]
    broker_pos = await broker.get_position("BTC/USD")

    assert float(store_pos["qty"]) == pytest.approx(abs(float(broker_pos["qty"])))  # 20
    # The mirror invariant: store avg cost == broker entry price.
    assert float(store_pos["avg_cost"]) == pytest.approx(float(broker_pos["entry_price"]))
    # And it is a weighted average (~110), strictly above the first fill (~100).
    assert float(store_pos["avg_cost"]) > 100.0


async def test_roundtrip_close_sets_order_pnl(memory_engine):
    """A BUY then a full SELL closes the position and records realized PnL."""
    engine, _broker = memory_engine
    await engine.process(_order("buy", 10.0, 100.0, "2024-01-01T12:00:00+00:00"))
    await engine.process(_order("sell", 10.0, 110.0, "2024-01-01T12:05:00+00:00"))

    store = get_runtime_store()
    assert store.get_active_position_count() == 0  # flat after full close

    stats = closed_trade_stats(store.orders)
    assert stats.winning == 1  # bought ~100, sold ~110 → a winning closed trade
    assert stats.realized_pnl > 0

    # The round-trip close is also recorded in closed_trades (populated by the
    # canonical fill path, not only the replay helper) with the same realized PnL.
    assert len(store.closed_trades) == 1
    assert store.closed_trades[0][FieldName.PNL] == pytest.approx(stats.realized_pnl)


async def test_sell_without_position_records_no_order(memory_engine):
    """The rejection invariant still holds: a SELL with no open long never
    creates an order or a position (rejected before any fill)."""
    engine, broker = memory_engine
    await engine.process(_order("sell", 5.0, 100.0, "2024-01-01T12:00:00+00:00"))

    store = get_runtime_store()
    assert store.orders == []
    assert store.get_active_position_count() == 0
    assert not (await broker.get_position("BTC/USD")).get("qty")


async def test_startup_hydration_mirrors_broker_positions(monkeypatch):
    """Startup hydration seeds the store mirror from carried-over broker state."""
    monkeypatch.setattr("api.startup.is_db_available", lambda: False)
    broker = PaperBroker(redis_client=fakeredis.aioredis.FakeRedis(decode_responses=True))
    await broker.place_order("BTC/USD", "buy", 5.0, 100.0)

    store = get_runtime_store()
    assert "BTC/USD" not in store.positions  # store starts empty

    await _hydrate_positions_from_broker(broker)

    assert store.has_active_position("BTC/USD")
    broker_pos = await broker.get_position("BTC/USD")
    assert float(store.positions["BTC/USD"]["qty"]) == pytest.approx(abs(float(broker_pos["qty"])))
