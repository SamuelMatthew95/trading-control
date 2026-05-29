"""Unit tests for the move-distribution telemetry (``backtest/distribution.py``).

Lives under tests/integration so CI runs it alongside the rest of the backtest
harness. Pure functions over a price series — no I/O, fully deterministic.
"""

from __future__ import annotations

from backtest.data import synthetic_prices
from backtest.distribution import (
    abs_pct_changes,
    distribution_report,
    percentile_of_value,
    percentiles,
    rolling_sigma,
)


def test_abs_pct_changes_matches_engine_formula():
    # +10% then -10%: both register as a 10% absolute move.
    assert abs_pct_changes([100.0, 110.0, 99.0]) == [10.0, 10.0]
    assert abs_pct_changes([100.0]) == []


def test_percentiles_monotonic_and_keyed_pnn():
    pcts = percentiles(list(range(101)), (50, 95, 99, 99.9))
    assert set(pcts) == {"p50", "p95", "p99", "p99.9"}
    assert pcts["p50"] == 50.0
    assert pcts["p50"] <= pcts["p95"] <= pcts["p99"] <= pcts["p99.9"]
    # Empty input degrades to zeros, never raises.
    assert percentiles([], (50, 99)) == {"p50": 0.0, "p99": 0.0}


def test_percentile_of_value_reads_as_rarity():
    # 4 of 5 observations are below 1.0 -> the 1.0 threshold sits at p80.
    assert percentile_of_value([0.1, 0.2, 0.3, 0.4, 5.0], 1.0) == 80.0
    assert percentile_of_value([], 1.0) == 0.0


def test_rolling_sigma_window_guard():
    assert rolling_sigma([1.0, 2.0], 5) == []  # window larger than series
    sig = rolling_sigma([0.0, 0.0, 0.0, 0.0], 2)
    assert sig and all(s == 0.0 for s in sig)  # flat series has zero vol


def test_distribution_report_shape():
    prices = synthetic_prices(n=2000, vol_pct=1.0, seed=5)
    report = distribution_report(prices, timeframes=(1, 5, 15), thresholds=(1.5, 3.0))
    assert [b["timeframe_bars"] for b in report] == [1, 5, 15]
    for block in report:
        assert {"timeframe_bars", "sample_size", "abs_pct", "rolling_sigma", "thresholds"} <= set(
            block
        )
        assert {"p50", "p95", "p99", "p99.9", "max"} <= set(block["abs_pct"])
        assert len(block["thresholds"]) == 2
        for t in block["thresholds"]:
            assert {"threshold", "percentile", "hit_rate"} <= set(t)
            assert 0.0 <= t["percentile"] <= 100.0
            assert 0.0 <= t["hit_rate"] <= 1.0


def test_coarser_timeframe_shifts_threshold_to_lower_percentile():
    """The calibration insight: a fixed % threshold is rarer (higher percentile)
    on fine bars than on coarse ones, because coarse bars accumulate bigger moves."""
    prices = synthetic_prices(n=4000, vol_pct=0.5, seed=9)
    by_tf = {
        b["timeframe_bars"]: b
        for b in distribution_report(prices, timeframes=(1, 60), thresholds=(1.5,))
    }
    assert by_tf[60]["abs_pct"]["p99"] > by_tf[1]["abs_pct"]["p99"]
    fine_pct = by_tf[1]["thresholds"][0]["percentile"]
    coarse_pct = by_tf[60]["thresholds"][0]["percentile"]
    assert fine_pct >= coarse_pct
