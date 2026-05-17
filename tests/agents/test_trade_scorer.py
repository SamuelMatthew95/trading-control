"""Tests for compute_learning_metrics in trade_scorer.py."""

import pytest

from api.constants import FieldName
from api.services.agents.trade_scorer import compute_learning_metrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evals(n: int, pnl_pct: float = 1.0, pnl: float = 10.0, score: float = 0.7) -> list[dict]:
    """Return n identical evaluation dicts with the given values."""
    return [
        {
            FieldName.PNL_PERCENT: pnl_pct,
            FieldName.PNL: pnl,
            FieldName.OVERALL_SCORE: score,
        }
        for _ in range(n)
    ]


def _alternating_evals(n: int) -> list[dict]:
    """Return n evals alternating between a win (+2%) and a loss (-1%)."""
    result = []
    for i in range(n):
        if i % 2 == 0:
            result.append(
                {FieldName.PNL_PERCENT: 2.0, FieldName.PNL: 20.0, FieldName.OVERALL_SCORE: 0.8}
            )
        else:
            result.append(
                {FieldName.PNL_PERCENT: -1.0, FieldName.PNL: -10.0, FieldName.OVERALL_SCORE: 0.4}
            )
    return result


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_evaluations_returns_zeros():
    result = compute_learning_metrics([])
    assert result[FieldName.TOTAL_TRADES] == 0
    assert result[FieldName.WIN_RATE] == 0.0
    assert result["sample_size"] == 0
    assert result["metric_status"] == "insufficient_data"
    assert result["min_required_sample_size"] == 10


# ---------------------------------------------------------------------------
# sample_size mirrors input length
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 5, 10, 30, 50])
def test_sample_size_equals_input_length(n):
    result = compute_learning_metrics(_make_evals(n))
    assert result["sample_size"] == n
    assert result[FieldName.TOTAL_TRADES] == n


# ---------------------------------------------------------------------------
# metric_status thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 5, 9])
def test_metric_status_insufficient_below_10(n):
    result = compute_learning_metrics(_make_evals(n))
    assert result["metric_status"] == "insufficient_data"


@pytest.mark.parametrize("n", [10, 15, 29])
def test_metric_status_unstable_between_10_and_29(n):
    result = compute_learning_metrics(_make_evals(n))
    assert result["metric_status"] == "unstable"


@pytest.mark.parametrize("n", [30, 50, 100])
def test_metric_status_reliable_at_30_or_more(n):
    result = compute_learning_metrics(_make_evals(n))
    assert result["metric_status"] == "reliable"


# ---------------------------------------------------------------------------
# max_drawdown uses pct returns, not dollar PnL
# ---------------------------------------------------------------------------


def test_max_drawdown_uses_pct_returns_not_dollar_pnl():
    """
    Evals with a large dollar PnL but tiny pct return should produce a small
    drawdown. If the implementation mistakenly used dollar PnL values, the
    drawdown would be orders of magnitude larger.
    """
    # pnl=100 (dollars) but pnl_pct=0.01 (1 basis point)
    evals = [
        {FieldName.PNL_PERCENT: 1.0, FieldName.PNL: 100.0, FieldName.OVERALL_SCORE: 0.6},
        {FieldName.PNL_PERCENT: -0.5, FieldName.PNL: -50.0, FieldName.OVERALL_SCORE: 0.4},
        {FieldName.PNL_PERCENT: 0.8, FieldName.PNL: 80.0, FieldName.OVERALL_SCORE: 0.5},
    ]
    result = compute_learning_metrics(evals)
    drawdown = result[FieldName.MAX_DRAWDOWN]
    # drawdown should be on the order of pct (≤ a few %) — not dollars (≤ 100+)
    assert abs(drawdown) < 10, f"drawdown too large: {drawdown} — likely using dollar PnL"


def test_max_drawdown_monotone_increase_is_zero():
    """No drawdown when every trade is a winner (cumulative curve only rises)."""
    evals = _make_evals(15, pnl_pct=1.0, pnl=10.0)
    result = compute_learning_metrics(evals)
    # max_drawdown is returned as a negative number; magnitude should be ~0
    assert result[FieldName.MAX_DRAWDOWN] == 0.0


def test_max_drawdown_all_losses():
    """Drawdown should be negative (we return -max_dd) when every trade loses."""
    evals = _make_evals(15, pnl_pct=-1.0, pnl=-10.0)
    result = compute_learning_metrics(evals)
    # All losses → peak=0, cumulative keeps falling → drawdown = 15
    assert result[FieldName.MAX_DRAWDOWN] == pytest.approx(-15.0, abs=0.01)


def test_max_drawdown_in_percentage_point_units():
    """
    Backend returns max_drawdown in percentage-point units matching avg_return.
    If pnl_pct values are in the range [-5, +5], the drawdown magnitude should
    be similarly bounded, not in dollar units (which would be 100× larger).
    """
    evals = _alternating_evals(20)
    result = compute_learning_metrics(evals)
    # avg_return and max_drawdown should be in the same order of magnitude
    avg_r = result[FieldName.AVG_RETURN]
    max_dd = result[FieldName.MAX_DRAWDOWN]
    # both should be single-digit percentages, not hundreds
    assert abs(avg_r) < 5, f"avg_return unexpectedly large: {avg_r}"
    assert abs(max_dd) < 5, f"max_drawdown unexpectedly large: {max_dd}"


# ---------------------------------------------------------------------------
# win_rate and avg_return correctness
# ---------------------------------------------------------------------------


def test_win_rate_all_winners():
    evals = _make_evals(10, pnl_pct=1.0, pnl=10.0)
    result = compute_learning_metrics(evals)
    assert result[FieldName.WIN_RATE] == pytest.approx(1.0)


def test_win_rate_half_winners():
    evals = _alternating_evals(10)
    result = compute_learning_metrics(evals)
    assert result[FieldName.WIN_RATE] == pytest.approx(0.5)


def test_avg_return_is_mean_of_pnl_pct():
    evals = [
        {FieldName.PNL_PERCENT: 2.0, FieldName.PNL: 20.0, FieldName.OVERALL_SCORE: 0.7},
        {FieldName.PNL_PERCENT: 4.0, FieldName.PNL: 40.0, FieldName.OVERALL_SCORE: 0.8},
    ]
    result = compute_learning_metrics(evals)
    assert result[FieldName.AVG_RETURN] == pytest.approx(3.0, abs=0.001)
