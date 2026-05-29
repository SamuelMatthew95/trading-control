"""Compare candidate strategies against the baseline on one price series.

Every strategy is run over the *same* prices — a paired comparison where only
the decision logic differs — and returns a uniform ``StrategyStats`` shape, so
callers (the API, the challenger evaluator) are source-agnostic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backtest.engine import run_backtest
from backtest.strategies import STRATEGIES, Strategy


@dataclass(frozen=True)
class StrategyStats:
    """Performance of one strategy over the evaluated price series."""

    name: str
    mean_return_pct: float
    mean_trades: float
    mean_sharpe: float
    mean_win_rate: float


def compare_on_prices(
    prices: Sequence[float],
    strategies: dict[str, Strategy] | None = None,
    *,
    slippage_seed: int = 1,
) -> list[StrategyStats]:
    """Run every strategy once over a single price series and collect results."""
    strategies = strategies or STRATEGIES
    out: list[StrategyStats] = []
    for name, strat in strategies.items():
        res = run_backtest(prices, strategy=strat, strategy_name=name, slippage_seed=slippage_seed)
        out.append(
            StrategyStats(
                name=name,
                mean_return_pct=round(res.total_return_pct, 2),
                mean_trades=float(res.trades),
                mean_sharpe=round(res.sharpe, 3),
                mean_win_rate=round(res.win_rate, 4),
            )
        )
    return out
