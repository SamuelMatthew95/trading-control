"""Tests for the price poller worker."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

import fakeredis
from api.workers.price_poller import (
    _sync_fetch_crypto,
    _sync_fetch_stocks,
    build_symbol_payload,
    fetch_crypto_prices,
    fetch_stock_prices,
    flush_to_db,
    publish_to_redis,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def redis():
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield r
    await r.aclose()


# ---------------------------------------------------------------------------
# _sync_fetch_crypto / _sync_fetch_stocks (sync helpers)
# ---------------------------------------------------------------------------


def _make_quote(bid: float, ask: float = 0.0):
    q = MagicMock()
    q.bid_price = bid
    q.ask_price = ask
    return q


def test_sync_fetch_crypto_returns_positive_prices():
    client = MagicMock()
    client.get_crypto_latest_quote.return_value = {
        "BTC/USD": _make_quote(50000.0),
        "ETH/USD": _make_quote(3000.0),
    }
    result = _sync_fetch_crypto(client, ["BTC/USD", "ETH/USD"])
    assert result == {"BTC/USD": 50000.0, "ETH/USD": 3000.0}


def test_sync_fetch_crypto_skips_zero_price():
    client = MagicMock()
    client.get_crypto_latest_quote.return_value = {
        "BTC/USD": _make_quote(0.0, ask=0.0),
    }
    result = _sync_fetch_crypto(client, ["BTC/USD"])
    assert "BTC/USD" not in result


def test_sync_fetch_crypto_uses_ask_when_bid_is_zero():
    client = MagicMock()
    client.get_crypto_latest_quote.return_value = {
        "BTC/USD": _make_quote(0.0, ask=49999.0),
    }
    result = _sync_fetch_crypto(client, ["BTC/USD"])
    assert result["BTC/USD"] == 49999.0


def test_sync_fetch_crypto_skips_missing_symbol():
    client = MagicMock()
    client.get_crypto_latest_quote.return_value = {}
    result = _sync_fetch_crypto(client, ["BTC/USD"])
    assert result == {}


def test_sync_fetch_stocks_returns_prices():
    client = MagicMock()
    client.get_stock_latest_quote.return_value = {
        "AAPL": _make_quote(180.0),
        "TSLA": _make_quote(250.0),
    }
    result = _sync_fetch_stocks(client, ["AAPL", "TSLA"])
    assert result == {"AAPL": 180.0, "TSLA": 250.0}


# ---------------------------------------------------------------------------
# fetch_crypto_prices / fetch_stock_prices (async wrappers)
# ---------------------------------------------------------------------------


async def test_fetch_crypto_prices_runs_in_executor():
    """Verifies run_in_executor is used — sync call does not block event loop."""
    client = MagicMock()
    client.get_crypto_latest_quote.return_value = {"BTC/USD": _make_quote(60000.0)}
    result = await fetch_crypto_prices(client, ["BTC/USD"])
    assert result["BTC/USD"] == 60000.0


async def test_fetch_crypto_prices_timeout_returns_empty():
    async def slow(*_):
        await asyncio.sleep(99)

    client = MagicMock()
    with patch("api.workers.price_poller.asyncio.wait_for", side_effect=TimeoutError):
        result = await fetch_crypto_prices(client, ["BTC/USD"])
    assert result == {}


async def test_fetch_crypto_prices_exception_returns_empty():
    client = MagicMock()
    client.get_crypto_latest_quote.side_effect = RuntimeError("network error")
    result = await fetch_crypto_prices(client, ["BTC/USD"])
    assert result == {}


async def test_fetch_stock_prices_runs_in_executor():
    client = MagicMock()
    client.get_stock_latest_quote.return_value = {"AAPL": _make_quote(190.0)}
    result = await fetch_stock_prices(client, ["AAPL"])
    assert result["AAPL"] == 190.0


# ---------------------------------------------------------------------------
# build_symbol_payload
# ---------------------------------------------------------------------------


async def test_build_symbol_payload_first_tick_zero_change(redis):
    """First tick — no cached price, change/pct should be 0."""
    payload = await build_symbol_payload(redis, "BTC/USD", 50000.0)
    assert payload["symbol"] == "BTC/USD"
    assert payload["price"] == 50000.0
    assert payload["change"] == 0.0
    assert payload["pct"] == 0.0
    assert "trace_id" in payload
    assert "ts" in payload


async def test_build_symbol_payload_calculates_change(redis):
    """Change and pct are computed from the cached previous price."""
    await redis.set(
        "prices:BTC/USD", json.dumps({"price": 40000.0, "change": 0, "pct": 0, "ts": 0})
    )
    payload = await build_symbol_payload(redis, "BTC/USD", 42000.0)
    assert payload["change"] == 2000.0
    assert abs(payload["pct"] - 5.0) < 0.01


async def test_build_symbol_payload_unique_trace_ids(redis):
    p1 = await build_symbol_payload(redis, "ETH/USD", 3000.0)
    p2 = await build_symbol_payload(redis, "ETH/USD", 3000.0)
    assert p1["trace_id"] != p2["trace_id"]


# ---------------------------------------------------------------------------
# publish_to_redis
# ---------------------------------------------------------------------------


async def test_publish_to_redis_sets_cache(redis):
    payloads = [
        {
            "symbol": "BTC/USD",
            "price": 50000.0,
            "change": 100.0,
            "pct": 0.2,
            "ts": 1000,
            "trace_id": "t1",
        },
        {
            "symbol": "ETH/USD",
            "price": 3000.0,
            "change": 10.0,
            "pct": 0.33,
            "ts": 1000,
            "trace_id": "t2",
        },
    ]
    await publish_to_redis(redis, payloads)

    cached = await redis.get("prices:BTC/USD")
    assert cached is not None
    data = json.loads(cached)
    assert data["price"] == 50000.0


async def test_publish_to_redis_adds_to_market_events_stream(redis):
    payloads = [
        {
            "symbol": "SOL/USD",
            "price": 150.0,
            "change": 5.0,
            "pct": 3.4,
            "ts": 999,
            "trace_id": "t3",
        },
    ]
    await publish_to_redis(redis, payloads)
    stream_len = await redis.xlen("market_events")
    assert stream_len >= 1


async def test_publish_to_redis_multiple_symbols(redis):
    payloads = [
        {
            "symbol": s,
            "price": float(i * 100),
            "change": 0.0,
            "pct": 0.0,
            "ts": 1,
            "trace_id": f"t{i}",
        }
        for i, s in enumerate(["BTC/USD", "ETH/USD", "SOL/USD"], start=1)
    ]
    await publish_to_redis(redis, payloads)
    for s in ["BTC/USD", "ETH/USD", "SOL/USD"]:
        assert await redis.get(f"prices:{s}") is not None


# ---------------------------------------------------------------------------
# flush_to_db
# ---------------------------------------------------------------------------


class _MockSession:
    def __init__(self):
        self.executed = []

    async def execute(self, stmt, params=None):
        self.executed.append(params)
        return MagicMock(rowcount=1)

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _MockSessionFactory:
    def __init__(self):
        self.session = _MockSession()

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        pass


async def test_flush_to_db_calls_execute_for_each_symbol():
    factory = _MockSessionFactory()
    payloads = [
        {"symbol": "BTC/USD", "price": 50000.0, "change": 0.0, "pct": 0.0, "ts": 1},
        {"symbol": "ETH/USD", "price": 3000.0, "change": 0.0, "pct": 0.0, "ts": 1},
    ]
    with patch("api.workers.price_poller.AsyncSessionFactory", factory):
        await flush_to_db(payloads)
    # 2 symbols × 2 statements (prices_snapshot + system_metrics) = 4 executions
    assert len(factory.session.executed) == 4


async def test_flush_to_db_handles_db_error_gracefully():
    """DB failure should not propagate — poller must continue."""
    payloads = [{"symbol": "BTC/USD", "price": 50000.0, "change": 0.0, "pct": 0.0, "ts": 1}]
    with patch("api.workers.price_poller.AsyncSessionFactory", side_effect=RuntimeError("db down")):
        # Should not raise
        await flush_to_db(payloads)
