"""Move-distribution telemetry — evidence for threshold calibration.

The live momentum signal triggers on a fixed single-bar move (``MOMENTUM_PCT`` =
1.5%, ``STRONG_MOMENTUM_PCT`` = 3.0%). Whether that is a sensible trigger depends
entirely on the volatility of the timeframe it runs on: on 1-minute BTC bars a
1.5% move is a ~p99.7 event (almost never), while on hourly bars it is routine.
This module turns that into numbers instead of intuition — for each timeframe it
reports the distribution of ``|per-bar move|`` and where each threshold falls in
it (percentile rank + hit rate), plus a rolling-sigma summary for the eventual
volatility-normalized triggering work.

Pure functions over a close-price series; no I/O. Reused by
``GET /backtest/distribution``. This is research tooling (outside ``api/``), so it
is exempt from the ``FieldName`` ceremony — plain string keys here are fine.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "abs_pct_changes",
    "distribution_report",
    "percentile_of_value",
    "percentiles",
    "rolling_sigma",
    "signed_pct_changes",
]


def signed_pct_changes(prices: Sequence[float]) -> list[float]:
    """Bar-to-bar percent moves, exactly as ``backtest.engine`` computes ``pct``."""
    out: list[float] = []
    for i in range(1, len(prices)):
        prev = float(prices[i - 1])
        if prev:
            out.append((float(prices[i]) - prev) / prev * 100.0)
    return out


def abs_pct_changes(prices: Sequence[float]) -> list[float]:
    """``|bar-to-bar percent move|`` — the quantity ``classify_signal`` thresholds."""
    return [abs(p) for p in signed_pct_changes(prices)]


def _pkey(p: float) -> str:
    """``99 -> 'p99'``, ``99.9 -> 'p99.9'`` (compact, no trailing zeros)."""
    return "p" + f"{p:g}"


def percentiles(values: Sequence[float], ps: Sequence[float]) -> dict[str, float]:
    """Linear-interpolated percentiles keyed ``pNN`` (e.g. ``p99`` / ``p99.9``)."""
    if not values:
        return {_pkey(p): 0.0 for p in ps}
    ordered = sorted(values)
    n = len(ordered)
    result: dict[str, float] = {}
    for p in ps:
        if n == 1:
            result[_pkey(p)] = round(ordered[0], 6)
            continue
        rank = (p / 100.0) * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        result[_pkey(p)] = round(ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo), 6)
    return result


def percentile_of_value(values: Sequence[float], threshold: float) -> float:
    """Percentile rank of ``threshold`` within ``values`` (0–100).

    "1.5% is a p99.7 event" means 99.7% of observed ``|moves|`` are below 1.5%.
    """
    if not values:
        return 0.0
    below = sum(1 for v in values if v < threshold)
    return round(below / len(values) * 100.0, 4)


def rolling_sigma(values: Sequence[float], window: int) -> list[float]:
    """Rolling sample standard deviation of ``values`` over ``window`` samples."""
    if window < 2 or len(values) < window:
        return []
    out: list[float] = []
    for i in range(window, len(values) + 1):
        chunk = values[i - window : i]
        mean = sum(chunk) / window
        var = sum((x - mean) ** 2 for x in chunk) / (window - 1)
        out.append(var**0.5)
    return out


def distribution_report(
    prices: Sequence[float],
    *,
    timeframes: Sequence[int],
    thresholds: Sequence[float],
    sigma_window: int = 30,
) -> list[dict]:
    """One block per timeframe describing the move distribution vs the thresholds.

    A timeframe of ``k`` resamples the base series to every ``k``-th close, so a
    base of 1-minute bars yields 1/5/15/60-minute views. Each block carries:

    * ``timeframe_bars`` / ``sample_size``
    * ``abs_pct``       — p50/p95/p99/p99.9 and max of ``|move|``
    * ``rolling_sigma`` — p50/p95 of the rolling stddev of the signed move
    * ``thresholds``    — per threshold: its ``percentile`` rank and ``hit_rate``
    """
    prices = [float(p) for p in prices]
    report: list[dict] = []
    for tf in timeframes:
        sampled = prices[::tf] if tf > 1 else prices
        moves = abs_pct_changes(sampled)
        sigmas = rolling_sigma(signed_pct_changes(sampled), sigma_window)
        report.append(
            {
                "timeframe_bars": tf,
                "sample_size": len(moves),
                "abs_pct": {
                    **percentiles(moves, (50, 90, 95, 99, 99.9)),
                    "max": round(max(moves), 6) if moves else 0.0,
                },
                "rolling_sigma": (
                    percentiles(sigmas, (50, 95)) if sigmas else {"p50": 0.0, "p95": 0.0}
                ),
                "thresholds": [
                    {
                        "threshold": t,
                        "percentile": percentile_of_value(moves, t),
                        "hit_rate": (
                            round(sum(1 for m in moves if m >= t) / len(moves), 6) if moves else 0.0
                        ),
                    }
                    for t in thresholds
                ],
            }
        )
    return report
