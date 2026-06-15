"""Backtest API — serves offline strategy-comparison results to the dashboard.

On-demand and **cached** (not a stored one-off, not a constant re-run): each
distinct ``(symbol, bars)`` request replays the production signal logic over
price history, scores it with the production trade_scorer, then memoizes the
result for a few minutes. On the deployed backend (Render) it fetches real
Alpaca history; locally / in CI it falls back to a deterministic synthetic
series and says so via ``source``.

This is intentionally NOT an isolated tool — it imports the SAME
``classify_signal`` the SignalGenerator agent uses and the SAME trade_scorer the
GradeAgent uses (see the ``backtest`` package), so what it measures is exactly
what the live agents do.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.constants import (
    BACKTEST_REFRESH_INTERVAL_SECONDS,
    REDIS_KEY_KILL_SWITCH,
    FieldName,
    StrategyStatus,
)
from api.observability import log_structured
from api.redis_client import get_redis
from api.services.signal_generator import MOMENTUM_PCT, STRONG_MOMENTUM_PCT
from api.services.strategy_registry import StrategyRegistry, get_strategy_registry
from api.utils import now_iso
from backtest.challenger import INSUFFICIENT_DATA, evaluate_from_stats
from backtest.compare import compare_on_prices
from backtest.data import alpaca_prices, synthetic_prices
from backtest.distribution import distribution_report
from backtest.strategies import STRATEGIES

router = APIRouter(prefix="/backtest", tags=["backtest"])

# Below this many real bars we treat the Alpaca fetch as unavailable (e.g. the
# network allowlist blocks it, or equities are off-hours) and fall back to a
# deterministic synthetic series so the endpoint always returns something.
_MIN_REAL_BARS = 50
_SYNTHETIC_VOL_PCT = 1.5
_SYNTHETIC_SEED = 1
_DEFAULT_SYMBOL = "BTC/USD"
_DEFAULT_BARS = 750

# A backtest over fixed history is deterministic, so we memoize per
# (symbol, bars) for this long rather than recomputing — and, crucially, rather
# than re-hitting the rate-limited Alpaca data API — on every dashboard poll.
_CACHE_TTL_SECONDS = 600
_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}

# Base-bar multiples to resample to for the move-distribution telemetry: a base
# of 1-minute bars yields 1/5/15/60-minute views of the same series.
_DISTRIBUTION_TIMEFRAMES = (1, 5, 15, 60)
_dist_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


def _summary(source: str, *, active: int, total: int, decision: str) -> str:
    """Interpretation derived from the numbers — never a hardcoded claim about how
    often a strategy trades. Those narratives drift from reality (a footer once read
    "the baseline over-trades" while the table showed 0 trades); see
    docs/troubleshooting/backtest.md."""
    src = "real Alpaca history" if source == "alpaca" else "synthetic, zero-edge data"
    bits = [f"Ranked by return on {src}."]
    inactive = total - active
    if inactive:
        bits.append(
            f"{inactive}/{total} strategies never crossed the signal threshold on this "
            "data (NO SIGNALS) and are not ranked."
        )
    if decision == INSUFFICIENT_DATA:
        bits.append("Too few trades to judge a challenger — verdict is INSUFFICIENT DATA.")
    elif source == "synthetic":
        bits.append("On synthetic zero-edge data the only lever is trading cost.")
    return " ".join(bits)


def _load_prices(symbol: str, bars: int) -> tuple[list[float], str]:
    """Real Alpaca history when reachable, deterministic synthetic otherwise.

    Shared by /compare and /distribution so both measure the identical series.
    Returns ``(prices, source)`` where source is ``"alpaca"`` or ``"synthetic"``.
    """
    prices = alpaca_prices(symbol, bars=bars)
    if len(prices) < _MIN_REAL_BARS:
        return synthetic_prices(
            n=bars, vol_pct=_SYNTHETIC_VOL_PCT, seed=_SYNTHETIC_SEED
        ), "synthetic"
    return list(prices), "alpaca"


def _compute_compare(symbol: str, bars: int) -> dict[str, Any]:
    """Run the strategy comparison + challenger verdict over price history.

    Real Alpaca data when available (deployed backend), deterministic synthetic
    otherwise. Pure compute — caching and HTTP concerns live in the callers.
    """
    prices, source = _load_prices(symbol, bars)
    stats = compare_on_prices(prices)
    verdict = evaluate_from_stats(stats)
    decision = verdict.decision if verdict else "reject"
    active = sum(1 for s in stats if s.mean_signals > 0)
    # Active (signal-producing) strategies first, ranked by return; inert
    # "NO SIGNALS" strategies sort last so a 0-trade 0.00% never outranks a
    # strategy that actually traded.
    ordered = sorted(stats, key=lambda x: (x.mean_signals > 0, x.mean_return_pct), reverse=True)
    strategies = [
        {
            FieldName.NAME: s.name,
            FieldName.RETURN_PCT: s.mean_return_pct,
            FieldName.TRADE_COUNT: s.mean_trades,
            FieldName.SIGNALS: s.mean_signals,
            FieldName.SHARPE_RATIO: s.mean_sharpe,
            FieldName.WIN_RATE: s.mean_win_rate,
        }
        for s in ordered
    ]
    return {
        FieldName.MODE: "analysis",
        FieldName.SOURCE: source,
        FieldName.SYMBOL: symbol,
        FieldName.BARS: len(prices),
        FieldName.GENERATED_AT: now_iso(),
        FieldName.SUMMARY: _summary(source, active=active, total=len(stats), decision=decision),
        FieldName.STRATEGIES: strategies,
        FieldName.CANDIDATE: verdict.candidate if verdict else None,
        FieldName.BASELINE: verdict.baseline if verdict else None,
        FieldName.IS_DIFFERENT: verdict.is_different if verdict else False,
        FieldName.BEATS_BASELINE: verdict.beats_baseline if verdict else False,
        FieldName.DECISION: decision,
        FieldName.REASON: verdict.reason if verdict else "no candidate available",
        FieldName.CACHED: False,
    }


@router.get("/compare")
async def compare(
    symbol: str = Query(default="BTC/USD", description="symbol to backtest"),
    bars: int = Query(default=750, ge=_MIN_REAL_BARS, le=5000),
    force: bool = Query(default=False, description="bypass the cache and recompute now"),
) -> dict[str, Any]:
    """Compare the live signal against candidate strategies over price history.

    Cached per ``(symbol, bars)`` for ``_CACHE_TTL_SECONDS``; pass ``force=true``
    (the dashboard's Refresh button) to bypass the cache and recompute now.
    """
    key = (symbol, bars)
    now = time.time()
    hit = _cache.get(key)
    if not force and hit is not None and (now - hit[0]) < _CACHE_TTL_SECONDS:
        cached_payload = dict(hit[1])
        cached_payload[FieldName.CACHED] = True
        return cached_payload
    try:
        payload = _compute_compare(symbol, bars)
    except Exception:
        log_structured("error", "backtest_compare_failed", symbol=symbol, exc_info=True)
        raise HTTPException(status_code=500, detail="backtest comparison failed") from None
    _cache[key] = (now, payload)
    return payload


async def refresh_compare_cache(symbol: str = _DEFAULT_SYMBOL, bars: int = _DEFAULT_BARS) -> None:
    """Recompute and cache the comparison — used by the hourly background refresh."""
    try:
        payload = _compute_compare(symbol, bars)
        _cache[(symbol, bars)] = (time.time(), payload)
        log_structured(
            "info", "backtest_cache_refreshed", symbol=symbol, source=payload[FieldName.SOURCE]
        )
    except Exception:
        log_structured("warning", "backtest_cache_refresh_failed", symbol=symbol, exc_info=True)


async def run_backtest_refresh_loop() -> None:
    """Background loop: warm the backtest cache on start, then refresh every hour
    so the dashboard shows fresh real-data results without anyone clicking."""
    while True:
        await refresh_compare_cache()
        await asyncio.sleep(BACKTEST_REFRESH_INTERVAL_SECONDS)


def _compute_distribution(symbol: str, bars: int) -> dict[str, Any]:
    """Per-timeframe distribution of actual moves vs the live signal thresholds."""
    prices, source = _load_prices(symbol, bars)
    report = distribution_report(
        prices,
        timeframes=_DISTRIBUTION_TIMEFRAMES,
        thresholds=(MOMENTUM_PCT, STRONG_MOMENTUM_PCT),
    )
    return {
        FieldName.MODE: "distribution",
        FieldName.SOURCE: source,
        FieldName.SYMBOL: symbol,
        FieldName.BARS: len(prices),
        FieldName.GENERATED_AT: now_iso(),
        FieldName.TIMEFRAMES: report,
        FieldName.CACHED: False,
    }


@router.get("/distribution")
async def distribution(
    symbol: str = Query(default="BTC/USD", description="symbol to analyze"),
    bars: int = Query(default=750, ge=_MIN_REAL_BARS, le=5000),
    force: bool = Query(default=False, description="bypass the cache and recompute now"),
) -> dict[str, Any]:
    """Where the live MOMENTUM_PCT / STRONG_MOMENTUM_PCT triggers fall in the
    distribution of actual per-bar moves, per timeframe — calibration as evidence
    rather than a magic number, e.g. "1.5% is a p99.7 event on 1-minute bars".
    Cached per ``(symbol, bars)`` like /compare; ``force=true`` recomputes now.
    """
    key = (symbol, bars)
    now = time.time()
    hit = _dist_cache.get(key)
    if not force and hit is not None and (now - hit[0]) < _CACHE_TTL_SECONDS:
        cached_payload = dict(hit[1])
        cached_payload[FieldName.CACHED] = True
        return cached_payload
    try:
        payload = _compute_distribution(symbol, bars)
    except Exception:
        log_structured("error", "backtest_distribution_failed", symbol=symbol, exc_info=True)
        raise HTTPException(status_code=500, detail="distribution computation failed") from None
    _dist_cache[key] = (now, payload)
    return payload


_BASELINE_NAME = "baseline_momentum"
_TO_LIVE_STAGES = (
    StrategyStatus.BACKTESTED,
    StrategyStatus.SHADOW,
    StrategyStatus.CANARY,
    StrategyStatus.LIVE,
)


def _ensure_registry_seeded() -> StrategyRegistry:
    """Idempotently seed the lifecycle: baseline LIVE, candidates SHADOW.

    Candidates sit at SHADOW (not BACKTESTED) because a shadow ChallengerAgent is
    auto-spawned for each at startup — they run on the live streams, are graded,
    and place no orders. Idempotent via ``find_by_strategy`` so it agrees with the
    challengers' own registration no matter which runs first.
    """
    registry = get_strategy_registry()
    if registry.find_by_strategy(_BASELINE_NAME) is None:
        base = registry.register({FieldName.STRATEGY: _BASELINE_NAME})
        for stage in _TO_LIVE_STAGES:
            registry.transition(base.version_id, stage)
    for name in STRATEGIES:
        if name == _BASELINE_NAME or registry.find_by_strategy(name) is not None:
            continue
        candidate = registry.register({FieldName.STRATEGY: name})
        registry.transition(candidate.version_id, StrategyStatus.BACKTESTED)
        registry.transition(candidate.version_id, StrategyStatus.SHADOW)
    return registry


async def _breaker_tripped() -> bool:
    """Best-effort read of the kill switch — the circuit breaker's live state."""
    try:
        redis = await get_redis()
        value = await redis.get(REDIS_KEY_KILL_SWITCH)
        return value in ("1", b"1")
    except Exception:
        return False


@router.get("/strategies")
async def strategies() -> dict[str, Any]:
    """List every strategy version and its lifecycle stage, for the dashboard.

    Each version advances proposed -> backtested -> shadow -> canary -> live ->
    retired (one stage at a time, enforced by the registry). The circuit-breaker
    (kill-switch) state is included so the UI can show when trading is halted.
    """
    registry = _ensure_registry_seeded()
    rows = [
        {
            FieldName.ID: sv.version_id,
            FieldName.NAME: sv.config.get(FieldName.STRATEGY, ""),
            FieldName.VERSION: sv.version,
            FieldName.STATUS: (rec.status.value if (rec := registry.get(sv.version_id)) else ""),
        }
        for sv in registry.versions()
    ]
    rows.sort(key=lambda r: r[FieldName.VERSION])
    return {
        FieldName.MODE: "registry",
        FieldName.STRATEGIES: rows,
        FieldName.CIRCUIT_BREAKER_ACTIVE: await _breaker_tripped(),
    }
