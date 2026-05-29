"""Price-series sources for the backtest harness.

Two sources:

* :func:`synthetic_prices` — a seeded random walk. Zero drift by default, so
  there is NO edge to find; any P&L the strategy shows is pure signal behavior
  plus cost drag. Fully deterministic — used in CI.
* :func:`alpaca_prices` — real historical 1-minute bars from Alpaca. Faithful,
  but requires ``ALPACA_API_KEY`` / ``ALPACA_SECRET_KEY`` and network access.
"""

from __future__ import annotations

import random

__all__ = ["alpaca_prices", "synthetic_prices"]


def synthetic_prices(
    *,
    n: int = 1000,
    start: float = 50_000.0,
    vol_pct: float = 0.8,
    drift_pct: float = 0.0,
    seed: int = 0,
) -> list[float]:
    """Generate ``n`` bar-close prices as a seeded multiplicative random walk.

    ``vol_pct`` is the per-bar standard deviation in percent; ``drift_pct`` the
    per-bar mean in percent. ``drift_pct=0`` (the default) yields a fair random
    walk with no exploitable edge, so any strategy P&L reflects the signal's
    own behavior and trading costs — not luck. Deterministic for a given seed.
    """
    rng = random.Random(seed)
    prices = [float(start)]
    mu = drift_pct / 100.0
    sigma = vol_pct / 100.0
    for _ in range(max(0, n - 1)):
        shock = rng.gauss(mu, sigma)
        prices.append(max(0.01, prices[-1] * (1.0 + shock)))
    return prices


def alpaca_prices(symbol: str, *, bars: int = 1000) -> list[float]:
    """Fetch the most recent ``bars`` 1-minute closes for ``symbol`` from Alpaca.

    Returns an empty list if credentials are missing or the fetch fails — the
    caller is expected to fall back to synthetic data and say so. Mirrors the
    historical-bar fetch already used by ``SignalGenerator._bootstrap_price_history``.
    """
    from api.config import settings  # noqa: PLC0415

    if not (settings.ALPACA_API_KEY and settings.ALPACA_SECRET_KEY):
        return []
    try:
        from datetime import datetime, timedelta, timezone  # noqa: PLC0415

        from alpaca.data.historical.crypto import CryptoHistoricalDataClient  # noqa: PLC0415
        from alpaca.data.historical.stock import StockHistoricalDataClient  # noqa: PLC0415
        from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest  # noqa: PLC0415
        from alpaca.data.timeframe import TimeFrame  # noqa: PLC0415

        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=bars * 2 + 120)
        if "/" in symbol:
            client = CryptoHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)
            req = CryptoBarsRequest(
                symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start, end=end
            )
            data = client.get_crypto_bars(req)
        else:
            client = StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)
            req = StockBarsRequest(
                symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start, end=end
            )
            data = client.get_stock_bars(req)
        rows = data[symbol] if hasattr(data, "__getitem__") else []
        return [float(b.close) for b in rows][-bars:]
    except Exception:
        return []
