"""Tests for the price poller worker."""

from __future__ import annotations

import json
import ssl
import time
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import httpx
import pytest

from api.config import settings
from api.constants import REDIS_PRICES_TTL_SECONDS, FieldName
from api.workers.price_poller import (
    _create_alpaca_client,
    _due_asset_classes,
    _fetch_crypto,
    _fetch_stocks,
    _is_ssl_eof,
    _PollerState,
    _run_poll_cycle,
    build_symbol_payload,
    build_symbol_payloads,
    flush_to_db,
    publish_to_redis,
)


@pytest.fixture
async def redis():
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield r
    await r.aclose()


def _make_httpx_response(json_body: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()  # no-op for 2xx
    return resp


# ---------------------------------------------------------------------------
# _is_ssl_eof — SSL EOF detection through exception chain
# ---------------------------------------------------------------------------


async def test_is_ssl_eof_detects_ssl_zero_return_error():
    exc = ssl.SSLZeroReturnError(6, "TLS/SSL connection has been closed (EOF)")
    assert _is_ssl_eof(exc) is True


async def test_is_ssl_eof_detects_generic_ssl_error():
    exc = ssl.SSLError(1, "SSL handshake failed")
    assert _is_ssl_eof(exc) is True


async def test_is_ssl_eof_detects_through_httpx_connect_error():
    """httpx wraps ssl.SSLError in ConnectError during TLS handshake."""
    ssl_exc = ssl.SSLZeroReturnError(6, "EOF")
    httpx_exc = httpx.ConnectError("SSL EOF")
    httpx_exc.__cause__ = ssl_exc
    assert _is_ssl_eof(httpx_exc) is True


async def test_is_ssl_eof_detects_through_httpx_remote_protocol_error():
    """httpx wraps ssl.SSLError in RemoteProtocolError after connection."""
    ssl_exc = ssl.SSLZeroReturnError(6, "EOF")
    httpx_exc = httpx.RemoteProtocolError("remote EOF")
    httpx_exc.__cause__ = ssl_exc
    assert _is_ssl_eof(httpx_exc) is True


async def test_is_ssl_eof_ignores_timeout():
    assert _is_ssl_eof(httpx.ReadTimeout("timed out")) is False


async def test_is_ssl_eof_ignores_generic_runtime_error():
    assert _is_ssl_eof(RuntimeError("network error")) is False


async def test_is_ssl_eof_ignores_http_status_error():
    request = httpx.Request("GET", "https://data.alpaca.markets/v2/test")
    response = httpx.Response(500, request=request)
    exc = httpx.HTTPStatusError("Server error", request=request, response=response)
    assert _is_ssl_eof(exc) is False


# ---------------------------------------------------------------------------
# _create_alpaca_client — smoke test (no network)
# ---------------------------------------------------------------------------


async def test_create_alpaca_client_returns_async_client(monkeypatch):
    monkeypatch.setattr("api.workers.price_poller.settings.ALPACA_API_KEY", "test-key")
    monkeypatch.setattr("api.workers.price_poller.settings.ALPACA_SECRET_KEY", "test-secret")
    client = _create_alpaca_client()
    assert isinstance(client, httpx.AsyncClient)
    # Explicit timeouts must be set — never timeout=None (prevents threadpool starvation)
    assert client.timeout.connect is not None
    assert client.timeout.read is not None
    assert client.timeout.connect == pytest.approx(5.0)
    assert client.timeout.read == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# _fetch_crypto — response parsing
# ---------------------------------------------------------------------------


async def test_fetch_crypto_returns_bid_price():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_make_httpx_response(
            {
                "quotes": {
                    "BTC/USD": {"bp": 50000.0, "ap": 50001.0},
                    "ETH/USD": {"bp": 3000.0, "ap": 3001.0},
                }
            }
        )
    )
    result = await _fetch_crypto(mock_client, ["BTC/USD", "ETH/USD"])
    assert result == {"BTC/USD": 50000.0, "ETH/USD": 3000.0}


async def test_fetch_crypto_uses_ask_when_bid_is_zero():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_make_httpx_response({"quotes": {"BTC/USD": {"bp": 0.0, "ap": 49999.0}}})
    )
    result = await _fetch_crypto(mock_client, ["BTC/USD"])
    assert result["BTC/USD"] == 49999.0


async def test_fetch_crypto_skips_zero_price():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_make_httpx_response({"quotes": {"BTC/USD": {"bp": 0.0, "ap": 0.0}}})
    )
    result = await _fetch_crypto(mock_client, ["BTC/USD"])
    assert "BTC/USD" not in result


async def test_fetch_crypto_skips_missing_symbol():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_make_httpx_response({"quotes": {}}))
    result = await _fetch_crypto(mock_client, ["BTC/USD"])
    assert result == {}


# ---------------------------------------------------------------------------
# _fetch_stocks — response parsing
# ---------------------------------------------------------------------------


async def test_fetch_stocks_returns_bid_price():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_make_httpx_response(
            {
                "quotes": {
                    "AAPL": {"bp": 182.0, "ap": 182.1},
                    "TSLA": {"bp": 250.0, "ap": 250.5},
                }
            }
        )
    )
    result = await _fetch_stocks(mock_client, ["AAPL", "TSLA"])
    assert result == {"AAPL": 182.0, "TSLA": 250.0}


async def test_fetch_stocks_uses_ask_when_bid_is_zero():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_make_httpx_response({"quotes": {"AAPL": {"bp": 0.0, "ap": 183.5}}})
    )
    result = await _fetch_stocks(mock_client, ["AAPL"])
    assert result["AAPL"] == 183.5


async def test_fetch_crypto_propagates_ssl_eof_error():
    """SSL EOF must propagate so poll_prices() can detect and recreate the client."""
    ssl_exc = ssl.SSLZeroReturnError(6, "EOF")
    httpx_exc = httpx.ConnectError("SSL EOF")
    httpx_exc.__cause__ = ssl_exc

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx_exc)

    with pytest.raises(httpx.ConnectError):
        await _fetch_crypto(mock_client, ["BTC/USD"])


async def test_fetch_stocks_propagates_timeout_error():
    """Timeouts must propagate so poll_prices() can log and degrade gracefully."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(httpx.ReadTimeout):
        await _fetch_stocks(mock_client, ["AAPL"])


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


async def test_publish_to_redis_market_events_has_msg_id(redis):
    """Every market_events entry must carry msg_id so BaseStreamConsumer never raises."""
    payloads = [
        {
            "symbol": "BTC/USD",
            "price": 60000.0,
            "change": 0.0,
            "pct": 0.0,
            "ts": 1,
            "trace_id": "t-msg-id",
        }
    ]
    await publish_to_redis(redis, payloads)
    messages = await redis.xread({"market_events": "0-0"}, count=10)
    assert messages, "Expected at least one message in market_events"
    _stream_name, entries = messages[0]
    _redis_id, fields = entries[0]
    assert "msg_id" in fields, "msg_id must be present in market_events xadd payload"
    assert fields["msg_id"]  # non-empty


async def test_publish_to_redis_market_events_has_schema_version(redis):
    """Every market_events entry must carry schema_version='v3'."""
    payloads = [
        {
            "symbol": "ETH/USD",
            "price": 3000.0,
            "change": 0.0,
            "pct": 0.0,
            "ts": 1,
            "trace_id": "t-sv",
        }
    ]
    await publish_to_redis(redis, payloads)
    messages = await redis.xread({"market_events": "0-0"}, count=10)
    _stream_name, entries = messages[0]
    _redis_id, fields = entries[0]
    assert fields.get("schema_version") == "v3"


async def test_publish_to_redis_msg_ids_are_unique_per_symbol(redis):
    """Each symbol tick must get its own unique msg_id."""
    payloads = [
        {
            "symbol": "BTC/USD",
            "price": 60000.0,
            "change": 0.0,
            "pct": 0.0,
            "ts": 1,
            "trace_id": "a",
        },
        {"symbol": "ETH/USD", "price": 3000.0, "change": 0.0, "pct": 0.0, "ts": 1, "trace_id": "b"},
    ]
    await publish_to_redis(redis, payloads)
    messages = await redis.xread({"market_events": "0-0"}, count=10)
    _stream_name, entries = messages[0]
    msg_ids = [fields["msg_id"] for _rid, fields in entries]
    assert len(set(msg_ids)) == len(msg_ids), "Each tick should have a unique msg_id"


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
    from unittest.mock import patch

    factory = _MockSessionFactory()
    payloads = [
        {"symbol": "BTC/USD", "price": 50000.0, "change": 0.0, "pct": 0.0, "ts": 1},
        {"symbol": "ETH/USD", "price": 3000.0, "change": 0.0, "pct": 0.0, "ts": 1},
    ]
    with (
        patch("api.workers.price_poller.AsyncSessionFactory", factory),
        patch("api.workers.price_poller.is_db_available", return_value=True),
    ):
        await flush_to_db(payloads)
    # 2 symbols × 2 statements (prices_snapshot + system_metrics) = 4 executions
    assert len(factory.session.executed) == 4


async def test_flush_to_db_handles_db_error_gracefully():
    """DB failure should not propagate — poller must continue."""
    from unittest.mock import patch

    payloads = [{"symbol": "BTC/USD", "price": 50000.0, "change": 0.0, "pct": 0.0, "ts": 1}]
    with patch("api.workers.price_poller.AsyncSessionFactory", side_effect=RuntimeError("db down")):
        # Should not raise
        await flush_to_db(payloads)


# ---------------------------------------------------------------------------
# _due_asset_classes — per-class cadence + market-hours gating (pure)
# ---------------------------------------------------------------------------


def test_due_classes_crypto_only_when_market_closed():
    due = _due_asset_classes(
        now=1000.0,
        last_fetch={FieldName.CRYPTO: 0.0, FieldName.STOCKS: 0.0},
        crypto_interval=30,
        stock_interval=60,
        stocks_open=False,
    )
    assert due == [FieldName.CRYPTO]  # zero stock work overnight


def test_due_classes_both_when_open_and_due():
    due = _due_asset_classes(
        1000.0, {FieldName.CRYPTO: 0.0, FieldName.STOCKS: 0.0}, 30, 60, stocks_open=True
    )
    assert set(due) == {FieldName.CRYPTO, FieldName.STOCKS}


def test_due_classes_respects_interval():
    # Both fetched 5s ago — neither interval has elapsed.
    due = _due_asset_classes(
        10.0, {FieldName.CRYPTO: 5.0, FieldName.STOCKS: 5.0}, 30, 60, stocks_open=True
    )
    assert due == []


def test_due_classes_crypto_due_stock_not_yet():
    # Crypto interval (30s) elapsed, stock interval (60s) not.
    due = _due_asset_classes(
        40.0, {FieldName.CRYPTO: 0.0, FieldName.STOCKS: 0.0}, 30, 60, stocks_open=True
    )
    assert due == [FieldName.CRYPTO]


# ---------------------------------------------------------------------------
# build_symbol_payloads — pure delta against the in-memory prev-price anchor
# ---------------------------------------------------------------------------


def test_build_symbol_payloads_computes_change_from_prev():
    payloads = build_symbol_payloads({"BTC/USD": 42000.0, "ETH/USD": 3000.0}, {"BTC/USD": 40000.0})
    by_symbol = {p["symbol"]: p for p in payloads}
    assert by_symbol["BTC/USD"]["change"] == 2000.0
    assert abs(by_symbol["BTC/USD"]["pct"] - 5.0) < 0.01
    assert by_symbol["ETH/USD"]["change"] == 0.0  # no prior price → first-tick zero
    assert by_symbol["ETH/USD"]["pct"] == 0.0


def test_build_symbol_payloads_anchor_is_prev_map_not_redis_cache():
    """REGRESSION (no-buys bug): the delta anchor is the explicit prev-price map,
    never the short-TTL Redis cache. A whole cycle computes pct with zero Redis
    reads, so an expired/empty cache can no longer pin pct to 0 and starve the
    momentum (buy/sell) signal."""
    # prev supplied in-memory → real delta even with nothing in any cache.
    moved = build_symbol_payloads({"BTC/USD": 51000.0}, {"BTC/USD": 50000.0})
    assert moved[0]["pct"] == pytest.approx(2.0, abs=0.01)
    assert moved[0]["change"] == pytest.approx(1000.0)
    # absent prev → first-tick zero (one cycle only), not a crash.
    assert build_symbol_payloads({"BTC/USD": 51000.0}, {})[0]["pct"] == 0.0


def test_build_symbol_payloads_empty_returns_empty():
    assert build_symbol_payloads({}, {}) == []


def test_price_cache_ttl_exceeds_poll_interval():
    """Guardrail: the price cache TTL MUST exceed the longest poll interval, or the
    consumer cache (dashboard, RiskGuardian) empties between polls. A 30s TTL with a
    60s stock interval left stock prices blank for half of every window."""
    assert REDIS_PRICES_TTL_SECONDS > settings.STOCK_POLL_INTERVAL_SECONDS
    assert REDIS_PRICES_TTL_SECONDS > settings.CRYPTO_POLL_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# _run_poll_cycle — market-hours gating end-to-end
# ---------------------------------------------------------------------------


def _market(is_open: bool) -> MagicMock:
    m = MagicMock()
    m.is_open.return_value = is_open
    return m


async def test_run_poll_cycle_skips_stocks_when_market_closed(redis, monkeypatch):
    crypto_mock = AsyncMock(return_value={"BTC/USD": 50000.0})
    stock_mock = AsyncMock(return_value={"AAPL": 180.0})
    monkeypatch.setattr("api.workers.price_poller._fetch_crypto", crypto_mock)
    monkeypatch.setattr("api.workers.price_poller._fetch_stocks", stock_mock)

    state = _PollerState(client=MagicMock())
    await _run_poll_cycle(state, redis, _market(False), crypto_interval=30, stock_interval=60)

    crypto_mock.assert_awaited_once()
    stock_mock.assert_not_awaited()  # zero stock Alpaca calls when closed
    assert await redis.get("prices:BTC/USD") is not None
    assert await redis.get("prices:AAPL") is None  # zero stock Redis writes


async def test_run_poll_cycle_fetches_both_when_open(redis, monkeypatch):
    crypto_mock = AsyncMock(return_value={"BTC/USD": 50000.0})
    stock_mock = AsyncMock(return_value={"AAPL": 180.0})
    monkeypatch.setattr("api.workers.price_poller._fetch_crypto", crypto_mock)
    monkeypatch.setattr("api.workers.price_poller._fetch_stocks", stock_mock)

    state = _PollerState(client=MagicMock())
    await _run_poll_cycle(state, redis, _market(True), crypto_interval=30, stock_interval=60)

    crypto_mock.assert_awaited_once()
    stock_mock.assert_awaited_once()
    assert await redis.get("prices:BTC/USD") is not None
    assert await redis.get("prices:AAPL") is not None


async def test_run_poll_cycle_circuit_open_does_no_work(redis, monkeypatch):
    crypto_mock = AsyncMock(return_value={"BTC/USD": 50000.0})
    monkeypatch.setattr("api.workers.price_poller._fetch_crypto", crypto_mock)
    # Circuit open far into the future → cycle returns immediately.
    state = _PollerState(client=MagicMock(), circuit_open_until=time.monotonic() + 999)
    await _run_poll_cycle(state, redis, _market(True), 30, 60)
    crypto_mock.assert_not_awaited()


async def test_run_poll_cycle_pct_survives_expired_cache(redis, monkeypatch):
    """REGRESSION (the 'no buys ever' bug): pct must be derived from the poller's
    own in-memory anchor (_PollerState.last_prices), so a price move yields a
    non-zero pct on the next cycle EVEN WHEN the Redis price cache entry has
    expired (REDIS_PRICES_TTL_SECONDS < poll interval).

    Before the fix, prev was read from the expiring cache → prev always missing →
    pct pinned to 0.0 → every signal classified NEUTRAL/LOW → 'hold' forever →
    no buys and a permanently starved learning loop (Grade/IC/Reflection/etc).
    """
    fetch = AsyncMock(side_effect=[{"BTC/USD": 50000.0}, {"BTC/USD": 51000.0}])
    monkeypatch.setattr("api.workers.price_poller._fetch_crypto", fetch)
    state = _PollerState(client=MagicMock())

    # Cycle 1 — first observation, pct=0 (no prior anchor yet).
    await _run_poll_cycle(state, redis, _market(False), crypto_interval=30, stock_interval=60)
    assert state.last_prices["BTC/USD"] == 50000.0

    # Simulate the cache TTL expiring before the next poll, and make crypto due again.
    await redis.delete("prices:BTC/USD")
    state.last_fetch[FieldName.CRYPTO] = 0.0

    # Cycle 2 — price moved +2%; pct must come from the anchor, not the (gone) cache.
    await _run_poll_cycle(state, redis, _market(False), crypto_interval=30, stock_interval=60)

    messages = await redis.xread({"market_events": "0-0"}, count=10)
    _stream, entries = messages[0]
    last_payload = json.loads(entries[-1][1]["payload"])
    assert last_payload["symbol"] == "BTC/USD"
    assert last_payload["pct"] == pytest.approx(2.0, abs=0.01)
    assert last_payload["change"] == pytest.approx(1000.0)


async def test_run_poll_cycle_anchor_not_advanced_when_publish_fails(redis, monkeypatch):
    """REGRESSION (PR #275 review P2): the prev-price anchor must advance ONLY after
    publish succeeds. If publish_to_redis raises, last_prices must stay put so the
    unpublished move is re-measured next cycle instead of being silently erased.

    Scenario: cycle 1 publishes @50000 (anchor=50000). Cycle 2 fetches 51000 but the
    publish fails — anchor must remain 50000. Cycle 3 fetches 52000 and publishes; its
    pct must be measured from 50000 (the last PUBLISHED price), i.e. +4%, not +1.96%.
    """
    fetch = AsyncMock(
        side_effect=[{"BTC/USD": 50000.0}, {"BTC/USD": 51000.0}, {"BTC/USD": 52000.0}]
    )
    monkeypatch.setattr("api.workers.price_poller._fetch_crypto", fetch)
    state = _PollerState(client=MagicMock())

    # Cycle 1 — publishes, anchor advances to 50000.
    await _run_poll_cycle(state, redis, _market(False), 30, 60)
    assert state.last_prices["BTC/USD"] == 50000.0

    # Cycle 2 — publish raises; the cycle error propagates but anchor must NOT advance.
    boom = AsyncMock(side_effect=RuntimeError("redis pipeline down"))
    monkeypatch.setattr("api.workers.price_poller.publish_to_redis", boom)
    state.last_fetch[FieldName.CRYPTO] = 0.0
    with pytest.raises(RuntimeError):
        await _run_poll_cycle(state, redis, _market(False), 30, 60)
    assert state.last_prices["BTC/USD"] == 50000.0  # unchanged — the fix

    # Cycle 3 — publish restored; pct measured from the last PUBLISHED price (50000).
    monkeypatch.undo()  # restore real publish_to_redis
    monkeypatch.setattr("api.workers.price_poller._fetch_crypto", fetch)
    state.last_fetch[FieldName.CRYPTO] = 0.0
    await _run_poll_cycle(state, redis, _market(False), 30, 60)
    messages = await redis.xread({"market_events": "0-0"}, count=20)
    _stream, entries = messages[0]
    last_payload = json.loads(entries[-1][1]["payload"])
    assert last_payload["pct"] == pytest.approx(4.0, abs=0.01)  # (52000-50000)/50000
    assert state.last_prices["BTC/USD"] == 52000.0


async def test_run_poll_cycle_recreates_client_on_ssl_eof(redis, monkeypatch):
    ssl_exc = ssl.SSLZeroReturnError(6, "EOF")
    httpx_exc = httpx.ConnectError("SSL EOF")
    httpx_exc.__cause__ = ssl_exc
    monkeypatch.setattr("api.workers.price_poller._fetch_crypto", AsyncMock(side_effect=httpx_exc))
    new_client = MagicMock()
    monkeypatch.setattr(
        "api.workers.price_poller._create_alpaca_client", MagicMock(return_value=new_client)
    )
    old_client = AsyncMock()
    state = _PollerState(client=old_client)
    await _run_poll_cycle(state, redis, _market(False), 30, 60)
    old_client.aclose.assert_awaited_once()  # poisoned client evicted
    assert state.client is new_client
    assert state.consecutive_failures == 1
    # last_fetch NOT advanced → retries next cycle
    assert state.last_fetch[FieldName.CRYPTO] == 0.0
