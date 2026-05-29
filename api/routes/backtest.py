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

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.constants import FieldName
from api.observability import log_structured
from backtest.compare import compare_on_prices
from backtest.data import alpaca_prices, synthetic_prices

router = APIRouter(prefix="/backtest", tags=["backtest"])

# Below this many real bars we treat the Alpaca fetch as unavailable (e.g. the
# network allowlist blocks it, or equities are off-hours) and fall back to a
# deterministic synthetic series so the endpoint always returns something.
_MIN_REAL_BARS = 50
_SYNTHETIC_VOL_PCT = 1.5
_SYNTHETIC_SEED = 1

# A backtest over fixed history is deterministic, so we memoize per
# (symbol, bars) for this long rather than recomputing — and, crucially, rather
# than re-hitting the rate-limited Alpaca data API — on every dashboard poll.
_CACHE_TTL_SECONDS = 600
_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


def _summary(source: str) -> str:
    """Honest one-line interpretation that depends on the data source."""
    if source == "alpaca":
        return (
            "Ranked by return on real Alpaca history. The live baseline over-trades; "
            "selective strategies trade less. A positive return here is genuine edge."
        )
    return (
        "Ranked by return on synthetic, zero-edge data (no real-data network access here). "
        "The only lever is trading cost: the baseline over-trades and bleeds to slippage while "
        "selective strategies lose less. Real edge needs real data — runs on the deployed backend."
    )


@router.get("/compare")
async def compare(
    symbol: str = Query(default="BTC/USD", description="symbol to backtest"),
    bars: int = Query(default=750, ge=_MIN_REAL_BARS, le=5000),
) -> dict[str, Any]:
    """Compare the live signal against candidate strategies over price history.

    Returns one row per strategy (return %, trades, Sharpe, win rate), the data
    source actually used (``alpaca`` or ``synthetic``), a plain-language
    interpretation, and a ``cached`` flag. Strategies are pre-sorted
    best-return-first. Identical ``(symbol, bars)`` requests are served from a
    short-lived cache instead of recomputing.
    """
    key = (symbol, bars)
    now = time.time()
    hit = _cache.get(key)
    if hit is not None and (now - hit[0]) < _CACHE_TTL_SECONDS:
        cached_payload = dict(hit[1])
        cached_payload[FieldName.CACHED] = True
        return cached_payload

    try:
        prices = alpaca_prices(symbol, bars=bars)
        source = "alpaca"
        if len(prices) < _MIN_REAL_BARS:
            prices = synthetic_prices(n=bars, vol_pct=_SYNTHETIC_VOL_PCT, seed=_SYNTHETIC_SEED)
            source = "synthetic"

        stats = compare_on_prices(prices)
        strategies = [
            {
                FieldName.NAME: s.name,
                FieldName.RETURN_PCT: s.mean_return_pct,
                FieldName.TRADE_COUNT: s.mean_trades,
                FieldName.SHARPE_RATIO: s.mean_sharpe,
                FieldName.WIN_RATE: s.mean_win_rate,
            }
            for s in sorted(stats, key=lambda x: x.mean_return_pct, reverse=True)
        ]
        payload = {
            FieldName.MODE: "analysis",
            FieldName.SOURCE: source,
            FieldName.SYMBOL: symbol,
            FieldName.BARS: len(prices),
            FieldName.GENERATED_AT: datetime.now(timezone.utc).isoformat(),
            FieldName.SUMMARY: _summary(source),
            FieldName.STRATEGIES: strategies,
            FieldName.CACHED: False,
        }
        _cache[key] = (now, payload)
        return payload
    except Exception:
        log_structured("error", "backtest_compare_failed", symbol=symbol, exc_info=True)
        raise HTTPException(status_code=500, detail="backtest comparison failed") from None
