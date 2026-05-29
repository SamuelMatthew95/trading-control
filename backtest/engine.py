"""Pure, synchronous backtest engine.

Feeds a price series through the production signal decision
(:func:`api.services.signal_generator.classify_signal`), simulates fills with
the same slippage model as the paper broker, and scores every round-trip with
the production :mod:`api.services.agents.trade_scorer`. No async, no Redis, no
DB — fast and fully deterministic for a given ``slippage_seed``.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from api.constants import DEFAULT_PAPER_CASH, FieldName
from api.services.agents.trade_scorer import compute_learning_metrics, score_trade
from backtest.strategies import Bar, Strategy, baseline_momentum

# Mirrors api/services/execution/brokers/paper.py: fill = price * (1 ± slip),
# slip drawn uniformly from this fractional range (0.01%–0.05%).
SLIPPAGE_MIN_PCT = 0.0001
SLIPPAGE_MAX_PCT = 0.0005

# Fraction of current equity deployed as notional on each new position.
DEFAULT_POSITION_FRACTION = 0.95

# Confidence stamped on every simulated trade for scoring. The headline metrics
# (return, win rate, Sharpe, drawdown) are confidence-independent, so a constant
# keeps strategy comparisons apples-to-apples.
DEFAULT_CONFIDENCE = 0.6

# Window of recent closes handed to each strategy as context.
HISTORY_WINDOW = 64


@dataclass
class BacktestResult:
    """Outcome of a single backtest run."""

    symbol: str
    bars: int
    trades: int
    holds: int
    signals: int
    starting_equity: float
    final_equity: float
    total_return_pct: float
    win_rate: float
    sharpe: float
    max_drawdown_pct: float
    avg_trade_pnl: float
    strategy: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable one-block report."""
        return "\n".join(
            [
                f"Backtest — {self.symbol}" + (f"  [{self.strategy}]" if self.strategy else ""),
                f"  bars analysed   : {self.bars}",
                f"  trades          : {self.trades}   (holds: {self.holds})",
                f"  signals         : {self.signals}   (non-hold decisions)",
                f"  starting equity : ${self.starting_equity:,.2f}",
                f"  final equity    : ${self.final_equity:,.2f}",
                f"  total return    : {self.total_return_pct:+.2f}%",
                f"  win rate        : {self.win_rate * 100:.1f}%",
                f"  sharpe (annual) : {self.sharpe:.2f}",
                f"  max drawdown    : {self.max_drawdown_pct:.2f}%",
                f"  avg trade P&L   : ${self.avg_trade_pnl:+,.2f}",
            ]
        )


def run_backtest(
    prices: Sequence[float],
    *,
    strategy: Strategy = baseline_momentum,
    strategy_name: str = "",
    symbol: str = "SYNTHETIC",
    starting_equity: float = DEFAULT_PAPER_CASH,
    position_fraction: float = DEFAULT_POSITION_FRACTION,
    bar_minutes: float = 1.0,
    slippage_seed: int | None = 0,
) -> BacktestResult:
    """Replay ``prices`` through the live signal logic and score the result.

    The strategy is long/short and flips when the signal direction reverses;
    positions are marked-to-market each bar and any open position is closed at
    the final price. This isolates the *directional edge of the signal* —
    live-only mechanics (Kelly sizing, ATR stops, take-profit) are intentionally
    excluded so the number reflects the signal itself, nothing else.
    """
    rng = random.Random(slippage_seed)
    starting_equity = float(starting_equity)

    cash = starting_equity
    position_qty = 0.0  # signed: +long / -short / 0 flat

    # Currently open lot (tracked for per-trade scoring).
    open_dir = 0
    open_price = 0.0
    open_qty = 0.0
    open_bar = 0
    open_confidence = 0.0

    evaluations: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    holds = 0
    signals = 0  # non-hold strategy outputs (threshold hits), distinct from fills

    def _fill(price: float, signed_delta: float) -> float:
        """Slipped fill price — buys slip up, sells slip down (like PaperBroker)."""
        slip = rng.uniform(SLIPPAGE_MIN_PCT, SLIPPAGE_MAX_PCT)
        sign = 1.0 if signed_delta > 0 else -1.0
        return price * (1.0 + sign * slip)

    def _score(exit_fill: float, exit_bar: int) -> dict[str, Any]:
        """Build + score a closed round-trip using the production trade_scorer."""
        pnl = open_dir * open_qty * (exit_fill - open_price)
        pnl_pct = open_dir * (exit_fill - open_price) / open_price * 100.0
        return score_trade(
            {
                FieldName.SYMBOL: symbol,
                # trade_scorer close-side semantics: selling closes a long,
                # buying closes a short.
                FieldName.SIDE: "sell" if open_dir > 0 else "buy",
                FieldName.ACTION: "buy" if open_dir > 0 else "sell",
                FieldName.ENTRY_PRICE: open_price,
                FieldName.EXIT_PRICE: exit_fill,
                FieldName.PNL: pnl,
                FieldName.PNL_PERCENT: pnl_pct,
                FieldName.HOLDING_PERIOD_MINUTES: (exit_bar - open_bar) * bar_minutes,
                FieldName.CONFIDENCE: open_confidence,
            }
        )

    n = len(prices)
    for i in range(1, n):
        prev = float(prices[i - 1])
        cur = float(prices[i])
        pct = ((cur - prev) / prev * 100.0) if prev else 0.0
        bar = Bar(
            index=i,
            price=cur,
            prev_price=prev,
            pct=pct,
            history=[float(p) for p in prices[max(0, i - HISTORY_WINDOW) : i + 1]],
        )
        action = strategy(bar)

        if action == "hold":
            holds += 1
        else:
            signals += 1
            target_dir = 1 if action == "buy" else -1
            if target_dir == open_dir:
                holds += 1  # already positioned this way — no pyramiding
            else:
                # Close the existing lot (if any) at the current price.
                if open_dir != 0:
                    close_fill = _fill(cur, -position_qty)
                    cash -= (-position_qty) * close_fill
                    evaluations.append(_score(close_fill, i))
                    position_qty = 0.0
                    open_dir = 0
                # Open a fresh lot in the new direction.
                equity = cash + position_qty * cur
                qty = (position_fraction * equity) / cur
                signed = target_dir * qty
                open_fill = _fill(cur, signed)
                cash -= signed * open_fill
                position_qty = signed
                open_dir = target_dir
                open_price = open_fill
                open_qty = qty
                open_bar = i
                open_confidence = DEFAULT_CONFIDENCE

        equity_curve.append(cash + position_qty * cur)

    # Close any residual position at the last price so all P&L is realized.
    if open_dir != 0 and n >= 1:
        last = float(prices[-1])
        close_fill = _fill(last, -position_qty)
        cash -= (-position_qty) * close_fill
        evaluations.append(_score(close_fill, n - 1))
        position_qty = 0.0
        open_dir = 0

    final_equity = cash  # flat after the residual close → equity == cash
    if not equity_curve:
        equity_curve = [final_equity]
    else:
        equity_curve[-1] = final_equity

    total_return_pct = (final_equity - starting_equity) / starting_equity * 100.0

    # Drawdown from the realized equity path.
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)

    metrics = compute_learning_metrics(evaluations)
    trades = len(evaluations)
    avg_trade_pnl = (
        sum(float(e.get(FieldName.PNL) or 0.0) for e in evaluations) / trades if trades else 0.0
    )

    return BacktestResult(
        symbol=symbol,
        strategy=strategy_name,
        bars=n,
        trades=trades,
        holds=holds,
        signals=signals,
        starting_equity=starting_equity,
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        win_rate=float(metrics.get(FieldName.WIN_RATE) or 0.0),
        sharpe=float(metrics.get(FieldName.SHARPE_RATIO) or 0.0),
        max_drawdown_pct=max_dd,
        avg_trade_pnl=avg_trade_pnl,
        metrics=metrics,
        evaluations=evaluations,
        equity_curve=equity_curve,
    )
