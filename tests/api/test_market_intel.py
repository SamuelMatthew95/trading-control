"""Tests for the live market-intel perception tools."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.constants import FieldName, MacroRegime
from api.services import market_intel
from api.services.market_intel import (
    _is_crypto,
    _pearson,
    _peers,
    _returns,
    _score_sentiment,
    compute_cross_asset_correlation,
    fetch_macro_regime,
    fetch_news_sentiment,
    fetch_order_book_depth,
)

# asyncio runs in auto mode (pytest.ini); async tests need no explicit marker.


# --- pure helpers (the real math, no mocking) -------------------------------


def test_is_crypto_distinguishes_by_slash():
    assert _is_crypto("BTC/USD") is True
    assert _is_crypto("AAPL") is False


def test_peers_are_same_asset_class_excluding_self():
    peers = _peers("BTC/USD")
    assert "BTC/USD" not in peers
    assert all("/" in p for p in peers)  # only crypto peers
    assert "AAPL" not in peers


def test_score_sentiment_is_bounded_and_directional():
    assert _score_sentiment(["stocks surge on record profit"]) > 0
    assert _score_sentiment(["shares plunge amid fraud lawsuit"]) < 0
    assert _score_sentiment(["the company released a statement"]) == 0.0
    assert -1.0 <= _score_sentiment(["surge plunge"]) <= 1.0


def test_returns_and_pearson_detect_perfect_correlation():
    closes = [100.0, 101.0, 102.0, 103.0]
    rets = _returns(closes)
    assert len(rets) == 3
    # A series perfectly correlated with itself → 1.0
    assert _pearson(rets, rets) == 1.0
    # Too few points → None
    assert _pearson([0.1], [0.2]) is None


# --- network-backed tools (httpx client mocked) -----------------------------


def _fake_client(payload: dict):
    """Return a patcher that makes market_intel._client() yield a client whose
    GET returns ``payload`` from .json()."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def _cm():
        yield client

    return patch.object(market_intel, "_client", lambda: _cm())


async def test_order_book_depth_computes_spread_and_imbalance(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    payload = {"quotes": {"BTC/USD": {"bp": 100.0, "ap": 100.5, "bs": 3.0, "as": 1.0}}}
    with _fake_client(payload):
        out = await fetch_order_book_depth("BTC/USD")
    assert out[FieldName.BID] == 100.0
    assert out[FieldName.ASK] == 100.5
    assert out[FieldName.SPREAD_BPS] > 0
    assert out[FieldName.IMBALANCE] == pytest.approx(0.5)  # (3-1)/(3+1)


async def test_order_book_depth_without_api_key_returns_empty(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "")
    assert await fetch_order_book_depth("BTC/USD") == {}


async def test_news_sentiment_uses_cache_when_present():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value='{"sentiment": 0.5, "article_count": 4}')
    out = await fetch_news_sentiment("AAPL", redis)
    assert out[FieldName.SENTIMENT] == 0.5
    redis.set.assert_not_called()  # cache hit — no write


async def test_news_sentiment_scores_and_caches(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    payload = {
        "news": [{"headline": "Company profit surges to record", "summary": "strong growth"}]
    }
    with _fake_client(payload):
        out = await fetch_news_sentiment("AAPL", redis)
    assert out[FieldName.SENTIMENT] > 0
    assert out[FieldName.ARTICLE_COUNT] == 1
    redis.set.assert_awaited_once()  # result cached


async def test_correlation_ranks_most_correlated_peer(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    # BTC and ETH move together; SOL moves opposite.
    bars = {
        "BTC/USD": [{"c": 100}, {"c": 101}, {"c": 102}, {"c": 103}],
        "ETH/USD": [{"c": 50}, {"c": 50.5}, {"c": 51}, {"c": 51.5}],
        "SOL/USD": [{"c": 30}, {"c": 29}, {"c": 28}, {"c": 27}],
    }
    with _fake_client({"bars": bars}):
        out = await compute_cross_asset_correlation("BTC/USD", redis)
    assert out[FieldName.MOST_CORRELATED] == "ETH/USD"
    assert out[FieldName.CORRELATIONS]["ETH/USD"] == pytest.approx(1.0)
    redis.set.assert_awaited_once()


async def test_correlation_request_uses_recent_start_window(monkeypatch):
    """Regression: the bars request must carry a recent `start` (newest-first).

    Without `start`, Alpaca returns the OLDEST bars (ascending), so the tool
    degraded to {} (success: false) on every decision even with valid keys.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    captured: dict = {}
    resp = MagicMock()
    resp.json.return_value = {
        "bars": {
            "BTC/USD": [{"c": 100}, {"c": 101}, {"c": 102}, {"c": 103}],
            "ETH/USD": [{"c": 50}, {"c": 50.5}, {"c": 51}, {"c": 51.5}],
        }
    }
    resp.raise_for_status = MagicMock()

    async def _get(path, params=None):
        captured["params"] = params or {}
        return resp

    client = MagicMock()
    client.get = _get

    @asynccontextmanager
    async def _cm():
        yield client

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    with patch.object(market_intel, "_client", lambda: _cm()):
        out = await compute_cross_asset_correlation("BTC/USD", redis)

    assert "start" in captured["params"]  # a recent window is requested
    assert captured["params"]["sort"] == "desc"  # newest bars first
    start = datetime.fromisoformat(captured["params"]["start"])
    assert (datetime.now(timezone.utc) - start).total_seconds() < 6 * 3600
    assert out  # non-empty result when bars are present


# --- macro regime tool ------------------------------------------------------


async def test_macro_regime_risk_on_when_benchmark_trends_up(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    # newest-first (sort=desc): 105 now vs 100 at window start → +5% → risk-on.
    payload = {"bars": {"BTC/USD": [{"c": 105}, {"c": 103}, {"c": 100}]}}
    with _fake_client(payload):
        out = await fetch_macro_regime("BTC/USD", redis)
    assert out[FieldName.REGIME] == MacroRegime.RISK_ON
    assert out[FieldName.BENCHMARK] == "BTC/USD"  # crypto benchmark
    assert out[FieldName.RETURN_PCT] == pytest.approx(5.0)
    redis.set.assert_awaited_once()  # result cached


async def test_macro_regime_risk_off_when_benchmark_trends_down(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    payload = {"bars": {"BTC/USD": [{"c": 95}, {"c": 97}, {"c": 100}]}}
    with _fake_client(payload):
        out = await fetch_macro_regime("BTC/USD", redis)
    assert out[FieldName.REGIME] == MacroRegime.RISK_OFF
    assert out[FieldName.RETURN_PCT] == pytest.approx(-5.0)


async def test_macro_regime_neutral_within_band(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    payload = {"bars": {"BTC/USD": [{"c": 100.2}, {"c": 100.1}, {"c": 100.0}]}}
    with _fake_client(payload):
        out = await fetch_macro_regime("BTC/USD", redis)
    assert out[FieldName.REGIME] == MacroRegime.NEUTRAL  # +0.2% is inside the band


async def test_macro_regime_equity_symbol_uses_spy_benchmark(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "k")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    payload = {"bars": {"SPY": [{"c": 110}, {"c": 105}, {"c": 100}]}}
    with _fake_client(payload):
        out = await fetch_macro_regime("AAPL", redis)
    assert out[FieldName.BENCHMARK] == "SPY"  # equities proxy off SPY, not AAPL
    assert out[FieldName.REGIME] == MacroRegime.RISK_ON


async def test_macro_regime_without_api_key_returns_empty(monkeypatch):
    monkeypatch.setattr(market_intel.settings, "ALPACA_API_KEY", "")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    assert await fetch_macro_regime("BTC/USD", redis) == {}


async def test_macro_regime_uses_cache_when_present():
    redis = AsyncMock()
    redis.get = AsyncMock(
        return_value='{"regime": "risk_on", "return_pct": 2.0, "benchmark": "BTC/USD"}'
    )
    out = await fetch_macro_regime("BTC/USD", redis)
    assert out[FieldName.REGIME] == "risk_on"
    redis.set.assert_not_called()  # cache hit — no fetch, no write
