"""End-to-end checks for the offline backtest harness.

Lives under tests/integration so CI runs it (the harness wires the production
signal decision to the production trade scorer — a genuine cross-module flow).
"""

from __future__ import annotations

from api.constants import FieldName
from backtest.data import synthetic_prices
from backtest.engine import run_backtest


def test_backtest_runs_end_to_end_and_reuses_trade_scorer():
    """A volatile series produces trades scored by the production trade_scorer."""
    prices = synthetic_prices(n=500, vol_pct=1.2, seed=7)
    result = run_backtest(prices, symbol="BTC/USD", slippage_seed=7)

    assert result.bars == 500
    assert result.trades >= 1
    # Metrics are produced by api.services.agents.trade_scorer, not reinvented.
    assert FieldName.SHARPE_RATIO in result.metrics
    assert FieldName.WIN_RATE in result.metrics
    assert result.metrics[FieldName.TOTAL_TRADES] == result.trades
    assert len(result.evaluations) == result.trades
    assert result.final_equity > 0
    assert 0.0 <= result.win_rate <= 1.0


def test_backtest_is_deterministic_for_a_seed():
    """Same prices + same slippage seed => byte-identical result."""
    prices = synthetic_prices(n=300, vol_pct=1.0, seed=1)
    r1 = run_backtest(prices, slippage_seed=1)
    r2 = run_backtest(prices, slippage_seed=1)
    assert r1.total_return_pct == r2.total_return_pct
    assert r1.trades == r2.trades
    assert r1.final_equity == r2.final_equity


def test_realistic_volatility_almost_never_trades():
    """The 'idle' failure mode, reproduced offline.

    At realistic per-minute volatility (~0.1%), a single bar virtually never
    moves >= 1.5%, so the current signal sits in 'hold' forever — exactly the
    "0 trades most of the time" the operator observes live.
    """
    bars = 2000
    prices = synthetic_prices(n=bars, vol_pct=0.1, seed=3)
    result = run_backtest(prices, slippage_seed=3)
    assert result.trades == 0
    assert result.holds == bars - 1
    assert result.total_return_pct == 0.0
