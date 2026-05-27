"""Unit tests for api/services/risk_filters.py.

All tests are synchronous — risk_filters.py has no async code.
"""

from __future__ import annotations

from api.services.risk_filters import (
    compute_atr_from_prices,
    compute_dynamic_position_size,
    compute_kelly_size,
    compute_net_ev,
    compute_rsi,
    cooling_off_score,
    is_cooling_off,
    is_regime_tradeable,
)

# ---------------------------------------------------------------------------
# compute_rsi
# ---------------------------------------------------------------------------


def test_rsi_insufficient_data() -> None:
    assert compute_rsi([100.0] * 5, period=14) is None


def test_rsi_all_gains_returns_100() -> None:
    prices = [float(i) for i in range(1, 20)]  # strictly increasing
    rsi = compute_rsi(prices, period=14)
    assert rsi == 100.0


def test_rsi_all_losses_returns_0() -> None:
    prices = [float(20 - i) for i in range(20)]  # strictly decreasing
    rsi = compute_rsi(prices, period=14)
    assert rsi is not None
    assert rsi == 0.0


def test_rsi_mixed_returns_mid_range() -> None:
    # alternating up/down should give RSI ~50
    prices = [
        100.0,
        102.0,
        100.0,
        102.0,
        100.0,
        102.0,
        100.0,
        102.0,
        100.0,
        102.0,
        100.0,
        102.0,
        100.0,
        102.0,
        100.0,
        102.0,
    ]
    rsi = compute_rsi(prices, period=14)
    assert rsi is not None
    assert 45.0 < rsi < 55.0


# ---------------------------------------------------------------------------
# compute_atr_from_prices
# ---------------------------------------------------------------------------


def test_atr_insufficient_data() -> None:
    assert compute_atr_from_prices([100.0] * 5, period=14) is None


def test_atr_constant_prices_returns_zero() -> None:
    prices = [100.0] * 20
    atr = compute_atr_from_prices(prices, period=14)
    assert atr == 0.0


def test_atr_uniform_moves() -> None:
    # Each tick moves exactly $1, ATR should be ~1.0
    prices = [100.0 + i for i in range(20)]
    atr = compute_atr_from_prices(prices, period=14)
    assert atr is not None
    assert abs(atr - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# is_regime_tradeable
# ---------------------------------------------------------------------------


def test_regime_insufficient_history_allows_trade() -> None:
    assert is_regime_tradeable([1.0, 2.0, 3.0], avg_period=20) is True


def test_regime_current_atr_above_avg_allows_trade() -> None:
    # 19 values of 1.0, then current = 2.0 — regime is expanding
    history = [1.0] * 19 + [2.0]
    assert is_regime_tradeable(history, avg_period=20) is True


def test_regime_current_atr_below_avg_blocks_trade() -> None:
    # 19 values of 2.0, then current = 0.5 — choppy/low-vol regime
    history = [2.0] * 19 + [0.5]
    assert is_regime_tradeable(history, avg_period=20) is False


# ---------------------------------------------------------------------------
# cooling_off_score / is_cooling_off
# ---------------------------------------------------------------------------


def test_cooling_off_empty_outcomes_zero_score() -> None:
    assert cooling_off_score([]) == 0.0


def test_cooling_off_all_wins_zero_score() -> None:
    assert cooling_off_score([10.0, 5.0, 3.0], decay=0.7) == 0.0


def test_cooling_off_all_losses_score_one() -> None:
    score = cooling_off_score([-10.0, -5.0, -3.0], decay=0.7)
    assert score == 1.0


def test_cooling_off_recent_loss_weighted_higher() -> None:
    # [win, win, loss] — loss is most recent, should dominate with decay
    score_recent_loss = cooling_off_score([10.0, 10.0, -5.0], decay=0.7)
    # [loss, win, win] — loss is oldest, should be discounted
    score_old_loss = cooling_off_score([-5.0, 10.0, 10.0], decay=0.7)
    assert score_recent_loss > score_old_loss


def test_is_cooling_off_above_threshold() -> None:
    # All losses should trigger cooling-off
    assert is_cooling_off([-1.0, -1.0, -1.0, -1.0, -1.0], decay=0.7, threshold=0.6) is True


def test_is_cooling_off_below_threshold() -> None:
    # Mix of wins and losses below threshold
    assert is_cooling_off([10.0, 10.0, -1.0], decay=0.7, threshold=0.6) is False


# ---------------------------------------------------------------------------
# compute_net_ev
# ---------------------------------------------------------------------------


def test_net_ev_positive() -> None:
    # 2% expected return at 80% confidence, 0.05% slippage per side
    ev = compute_net_ev(0.02, 0.8, slippage_pct=0.0005)
    assert ev > 0


def test_net_ev_negative_when_costs_exceed_ev() -> None:
    # Very small move, low confidence — costs dominate
    ev = compute_net_ev(0.001, 0.3, slippage_pct=0.0005)
    assert ev < 0


def test_net_ev_zero_pct_move_is_negative() -> None:
    ev = compute_net_ev(0.0, 0.8, slippage_pct=0.0005)
    assert ev < 0  # pure cost, no return


# ---------------------------------------------------------------------------
# compute_kelly_size
# ---------------------------------------------------------------------------


def test_kelly_size_zero_win_prob() -> None:
    assert compute_kelly_size(0.0, 0.04, 0.02) == 0.0


def test_kelly_size_negative_ev_returns_zero() -> None:
    # win_prob=0.3, win=0.01, loss=0.04 → Kelly < 0 → return 0
    size = compute_kelly_size(0.3, 0.01, 0.04)
    assert size == 0.0


def test_kelly_size_capped_at_max_risk() -> None:
    # Very high confidence with 2:1 odds — Kelly might want more than max_risk
    size = compute_kelly_size(0.9, 0.10, 0.05, kelly_scale=1.0, max_risk_pct=0.015)
    assert size <= 0.015


def test_kelly_size_scales_with_confidence() -> None:
    # Use max_risk_pct=1.0 so neither value is capped — verifies raw scaling
    low = compute_kelly_size(0.5, 0.04, 0.02, kelly_scale=0.25, max_risk_pct=1.0)
    high = compute_kelly_size(0.8, 0.04, 0.02, kelly_scale=0.25, max_risk_pct=1.0)
    assert high > low


# ---------------------------------------------------------------------------
# compute_dynamic_position_size
# ---------------------------------------------------------------------------


def test_dynamic_size_zero_confidence() -> None:
    assert compute_dynamic_position_size(0.0, 0.05, 0.10) == 0.0


def test_dynamic_size_enforces_min_rr() -> None:
    # If take_profit < 2 * stop_loss, it should be scaled up internally
    # Both calls should produce the same result because TP is forced to 2× SL
    size_tight_tp = compute_dynamic_position_size(0.7, 0.05, 0.03)
    size_2x_tp = compute_dynamic_position_size(0.7, 0.05, 0.10)
    # tight TP forces TP=0.10 anyway, so they match
    assert size_tight_tp == size_2x_tp


def test_dynamic_size_below_max_risk() -> None:
    size = compute_dynamic_position_size(0.9, 0.05, 0.10, max_risk_pct=0.015)
    assert size <= 0.015
