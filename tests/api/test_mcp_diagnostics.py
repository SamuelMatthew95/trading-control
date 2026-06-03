"""Tests for the MCP dashboard-consistency diagnostic tools.

These run against a fakeredis-backed PaperBroker + RedisStore and prove the
tools detect agreement AND divergence between the dashboard's store view and
the broker source of truth.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from api.constants import FieldName
from api.mcp import read_tools
from api.runtime_state import get_runtime_store
from api.services.execution.brokers.paper import PaperBroker
from api.services.redis_store import RedisStore

# No module-level asyncio marker: this file mixes one sync test
# (diagnose_metrics) with async tools; asyncio_mode=auto runs the coroutines.


@pytest.fixture
def fake(monkeypatch):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(read_tools, "get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(read_tools, "get_redis_store", lambda: RedisStore(redis))
    return redis


async def test_diagnose_positions_ok_when_store_mirrors_broker(fake):
    broker = PaperBroker(redis_client=fake)
    await broker.place_order("BTC/USD", "buy", 1.0, 100.0)
    # Mirror the broker into the store (what the fill path does).
    get_runtime_store().mirror_broker_position("BTC/USD", await broker.get_position("BTC/USD"))

    out = (await read_tools.diagnose_positions_data())["data"]
    assert out["ok"] is True
    assert out["broker_open_count"] == 1
    assert out["store_open_count"] == 1
    assert out["mismatches"] == []
    assert out["stale_store_only"] == []
    assert out["missing_in_store"] == []


async def test_diagnose_positions_flags_stale_store_only(fake):
    # A store position the broker does not hold (the pre-fix drift scenario).
    get_runtime_store().positions["ETH/USD"] = {
        FieldName.SYMBOL: "ETH/USD",
        FieldName.SIDE: "long",
        FieldName.QTY: 4.0,
    }
    out = (await read_tools.diagnose_positions_data())["data"]
    assert out["ok"] is False
    assert "ETH/USD" in out["stale_store_only"]


async def test_diagnose_trade_feed_flags_phantom_sell(fake):
    store = RedisStore(fake)
    # SELL advertised for a symbol the broker does not hold → untagged phantom.
    await store.push_decision({FieldName.ACTION: "sell", FieldName.SYMBOL: "AAPL"})
    out = (await read_tools.diagnose_trade_feed_data())["data"]
    assert out["ok"] is False
    assert out["untagged_phantom_sells"] == 1


async def test_diagnose_trade_feed_ok_for_held_sell(fake):
    broker = PaperBroker(redis_client=fake)
    await broker.place_order("BTC/USD", "buy", 1.0, 100.0)  # now held long
    store = RedisStore(fake)
    await store.push_decision({FieldName.ACTION: "sell", FieldName.SYMBOL: "BTC/USD"})
    out = (await read_tools.diagnose_trade_feed_data())["data"]
    assert out["untagged_phantom_sells"] == 0
    assert out["ok"] is True


def test_diagnose_metrics_canonical_win_rate():
    store = get_runtime_store()
    for pnl in (10.0, 5.0, -3.0, 0.0, None):  # 2 win, 1 loss, 1 scratch, 1 open
        store.add_order({FieldName.PNL: pnl})
    out = read_tools.diagnose_metrics_data()["data"]
    assert out["winning_trades"] == 2
    assert out["losing_trades"] == 1
    assert out["closed_trades"] == 3
    assert out["open_trades_excluded"] == 1
    assert out["scratch_trades_excluded"] == 1
    assert out["win_rate"] == round(2 / 3, 4)


async def test_diagnose_dashboard_consistency_aggregates(fake):
    out = (await read_tools.diagnose_dashboard_consistency_data())["data"]
    # Empty account: no positions, no feed, no trades → consistent.
    assert out["ok"] is True
    assert out["issues"] == []
    assert out["equity_consistent"] is True
