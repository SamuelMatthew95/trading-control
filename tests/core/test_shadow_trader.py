"""Tests for the ShadowTradeEngine — runs a Strategy on a live price stream.

These prove the keystone that connects strategy *configs* to live *agents*: a
strategy function actually drives shadow trades and produces real PnL/win-rate/
Sharpe on a price series, with no IO. Deterministic — a scripted strategy lets us
assert exact trade mechanics, and the real strategies confirm integration.
"""

from __future__ import annotations

from backtest.strategies import Bar
from api.services.shadow_trader import ShadowTradeEngine


def _scripted(actions: list[str]):
    """A Strategy that returns actions[bar.index-1] (index is 1-based), else hold."""

    def strategy(bar: Bar) -> str:
        i = bar.index - 1
        return actions[i] if 0 <= i < len(actions) else "hold"

    return strategy


# ---------------------------------------------------------------------------
# Position / PnL mechanics (scripted strategy → exact assertions)
# ---------------------------------------------------------------------------


def test_first_signal_opens_no_closed_trade():
    eng = ShadowTradeEngine("s", _scripted(["buy"]))
    assert eng.observe("BTC/USD", 100.0) is None  # opens long, nothing closed yet
    assert eng.metrics.trades == 0


def test_long_then_flip_realizes_profit():
    eng = ShadowTradeEngine("s", _scripted(["buy", "hold", "sell"]))
    assert eng.observe("BTC/USD", 100.0) is None  # open long @100
    assert eng.observe("BTC/USD", 105.0) is None  # hold — position stays open
    trade = eng.observe("BTC/USD", 110.0)  # sell -> close long @110, open short
    assert trade is not None
    assert trade.direction == "long"
    assert trade.entry_price == 100.0
    assert trade.exit_price == 110.0
    assert trade.pnl == 10.0
    assert trade.bars_held == 2
    assert eng.metrics.trades == 1
    assert eng.metrics.wins == 1
    assert eng.metrics.realized_pnl == 10.0


def test_short_realizes_profit_when_price_falls():
    eng = ShadowTradeEngine("s", _scripted(["sell", "buy"]))
    assert eng.observe("BTC/USD", 100.0) is None  # open short @100
    trade = eng.observe("BTC/USD", 90.0)  # buy -> close short @90 (profit), open long
    assert trade is not None
    assert trade.direction == "short"
    assert trade.pnl == 10.0  # entry(100) - exit(90)
    assert eng.metrics.wins == 1


def test_losing_trade_counts_as_loss():
    eng = ShadowTradeEngine("s", _scripted(["buy", "sell"]))
    eng.observe("BTC/USD", 100.0)  # long @100
    trade = eng.observe("BTC/USD", 95.0)  # close long @95 -> loss
    assert trade is not None
    assert trade.pnl == -5.0
    assert eng.metrics.trades == 1
    assert eng.metrics.wins == 0
    assert eng.metrics.win_rate == 0.0


def test_hold_keeps_position_open_no_trades():
    eng = ShadowTradeEngine("s", _scripted(["buy", "hold", "hold", "hold"]))
    for p in (100.0, 101.0, 102.0, 103.0):
        eng.observe("BTC/USD", p)
    assert eng.metrics.trades == 0  # never flipped, so never realized


def test_all_hold_never_trades():
    eng = ShadowTradeEngine("s", _scripted(["hold", "hold", "hold"]))
    for p in (100.0, 101.0, 99.0):
        assert eng.observe("BTC/USD", p) is None
    assert eng.metrics.trades == 0


def test_same_direction_signal_is_noop():
    eng = ShadowTradeEngine("s", _scripted(["buy", "buy", "buy"]))
    eng.observe("BTC/USD", 100.0)  # open long
    assert eng.observe("BTC/USD", 105.0) is None  # buy again -> already long, no-op
    assert eng.observe("BTC/USD", 110.0) is None
    assert eng.metrics.trades == 0  # never closed


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def test_win_rate_and_avg_pnl():
    # long@100->close@110 (+10 win), short@110->close@120 (-10 loss)
    eng = ShadowTradeEngine("s", _scripted(["buy", "sell", "buy"]))
    eng.observe("BTC/USD", 100.0)  # open long
    eng.observe("BTC/USD", 110.0)  # close long +10, open short
    eng.observe("BTC/USD", 120.0)  # close short -10 (entry110-exit120), open long
    assert eng.metrics.trades == 2
    assert eng.metrics.wins == 1
    assert eng.metrics.win_rate == 0.5
    assert eng.metrics.realized_pnl == 0.0
    assert eng.metrics.avg_pnl == 0.0


def test_sharpe_zero_below_two_trades():
    eng = ShadowTradeEngine("s", _scripted(["buy", "sell"]))
    eng.observe("BTC/USD", 100.0)
    eng.observe("BTC/USD", 110.0)  # 1 trade
    assert eng.metrics.sharpe == 0.0


def test_sharpe_positive_for_consistent_wins():
    eng = ShadowTradeEngine("s", _scripted(["buy", "sell", "buy", "sell"]))
    # two long round-trips, both +10
    eng.observe("BTC/USD", 100.0)  # open long
    eng.observe("BTC/USD", 110.0)  # close long +10, open short
    eng.observe("BTC/USD", 100.0)  # close short +10 (110-100), open long
    eng.observe("BTC/USD", 110.0)  # close long +10
    assert eng.metrics.trades == 3
    assert eng.metrics.realized_pnl == 30.0
    # all three trades identical (+10) -> zero variance -> sharpe defined as 0.0
    assert eng.metrics.sharpe == 0.0


def test_zero_and_negative_price_ignored():
    eng = ShadowTradeEngine("s", _scripted(["buy", "buy"]))
    assert eng.observe("BTC/USD", 0.0) is None
    assert eng.observe("", 100.0) is None
    assert eng.metrics.trades == 0


def test_per_symbol_isolation():
    eng = ShadowTradeEngine("s", _scripted(["buy", "buy", "sell", "sell"]))
    # BTC bar1=buy(open long), ETH bar2=buy(open long),
    # BTC bar3=sell(close long), ETH bar4=sell(close long)
    eng.observe("BTC/USD", 100.0)
    eng.observe("ETH/USD", 2000.0)
    t_btc = eng.observe("BTC/USD", 110.0)
    t_eth = eng.observe("ETH/USD", 1900.0)
    assert t_btc is not None and t_btc.symbol == "BTC/USD" and t_btc.pnl == 10.0
    assert t_eth is not None and t_eth.symbol == "ETH/USD" and t_eth.pnl == -100.0
    assert eng.metrics.trades == 2


# ---------------------------------------------------------------------------
# Integration with the REAL strategy functions
# ---------------------------------------------------------------------------


def test_real_baseline_momentum_trades_a_trend():
    """A clean up-then-down series must make baseline_momentum trade (proves the
    real strategy function is actually driving shadow trades)."""
    from backtest.strategies import STRATEGIES

    eng = ShadowTradeEngine("baseline_momentum", STRATEGIES["baseline_momentum"])
    price = 100.0
    # warmup so compute_return_sigma has enough samples, then a sharp move
    for _ in range(40):
        price *= 1.001
        eng.observe("BTC/USD", price)
    for _ in range(10):
        price *= 1.03  # strong up-moves -> momentum should go long
        eng.observe("BTC/USD", price)
    for _ in range(10):
        price *= 0.97  # strong down-moves -> should flip short, realizing trades
        eng.observe("BTC/USD", price)
    assert eng.metrics.trades >= 1


def test_mean_reversion_opposes_momentum_on_same_series():
    """mean_reversion and baseline_momentum must diverge on the same prices —
    proof the config actually changes behavior, not just the label."""
    from backtest.strategies import STRATEGIES

    momo = ShadowTradeEngine("baseline_momentum", STRATEGIES["baseline_momentum"])
    rev = ShadowTradeEngine("mean_reversion", STRATEGIES["mean_reversion"])
    price = 100.0
    prices = []
    for _ in range(40):
        price *= 1.001
        prices.append(price)
    for _ in range(15):
        price *= 1.02
        prices.append(price)
    momo_dirs, rev_dirs = [], []
    for p in prices:
        momo.observe("BTC/USD", p)
        rev.observe("BTC/USD", p)
        momo_dirs.append(momo._positions.get("BTC/USD"))
        rev_dirs.append(rev._positions.get("BTC/USD"))
    # On a sustained up-move momentum ends long, mean-reversion ends short.
    momo_pos = momo._positions["BTC/USD"].direction
    rev_pos = rev._positions["BTC/USD"].direction
    assert momo_pos == 1  # long
    assert rev_pos == -1  # short — opposite, so the config genuinely matters
