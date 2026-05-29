"""Compare candidate strategies against the baseline on identical price paths.

Each strategy is run over the same set of seeded synthetic series (a *paired*
comparison — only the decision logic differs), and the per-seed results are
averaged. This is how you decide whether a hypothesis is worth promoting to
the live signal: it has to beat the baseline here first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean

from backtest.data import synthetic_prices
from backtest.engine import run_backtest
from backtest.strategies import STRATEGIES, Strategy

_DEFAULT_SEEDS = tuple(range(20))


@dataclass(frozen=True)
class StrategyStats:
    """Mean performance of one strategy across the evaluated seeds."""

    name: str
    mean_return_pct: float
    mean_trades: float
    mean_sharpe: float
    mean_win_rate: float


def compare_strategies(
    strategies: dict[str, Strategy] | None = None,
    *,
    seeds: Sequence[int] | None = None,
    n: int = 1500,
    vol_pct: float = 1.5,
    drift_pct: float = 0.0,
) -> list[StrategyStats]:
    """Run every strategy over identical seeded price paths and average results."""
    strategies = strategies or STRATEGIES
    seeds = _DEFAULT_SEEDS if seeds is None else seeds
    acc: dict[str, dict[str, list[float]]] = {
        name: {"r": [], "t": [], "s": [], "w": []} for name in strategies
    }
    for seed in seeds:
        prices = synthetic_prices(n=n, vol_pct=vol_pct, drift_pct=drift_pct, seed=seed)
        for name, strat in strategies.items():
            res = run_backtest(prices, strategy=strat, strategy_name=name, slippage_seed=seed)
            acc[name]["r"].append(res.total_return_pct)
            acc[name]["t"].append(float(res.trades))
            acc[name]["s"].append(res.sharpe)
            acc[name]["w"].append(res.win_rate)
    return [
        StrategyStats(
            name=name,
            mean_return_pct=round(mean(a["r"]), 2),
            mean_trades=round(mean(a["t"]), 1),
            mean_sharpe=round(mean(a["s"]), 3),
            mean_win_rate=round(mean(a["w"]), 4),
        )
        for name, a in acc.items()
    ]


def compare_on_prices(
    prices: Sequence[float],
    strategies: dict[str, Strategy] | None = None,
    *,
    slippage_seed: int = 1,
) -> list[StrategyStats]:
    """Run every strategy ONCE over a single (real) price series.

    Used for real-market backtests where there is one historical path rather
    than many synthetic seeds. Returns the same StrategyStats shape as
    ``compare_strategies`` so callers (and the API) are source-agnostic.
    """
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


def format_table(stats: list[StrategyStats]) -> str:
    """Render the comparison as a fixed-width table, best return first."""
    rows = sorted(stats, key=lambda s: s.mean_return_pct, reverse=True)
    lines = [
        f"{'strategy':<20}{'return%':>10}{'trades':>9}{'sharpe':>9}{'win%':>8}",
        "-" * 56,
    ]
    for s in rows:
        lines.append(
            f"{s.name:<20}{s.mean_return_pct:>10.2f}{s.mean_trades:>9.1f}"
            f"{s.mean_sharpe:>9.3f}{s.mean_win_rate * 100:>7.1f}%"
        )
    return "\n".join(lines)
