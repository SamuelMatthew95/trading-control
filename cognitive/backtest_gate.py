"""BACKTEST GATE — config-parameterized backtest; the JUDGE of every proposal.

This is the piece that closes the loop. It runs the SAME deterministic decision
engine (:func:`cognitive.decision.decide`) over a price series under two configs
— a baseline and a candidate — on IDENTICAL data with an IDENTICAL seeded
slippage sequence (a paired comparison), then reports the deltas a proposal MUST
carry before it can become a PR::

    {pnl_delta, sharpe_delta, drawdown_delta, false_positive_rate_delta}

Every change to weights/thresholds therefore traces back to a measurable PnL
impact. A proposal with no backtest delta is, by construction, invalid.

It reuses the production slippage model from ``backtest.engine`` and the paper
starting cash from ``api.constants`` so the offline number cannot silently
diverge from the live broker's mechanics.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from api.constants import DEFAULT_PAPER_CASH
from backtest.engine import SLIPPAGE_MAX_PCT, SLIPPAGE_MIN_PCT
from cognitive.agents import (
    MacroAgent,
    MarketView,
    NewsAgent,
    RiskAgent,
    TechnicalAgent,
    macro_regime,
    risk_assessment,
    technical_trend,
)
from cognitive.aggregation import aggregate
from cognitive.config import CognitiveConfig
from cognitive.decision import BUY, SELL, decide

DEFAULT_POSITION_FRACTION = 0.95
HISTORY_WINDOW = 64


@dataclass(frozen=True)
class ConfigBacktestMetrics:
    """Headline metrics from one config run over one price series."""

    total_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    trades: int
    signals: int
    win_rate: float
    false_positive_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_return_pct": self.total_return_pct,
            "sharpe": self.sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "trades": self.trades,
            "signals": self.signals,
            "win_rate": self.win_rate,
            "false_positive_rate": self.false_positive_rate,
        }


@dataclass(frozen=True)
class BacktestDelta:
    """Paired baseline-vs-candidate comparison — the evidence a proposal carries."""

    baseline: ConfigBacktestMetrics
    candidate: ConfigBacktestMetrics
    pnl_delta: float
    sharpe_delta: float
    drawdown_delta: float
    false_positive_rate_delta: float

    @property
    def improves(self) -> bool:
        """A conservative "did it help?" — more return, not-worse drawdown."""
        return self.pnl_delta > 0 and self.drawdown_delta <= 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.as_dict(),
            "candidate": self.candidate.as_dict(),
            "pnl_delta": self.pnl_delta,
            "sharpe_delta": self.sharpe_delta,
            "drawdown_delta": self.drawdown_delta,
            "false_positive_rate_delta": self.false_positive_rate_delta,
            "improves": self.improves,
        }


def _sharpe(pnls: Sequence[float]) -> float:
    """Per-trade Sharpe proxy: mean / population-stdev of trade PnLs."""
    if len(pnls) < 2:
        return 0.0
    sd = statistics.pstdev(pnls)
    if sd <= 1e-12:
        return 0.0
    return round(statistics.fmean(pnls) / sd, 4)


def _max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    """Largest peak-to-trough drop of the equity curve, as a percentage."""
    peak = equity_curve[0] if equity_curve else 0.0
    worst = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak:
            worst = max(worst, (peak - equity) / peak)
    return round(worst * 100.0, 4)


def run_config_backtest(
    prices: Sequence[float],
    config: CognitiveConfig,
    *,
    news: Sequence[float] | None = None,
    symbol: str = "SYNTHETIC",
    starting_equity: float = DEFAULT_PAPER_CASH,
    position_fraction: float = DEFAULT_POSITION_FRACTION,
    slippage_seed: int = 0,
) -> ConfigBacktestMetrics:
    """Replay ``prices`` through the cognitive decision engine under ``config``.

    A long/short flip model: BUY targets long, SELL targets short, HOLD keeps the
    current position. Closed round-trips are scored; a "false positive" is a
    closed trade that lost money.
    """
    rng = random.Random(slippage_seed)
    news_agent, tech_agent, macro_agent, risk_agent = (
        NewsAgent(),
        TechnicalAgent(lambda m: technical_trend(m.history)),
        MacroAgent(lambda m: macro_regime(m.history)),
        RiskAgent(lambda m: risk_assessment(m.history)),
    )

    def fill(price: float, direction: int) -> float:
        slip = rng.uniform(SLIPPAGE_MIN_PCT, SLIPPAGE_MAX_PCT)
        return price * (1.0 + (1 if direction > 0 else -1) * slip)

    cash = float(starting_equity)
    open_dir = 0
    open_price = 0.0
    open_qty = 0.0
    trade_pnls: list[float] = []
    equity_curve: list[float] = []
    signals = 0
    losing = 0

    for index, price in enumerate(prices):
        history = prices[max(0, index - HISTORY_WINDOW + 1) : index + 1]
        news_sentiment = news[index] if news is not None and index < len(news) else None
        market = MarketView(
            symbol=symbol,
            price=price,
            history=history,
            news_sentiment=news_sentiment,
            news_confidence=1.0 if news_sentiment is not None else 0.0,
        )
        features = aggregate(
            news_agent.analyze(market),
            tech_agent.analyze(market),
            macro_agent.analyze(market),
            risk_agent.analyze(market),
        )
        decision = decide(features, config)
        if decision.action in (BUY, SELL):
            signals += 1
        target_dir = 1 if decision.action == BUY else (-1 if decision.action == SELL else open_dir)

        if target_dir != open_dir:
            if open_dir != 0:
                exit_fill = fill(price, -open_dir)
                pnl = open_dir * open_qty * (exit_fill - open_price)
                trade_pnls.append(pnl)
                cash += pnl
                if pnl < 0:
                    losing += 1
            if target_dir != 0:
                entry = fill(price, target_dir)
                open_qty = (cash * position_fraction) / entry
                open_price = entry
                open_dir = target_dir
            else:
                open_dir, open_qty, open_price = 0, 0.0, 0.0

        marked = cash + (open_dir * open_qty * (price - open_price) if open_dir else 0.0)
        equity_curve.append(marked)

    if open_dir != 0 and prices:
        exit_fill = fill(prices[-1], -open_dir)
        pnl = open_dir * open_qty * (exit_fill - open_price)
        trade_pnls.append(pnl)
        cash += pnl
        if pnl < 0:
            losing += 1

    trades = len(trade_pnls)
    wins = sum(1 for pnl in trade_pnls if pnl > 0)
    return ConfigBacktestMetrics(
        total_return_pct=round((cash / starting_equity - 1.0) * 100.0, 4),
        sharpe=_sharpe(trade_pnls),
        max_drawdown_pct=_max_drawdown_pct(equity_curve),
        trades=trades,
        signals=signals,
        win_rate=round(wins / trades, 4) if trades else 0.0,
        false_positive_rate=round(losing / trades, 4) if trades else 0.0,
    )


def evaluate_proposal(
    prices: Sequence[float],
    baseline_config: CognitiveConfig,
    candidate_config: CognitiveConfig,
    *,
    news: Sequence[float] | None = None,
    slippage_seed: int = 0,
) -> BacktestDelta:
    """Run both configs on identical data + slippage and return the deltas."""
    baseline = run_config_backtest(prices, baseline_config, news=news, slippage_seed=slippage_seed)
    candidate = run_config_backtest(
        prices, candidate_config, news=news, slippage_seed=slippage_seed
    )
    return BacktestDelta(
        baseline=baseline,
        candidate=candidate,
        pnl_delta=round(candidate.total_return_pct - baseline.total_return_pct, 4),
        sharpe_delta=round(candidate.sharpe - baseline.sharpe, 4),
        drawdown_delta=round(candidate.max_drawdown_pct - baseline.max_drawdown_pct, 4),
        false_positive_rate_delta=round(
            candidate.false_positive_rate - baseline.false_positive_rate, 4
        ),
    )


@dataclass(frozen=True)
class WalkForwardResult:
    """Baseline-vs-candidate evaluated across several sequential OOS segments.

    ``consistency`` is the fraction of folds the candidate beats the baseline on
    — the anti-overfit metric: a candidate that only wins one lucky window scores
    low here even if its single-split PnL delta looks great.
    """

    folds: list[BacktestDelta]
    consistency: float
    mean_pnl_delta: float
    mean_sharpe_delta: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "consistency": self.consistency,
            "mean_pnl_delta": self.mean_pnl_delta,
            "mean_sharpe_delta": self.mean_sharpe_delta,
            "folds": [fold.as_dict() for fold in self.folds],
        }


def walk_forward(
    prices: Sequence[float],
    baseline_config: CognitiveConfig,
    candidate_config: CognitiveConfig,
    *,
    folds: int = 4,
    news: Sequence[float] | None = None,
    slippage_seed: int = 0,
) -> WalkForwardResult:
    """Paired baseline-vs-candidate backtest across ``folds`` contiguous segments.

    The series is split into ``folds`` sequential out-of-sample windows (each with
    its own slippage seed), so a candidate must beat the baseline across DIFFERENT
    market periods, not just one. Short series fall back to a single paired eval.
    """
    n = len(prices)
    if folds < 2 or n < folds * 2:
        single = evaluate_proposal(
            prices, baseline_config, candidate_config, news=news, slippage_seed=slippage_seed
        )
        return WalkForwardResult(
            folds=[single],
            consistency=1.0 if single.pnl_delta > 0 else 0.0,
            mean_pnl_delta=single.pnl_delta,
            mean_sharpe_delta=single.sharpe_delta,
        )
    seg = n // folds
    deltas: list[BacktestDelta] = []
    for fold in range(folds):
        start = fold * seg
        end = n if fold == folds - 1 else (fold + 1) * seg
        seg_news = None if news is None else news[start:end]
        deltas.append(
            evaluate_proposal(
                prices[start:end],
                baseline_config,
                candidate_config,
                news=seg_news,
                slippage_seed=slippage_seed + fold,
            )
        )
    positive = sum(1 for delta in deltas if delta.pnl_delta > 0)
    return WalkForwardResult(
        folds=deltas,
        consistency=round(positive / len(deltas), 4),
        mean_pnl_delta=round(statistics.fmean(delta.pnl_delta for delta in deltas), 4),
        mean_sharpe_delta=round(statistics.fmean(delta.sharpe_delta for delta in deltas), 4),
    )
