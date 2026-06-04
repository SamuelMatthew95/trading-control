"""Live market-intel perception tools for the reasoning node.

Four tools the :class:`ReasoningAgent` invokes against real Alpaca market data
before deciding — each registered + governed in the Tool Registry:

  - ``fetch_order_book_depth``        — top-of-book bid/ask → spread (bps) +
                                         size imbalance (Alpaca latest quotes).
  - ``fetch_news_sentiment``          — deterministic lexicon sentiment over the
                                         symbol's recent Alpaca news (Redis-cached).
  - ``compute_cross_asset_correlation`` — Pearson correlation of recent 1-min
                                         returns vs same-asset-class peers
                                         (Alpaca bars, Redis-cached).
  - ``fetch_macro_regime``            — risk-on / risk-off / neutral read off a
                                         benchmark's recent daily trend
                                         (BTC for crypto, SPY for equities).

All three are **best-effort**: any failure (no API key, network, empty data)
returns an empty/neutral dict and never raises into the decision path. Alpaca
response keys (``quotes``, ``bp``, ``ap``, ``bs``, ``as``, ``bars``, ``c``,
``news``, ``headline``, ``summary``) are external API-contract strings, not
internal ``FieldName`` payload keys, so they stay as raw literals.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from api.config import settings
from api.constants import (
    ALPACA_DATA_BASE_URL,
    ALPACA_HTTP_CONNECT_TIMEOUT_SECONDS,
    ALPACA_HTTP_READ_TIMEOUT_SECONDS,
    REDIS_CORRELATION_TTL_SECONDS,
    REDIS_KEY_CORRELATION,
    REDIS_KEY_MACRO_REGIME,
    REDIS_KEY_NEWS_SENTIMENT,
    REDIS_MACRO_REGIME_TTL_SECONDS,
    REDIS_NEWS_SENTIMENT_TTL_SECONDS,
    SYMBOL_BTC_USD,
    SYMBOL_SPY,
    VALID_SYMBOLS,
    FieldName,
    MacroRegime,
)
from api.observability import log_structured

# Minimal finance-news sentiment lexicon — deterministic, explainable scoring.
# Net sentiment = (pos - neg) / (pos + neg), so it is bounded in [-1, 1] and a
# headline with no lexicon hits contributes nothing (never random).
_POSITIVE_WORDS = frozenset(
    {
        "surge",
        "surges",
        "surged",
        "gain",
        "gains",
        "gained",
        "rally",
        "rallies",
        "rallied",
        "soar",
        "soars",
        "soared",
        "jump",
        "jumps",
        "jumped",
        "rise",
        "rises",
        "rose",
        "bullish",
        "beat",
        "beats",
        "upgrade",
        "upgraded",
        "record",
        "profit",
        "profits",
        "strong",
        "growth",
        "boost",
        "boosted",
        "outperform",
        "optimistic",
        "breakthrough",
        "approval",
        "partnership",
        "expansion",
        "adoption",
    }
)
_NEGATIVE_WORDS = frozenset(
    {
        "plunge",
        "plunges",
        "plunged",
        "drop",
        "drops",
        "dropped",
        "fall",
        "falls",
        "fell",
        "crash",
        "crashes",
        "crashed",
        "slump",
        "slumps",
        "tumble",
        "tumbles",
        "tumbled",
        "bearish",
        "miss",
        "misses",
        "missed",
        "downgrade",
        "downgraded",
        "loss",
        "losses",
        "weak",
        "decline",
        "declines",
        "declined",
        "lawsuit",
        "investigation",
        "fraud",
        "hack",
        "hacked",
        "ban",
        "banned",
        "selloff",
        "fear",
        "recession",
        "warning",
        "plummet",
        "plummets",
        "default",
    }
)

_NEWS_LIMIT = 10
_CORRELATION_BARS = 30
_CORRELATION_TIMEFRAME = "1Min"
_MIN_RETURNS = 3  # need at least this many return observations for a correlation

# Macro regime is asset-class-wide, so it is read off a benchmark's recent trend
# rather than the traded symbol. Daily bars (not 1-min) are used because they are
# reliably available outside regular trading hours, so the tool returns a real
# regime instead of an empty dict on most calls.
_MACRO_BENCHMARK_CRYPTO = SYMBOL_BTC_USD
_MACRO_BENCHMARK_EQUITY = SYMBOL_SPY
_MACRO_REGIME_BARS = 6
_MACRO_REGIME_TIMEFRAME = "1Day"
_MACRO_RISK_ON_PCT = 1.0  # window return >= +1% → risk-on
_MACRO_RISK_OFF_PCT = -1.0  # window return <= -1% → risk-off


def _is_crypto(symbol: str) -> bool:
    """Crypto symbols carry a base/quote slash (``BTC/USD``); equities do not."""
    return "/" in symbol


def _peers(symbol: str) -> list[str]:
    """Same-asset-class tradable peers — the cross-asset correlation universe."""
    crypto = _is_crypto(symbol)
    return sorted(s for s in VALID_SYMBOLS if _is_crypto(s) == crypto and s != symbol)


def _client() -> httpx.AsyncClient:
    """Short-lived Alpaca data-API client (same auth/host as the price poller)."""
    timeout = httpx.Timeout(
        connect=float(ALPACA_HTTP_CONNECT_TIMEOUT_SECONDS),
        read=float(ALPACA_HTTP_READ_TIMEOUT_SECONDS),
        write=5.0,
        pool=5.0,
    )
    return httpx.AsyncClient(
        base_url=ALPACA_DATA_BASE_URL,
        headers={
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
        },
        timeout=timeout,
    )


async def fetch_order_book_depth(symbol: str) -> dict[str, Any]:
    """Latest bid/ask → spread (bps) + top-of-book size imbalance.

    Returns ``{}`` when there is no API key or the quote is unusable. Imbalance
    is ``(bid_size - ask_size) / (bid_size + ask_size)`` in [-1, 1]: positive =
    more resting bids (buy-side pressure).
    """
    if not settings.ALPACA_API_KEY:
        return {}
    path = "/v1beta3/crypto/us/latest/quotes" if _is_crypto(symbol) else "/v2/stocks/quotes/latest"
    try:
        async with _client() as client:
            resp = await client.get(path, params={"symbols": symbol})
            resp.raise_for_status()
            quote = resp.json().get("quotes", {}).get(symbol, {})
    except Exception:
        log_structured("warning", "order_book_depth_fetch_failed", symbol=symbol, exc_info=True)
        return {}

    bid = float(quote.get("bp", 0) or 0)
    ask = float(quote.get("ap", 0) or 0)
    bid_size = float(quote.get("bs", 0) or 0)
    ask_size = float(quote.get("as", 0) or 0)
    if bid <= 0 or ask <= 0:
        return {}
    mid = (bid + ask) / 2
    spread_bps = round((ask - bid) / mid * 10_000, 2) if mid > 0 else 0.0
    total_size = bid_size + ask_size
    imbalance = round((bid_size - ask_size) / total_size, 4) if total_size > 0 else 0.0
    return {
        FieldName.BID: bid,
        FieldName.ASK: ask,
        FieldName.SPREAD_BPS: spread_bps,
        FieldName.IMBALANCE: imbalance,
    }


def _score_sentiment(texts: list[str]) -> float:
    """Net lexicon sentiment in [-1, 1] over the given headline/summary texts."""
    pos = neg = 0
    for text in texts:
        for raw in text.lower().split():
            word = raw.strip(".,!?;:'\"()[]")
            if word in _POSITIVE_WORDS:
                pos += 1
            elif word in _NEGATIVE_WORDS:
                neg += 1
    total = pos + neg
    return round((pos - neg) / total, 4) if total else 0.0


def _news_symbol(symbol: str) -> str:
    """Alpaca news uses slashless crypto tickers (``BTC/USD`` → ``BTCUSD``)."""
    return symbol.replace("/", "")


async def fetch_news_sentiment(symbol: str, redis) -> dict[str, Any]:
    """Recent-news sentiment score + article count, Redis-cached.

    News moves far slower than ticks, so the result is cached for
    ``REDIS_NEWS_SENTIMENT_TTL_SECONDS`` to bound API calls. Returns ``{}`` when
    there is no API key or the fetch fails.
    """
    cache_key = REDIS_KEY_NEWS_SENTIMENT.format(symbol=symbol)
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        log_structured("warning", "news_sentiment_cache_read_failed", symbol=symbol, exc_info=True)

    if not settings.ALPACA_API_KEY:
        return {}
    try:
        async with _client() as client:
            resp = await client.get(
                "/v1beta1/news",
                params={"symbols": _news_symbol(symbol), FieldName.LIMIT: _NEWS_LIMIT},
            )
            resp.raise_for_status()
            articles = resp.json().get("news", []) or []
    except Exception:
        log_structured("warning", "news_sentiment_fetch_failed", symbol=symbol, exc_info=True)
        return {}

    texts = [f"{a.get('headline', '')} {a.get(FieldName.SUMMARY, '')}" for a in articles]
    result = {
        FieldName.SENTIMENT: _score_sentiment(texts),
        FieldName.ARTICLE_COUNT: len(articles),
    }
    try:
        await redis.set(cache_key, json.dumps(result), ex=REDIS_NEWS_SENTIMENT_TTL_SECONDS)
    except Exception:
        log_structured("warning", "news_sentiment_cache_write_failed", symbol=symbol, exc_info=True)
    return result


def _returns(closes: list[float]) -> list[float]:
    """Simple period-over-period returns from a close-price series."""
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1]
    ]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-window return series, or ``None``."""
    n = min(len(xs), len(ys))
    if n < _MIN_RETURNS:
        return None
    xs, ys = xs[:n], ys[:n]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if std_x == 0 or std_y == 0:
        return None
    return round(cov / (std_x * std_y), 4)


async def _fetch_bars(
    client: httpx.AsyncClient, symbol: str, peers: list[str]
) -> dict[str, list[float]]:
    """Recent close-price series for ``symbol`` + ``peers`` in one Alpaca call."""
    symbols = [symbol, *peers]
    path = "/v1beta3/crypto/us/bars" if _is_crypto(symbol) else "/v2/stocks/bars"
    # Bars are HISTORICAL: without an explicit `start` Alpaca returns the OLDEST
    # bars (ascending) — useless for a current-correlation estimate, which is
    # why the tool returned {} on every decision. Request a recent window
    # (newest-first) so we actually get the latest bars, mirroring the
    # start/end the SignalGenerator's SDK bootstrap already passes.
    start = (datetime.now(timezone.utc) - timedelta(minutes=_CORRELATION_BARS * 4)).isoformat()
    resp = await client.get(
        path,
        params={
            "symbols": ",".join(symbols),
            FieldName.TIMEFRAME: _CORRELATION_TIMEFRAME,
            FieldName.LIMIT: _CORRELATION_BARS,
            "start": start,
            "sort": "desc",
        },
    )
    resp.raise_for_status()
    bars = resp.json().get(FieldName.BARS, {}) or {}
    closes: dict[str, list[float]] = {}
    for sym in symbols:
        series = bars.get(sym) or []
        closes[sym] = [c for c in (float(b.get("c", 0) or 0) for b in series) if c > 0]
    return closes


async def compute_cross_asset_correlation(symbol: str, redis) -> dict[str, Any]:
    """Pearson correlation of recent returns vs same-class peers, Redis-cached.

    Lets the agent avoid stacking correlated risk (e.g. a fresh BTC long while
    already long a highly-correlated ETH). Returns ``{}`` when there are no
    peers, no API key, or insufficient data.
    """
    cache_key = REDIS_KEY_CORRELATION.format(symbol=symbol)
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        log_structured("warning", "correlation_cache_read_failed", symbol=symbol, exc_info=True)

    peers = _peers(symbol)
    if not peers or not settings.ALPACA_API_KEY:
        return {}
    try:
        async with _client() as client:
            closes = await _fetch_bars(client, symbol, peers)
    except Exception:
        log_structured("warning", "correlation_fetch_failed", symbol=symbol, exc_info=True)
        return {}

    base_returns = _returns(closes.get(symbol, []))
    if len(base_returns) < _MIN_RETURNS:
        return {}
    correlations: dict[str, float] = {}
    for peer in peers:
        corr = _pearson(base_returns, _returns(closes.get(peer, [])))
        if corr is not None:
            correlations[peer] = corr
    if not correlations:
        return {}

    most_correlated = max(correlations, key=lambda k: abs(correlations[k]))
    result = {
        FieldName.CORRELATIONS: correlations,
        FieldName.MOST_CORRELATED: most_correlated,
        FieldName.MAX_CORRELATION: correlations[most_correlated],
    }
    try:
        await redis.set(cache_key, json.dumps(result), ex=REDIS_CORRELATION_TTL_SECONDS)
    except Exception:
        log_structured("warning", "correlation_cache_write_failed", symbol=symbol, exc_info=True)
    return result


async def _fetch_recent_closes(
    client: httpx.AsyncClient, symbol: str, *, timeframe: str, limit: int
) -> list[float]:
    """Recent close-price series for one symbol, newest-first (positive closes only).

    An explicit recent ``start`` plus ``sort=desc`` is required so Alpaca returns
    the NEWEST bars — without them it returns the oldest bars (ascending default),
    which is the bug that made bar-based tools return empty on every call.
    """
    path = "/v1beta3/crypto/us/bars" if _is_crypto(symbol) else "/v2/stocks/bars"
    start = (datetime.now(timezone.utc) - timedelta(days=limit * 3)).isoformat()
    resp = await client.get(
        path,
        params={
            "symbols": symbol,
            FieldName.TIMEFRAME: timeframe,
            FieldName.LIMIT: limit,
            "start": start,
            "sort": "desc",
        },
    )
    resp.raise_for_status()
    bars = resp.json().get(FieldName.BARS, {}) or {}
    series = bars.get(symbol) or []
    return [c for c in (float(b.get("c", 0) or 0) for b in series) if c > 0]


async def fetch_macro_regime(symbol: str, redis) -> dict[str, Any]:
    """Market-wide risk posture (risk-on / risk-off / neutral), Redis-cached.

    Macro regime is asset-class-wide, so it is derived from a benchmark's recent
    daily trend — BTC for crypto, SPY for equities — not from ``symbol`` itself.
    The reasoning node feeds the result into the decision prompt so the LLM leans
    risk-on vs risk-off appropriately. Returns ``{}`` only when there is no API
    key or the benchmark bars are unavailable.
    """
    benchmark = _MACRO_BENCHMARK_CRYPTO if _is_crypto(symbol) else _MACRO_BENCHMARK_EQUITY
    cache_key = REDIS_KEY_MACRO_REGIME.format(symbol=benchmark)
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        log_structured("warning", "macro_regime_cache_read_failed", symbol=benchmark, exc_info=True)

    if not settings.ALPACA_API_KEY:
        return {}
    try:
        async with _client() as client:
            closes = await _fetch_recent_closes(
                client, benchmark, timeframe=_MACRO_REGIME_TIMEFRAME, limit=_MACRO_REGIME_BARS
            )
    except Exception:
        log_structured("warning", "macro_regime_fetch_failed", symbol=benchmark, exc_info=True)
        return {}

    # closes are newest-first (sort=desc): window return = newest vs oldest.
    if len(closes) < 2 or closes[-1] <= 0:
        return {}
    newest, oldest = closes[0], closes[-1]
    return_pct = round((newest - oldest) / oldest * 100, 2)
    if return_pct >= _MACRO_RISK_ON_PCT:
        regime = MacroRegime.RISK_ON
    elif return_pct <= _MACRO_RISK_OFF_PCT:
        regime = MacroRegime.RISK_OFF
    else:
        regime = MacroRegime.NEUTRAL
    result = {
        FieldName.REGIME: str(regime),
        FieldName.RETURN_PCT: return_pct,
        FieldName.BENCHMARK: benchmark,
    }
    try:
        await redis.set(cache_key, json.dumps(result), ex=REDIS_MACRO_REGIME_TTL_SECONDS)
    except Exception:
        log_structured(
            "warning", "macro_regime_cache_write_failed", symbol=benchmark, exc_info=True
        )
    return result
