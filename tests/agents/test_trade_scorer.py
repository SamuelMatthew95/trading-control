"""Tests for compute_learning_metrics in trade_scorer.py."""

import pytest

from api.constants import FieldName
from api.services.agents.trade_scorer import (
    aggregate_model_performance,
    compute_learning_metrics,
    compute_recommendations,
    score_trade,
)


def test_aggregate_model_performance_groups_and_skips_blank():
    rows = aggregate_model_performance(
        [
            {
                FieldName.MODEL_USED: "gemini:flash",
                FieldName.PNL: 10.0,
                FieldName.OVERALL_SCORE: 0.8,
                FieldName.DECISION_COST_USD: 0.01,
            },
            {
                FieldName.MODEL_USED: "gemini:flash",
                FieldName.PNL: -4.0,
                FieldName.OVERALL_SCORE: 0.4,
                FieldName.DECISION_COST_USD: 0.03,
            },
            {
                FieldName.MODEL_USED: "lmstudio:llama",
                FieldName.PNL: 6.0,
                FieldName.OVERALL_SCORE: 0.7,
                FieldName.DECISION_COST_USD: 0.0,
            },
            {FieldName.MODEL_USED: "", FieldName.PNL: 99.0},  # blank model is skipped
        ]
    )
    by_model = {r[FieldName.MODEL_USED]: r for r in rows}
    assert set(by_model) == {"gemini:flash", "lmstudio:llama"}
    assert by_model["gemini:flash"][FieldName.TRADE_COUNT] == 2
    assert by_model["gemini:flash"][FieldName.WIN_RATE] == 0.5
    assert by_model["gemini:flash"][FieldName.AVG_SCORE] == 0.6
    assert by_model["gemini:flash"][FieldName.TOTAL_PNL] == 6.0
    assert by_model["gemini:flash"][FieldName.AVG_PNL] == 3.0
    # cost + net ROI (P&L minus the LLM cost of those trades' decisions)
    assert by_model["gemini:flash"][FieldName.TOTAL_COST] == 0.04
    assert by_model["gemini:flash"][FieldName.NET_ROI] == 5.96
    assert by_model["lmstudio:llama"][FieldName.NET_ROI] == 6.0  # local model is free
    # sorted by trade count descending
    assert rows[0][FieldName.MODEL_USED] == "gemini:flash"


def test_aggregate_model_performance_empty():
    assert aggregate_model_performance([]) == []


def test_score_trade_carries_decision_provenance():
    """A scored trade records the model + thesis that produced it, so the
    learning loop can grade decisions with model awareness."""
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-1",
            FieldName.SYMBOL: "BTC/USD",
            FieldName.SIDE: "buy",
            FieldName.PNL: 12.0,
            FieldName.PNL_PERCENT: 1.2,
            FieldName.CONFIDENCE: 0.8,
            FieldName.MODEL_USED: "gemini:gemini-1.5-flash",
            FieldName.PRIMARY_EDGE: "vwap_reclaim_momentum",
            FieldName.DECISION_COST_USD: 0.002,
        }
    )
    assert evaluation[FieldName.MODEL_USED] == "gemini:gemini-1.5-flash"
    assert evaluation[FieldName.PRIMARY_EDGE] == "vwap_reclaim_momentum"
    assert evaluation[FieldName.DECISION_COST_USD] == 0.002


def test_score_trade_provenance_defaults_empty_when_absent():
    evaluation = score_trade({FieldName.TRADE_ID: "t-2", FieldName.PNL_PERCENT: 0.5})
    assert evaluation[FieldName.MODEL_USED] == ""
    assert evaluation[FieldName.PRIMARY_EDGE] == ""
    assert evaluation[FieldName.DECISION_COST_USD] == 0.0


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


# trade_scorer uses the production "closing-order side" convention: a closed
# LONG is reported with side="sell" (the close order), favorable when price
# rose; a closed SHORT with side="buy", favorable when price fell. The
# execution engine emits side this way (see execution_engine.is_round_trip_close
# — a close order is opposite the open position), so these fixtures mirror real
# trade-completed events rather than an intuitive but wrong "buy == long" read.
def test_score_trade_adds_price_action_context_labels_for_losses():
    # Long closed at a loss after ~1 min: price fell below entry (adverse move).
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-loss",
            FieldName.SIDE: "sell",
            FieldName.PNL: -50.0,
            FieldName.PNL_PERCENT: -1.2,
            FieldName.CONFIDENCE: 0.35,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 99.0,
            FieldName.HOLDING_PERIOD_MINUTES: 1.0,
        }
    )
    assert "early_exit" in evaluation[FieldName.MISTAKES]
    assert "adverse_price_move" in evaluation[FieldName.MISTAKES]


def test_score_trade_adds_price_action_context_labels_for_wins():
    # Long held 15 min and closed for profit, capturing a +1% up move.
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-win",
            FieldName.SIDE: "sell",
            FieldName.PNL: 80.0,
            FieldName.PNL_PERCENT: 1.5,
            FieldName.CONFIDENCE: 0.85,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 101.0,
            FieldName.HOLDING_PERIOD_MINUTES: 15.0,
        }
    )
    assert "patience_paid" in evaluation[FieldName.STRENGTHS]
    assert "captured_directional_move" in evaluation[FieldName.STRENGTHS]


def test_score_trade_marks_execution_drag_on_losing_trade():
    # Long closed at a loss; realized P&L is worse than the price move implies.
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-drag",
            FieldName.SIDE: "sell",
            FieldName.PNL: -20.0,
            FieldName.PNL_PERCENT: -1.0,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 99.8,
            FieldName.HOLDING_PERIOD_MINUTES: 6.0,
            FieldName.CONFIDENCE: 0.45,
        }
    )
    assert "execution_drag" in evaluation[FieldName.MISTAKES]


def test_score_trade_marks_clean_execution_on_profitable_trade():
    # Long closed for a small clean profit; realized P&L tracks the price move.
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-clean",
            FieldName.SIDE: "sell",
            FieldName.PNL: 30.0,
            FieldName.PNL_PERCENT: 0.5,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 100.55,
            FieldName.HOLDING_PERIOD_MINUTES: 12.0,
            FieldName.CONFIDENCE: 0.9,
        }
    )
    assert "clean_execution" in evaluation[FieldName.STRENGTHS]


def test_compute_recommendations_includes_new_context_mistake_guidance():
    recs = compute_recommendations(
        [
            {FieldName.TYPE: "execution_drag", FieldName.FREQUENCY: 0.4},
            {FieldName.TYPE: "early_exit", FieldName.FREQUENCY: 0.3},
        ],
        [],
    )
    assert any("execution drag" in r for r in recs)
    assert any("minimum hold time" in r for r in recs)


def test_score_trade_no_price_context_does_not_emit_price_action_tags():
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-no-price",
            FieldName.SIDE: "buy",
            FieldName.PNL: -10.0,
            FieldName.PNL_PERCENT: -0.2,
            FieldName.CONFIDENCE: 0.6,
            # no entry/exit price provided
        }
    )
    assert "adverse_price_move" not in evaluation[FieldName.MISTAKES]
    assert "captured_directional_move" not in evaluation[FieldName.STRENGTHS]


def test_score_trade_short_side_directional_move_is_normalized():
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-short-move",
            FieldName.SIDE: "buy",  # buy-to-cover => closing a short
            FieldName.PNL: 25.0,
            FieldName.PNL_PERCENT: 0.8,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 99.0,  # favorable for short
            FieldName.HOLDING_PERIOD_MINUTES: 8.0,
            FieldName.CONFIDENCE: 0.7,
        }
    )
    assert "captured_directional_move" in evaluation[FieldName.STRENGTHS]
    assert "adverse_price_move" not in evaluation[FieldName.MISTAKES]


def test_score_trade_long_close_side_sell_keeps_favorable_move_positive():
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-long-close",
            FieldName.SIDE: "sell",  # sell-to-close => closing a long
            FieldName.PNL: 35.0,
            FieldName.PNL_PERCENT: 0.7,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 101.0,
            FieldName.HOLDING_PERIOD_MINUTES: 9.0,
            FieldName.CONFIDENCE: 0.75,
        }
    )
    assert "captured_directional_move" in evaluation[FieldName.STRENGTHS]
    assert "adverse_price_move" not in evaluation[FieldName.MISTAKES]


def test_compute_recommendations_respects_frequency_threshold():
    recs = compute_recommendations(
        [{FieldName.TYPE: "execution_drag", FieldName.FREQUENCY: 0.10}],
        [],
    )
    assert recs == []


def test_score_trade_adds_system_context_tags_when_inputs_present():
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-sys-tags",
            FieldName.SIDE: "buy",
            FieldName.PNL: -30.0,
            FieldName.PNL_PERCENT: -0.8,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 99.0,
            FieldName.LATENCY_MS: 2500,
            FieldName.SLIPPAGE_VARIANCE: 0.01,
            FieldName.SPREAD_PCT: 0.4,
            FieldName.REGIME: "trend",
            FieldName.CURRENT_REGIME: "mean_reversion",
            FieldName.RATE_LIMIT: True,
            FieldName.DATA_INTEGRITY_ISSUE: True,
        }
    )
    for tag in (
        "signal_latency",
        "fill_quality_poor",
        "low_liquidity_skew",
        "regime_shift",
        "api_throttle_penalty",
        "data_integrity_issue",
    ):
        assert tag in evaluation[FieldName.MISTAKES]


def test_score_trade_limits_mistake_tag_count_and_orders_by_priority():
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-many-tags",
            FieldName.SIDE: "sell",
            FieldName.ACTION: "buy",
            FieldName.PNL: -45.0,
            FieldName.PNL_PERCENT: -2.0,
            FieldName.CONFIDENCE: 0.2,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 101.5,
            FieldName.HOLDING_PERIOD_MINUTES: 1.0,
            FieldName.LATENCY_MS: 3000,
            FieldName.SLIPPAGE_VARIANCE: 0.02,
            FieldName.SPREAD_PCT: 0.5,
            FieldName.REGIME: "trend",
            FieldName.CURRENT_REGIME: "mean_reversion",
            FieldName.RATE_LIMIT: True,
            FieldName.DATA_INTEGRITY_ISSUE: True,
        }
    )
    mistakes = evaluation[FieldName.MISTAKES]
    assert len(mistakes) <= 6
    assert mistakes[0] == "data_integrity_issue"


def test_score_trade_reversion_luck_excludes_clean_execution():
    evaluation = score_trade(
        {
            FieldName.TRADE_ID: "t-reversion",
            FieldName.SIDE: "buy",
            FieldName.PNL: 5.0,
            FieldName.PNL_PERCENT: 0.2,
            FieldName.ENTRY_PRICE: 100.0,
            FieldName.EXIT_PRICE: 101.5,  # move=1.5, drift to pnl_pct creates reversion_luck
            FieldName.HOLDING_PERIOD_MINUTES: 15.0,
            FieldName.CONFIDENCE: 0.8,
        }
    )
    strengths = evaluation[FieldName.STRENGTHS]
    assert "reversion_luck" in strengths
    assert "clean_execution" not in strengths
