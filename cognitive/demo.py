"""Deterministic demo trajectory so the observability API has data without a live feed.

The live system would drive :class:`cognitive.loop.CognitiveLoop` from real market
events; in this environment (no broker feed) we seed it with a fixed synthetic run
so every UI tab is populated and the output is fully reproducible. The price path
spans several REGIMES (up-trend, chop, down-trend, high-vol) so walk-forward
validation sees different market conditions, and a deterministic sentiment series
is fed in so news weights are genuinely backtestable. Lives outside ``api/`` so it
can freely index event payloads without the FieldName ceremony.
"""

from __future__ import annotations

import math

from cognitive.agents import MarketView
from cognitive.config import load_config
from cognitive.loop import CognitiveLoop


def demo_prices(n: int = 480) -> list[float]:
    """A deterministic multi-regime synthetic price path."""
    prices = [100.0]
    seg = max(1, n // 4)
    for i in range(1, n):
        regime = i // seg
        if regime == 0:
            drift = 0.0015  # steady up-trend
        elif regime == 1:
            drift = 0.0006 * math.sin(i / 8.0)  # choppy / mean-reverting
        elif regime == 2:
            drift = -0.0012  # down-trend
        else:
            drift = 0.003 * math.sin(i / 5.0)  # high volatility
        prices.append(round(prices[-1] * (1 + drift), 4))
    return prices


def demo_news(prices: list[float]) -> list[float]:
    """A deterministic sentiment series correlated with recent momentum.

    Giving news genuine (if simple) predictive content means a news-weight
    proposal actually moves the backtest, so the gate can judge it — rather than
    news being a constant 0 that makes every news proposal look inert.
    """
    out: list[float] = []
    for i in range(len(prices)):
        if i < 2 or not prices[i - 2]:
            out.append(0.0)
            continue
        recent = (prices[i - 1] - prices[i - 2]) / prices[i - 2]
        out.append(round(max(-1.0, min(1.0, recent * 60.0)), 4))
    return out


def build_seeded_loop() -> CognitiveLoop:
    """Run a fixed scenario (trades -> grade -> learn -> evolve -> maybe merge)."""
    loop = CognitiveLoop(load_config())
    prices = demo_prices()
    news = demo_news(prices)
    for i in range(60, len(prices), 7):
        history = prices[max(0, i - 64) : i + 1]
        market = MarketView(
            "NVDA", prices[i], history, news_sentiment=news[i], news_confidence=0.8, ts=f"t{i}"
        )
        result = loop.step(market, equity=100_000, position_pct=0.03)
        score = result["decision"].score
        pnl_pct = 1.6 if score > 0 else (-1.2 if score < 0 else 0.1)
        side = result["decision"].action if result["decision"].action != "hold" else "buy"
        loop.close_trade(
            result["trace_id"],
            realized_pnl=pnl_pct * 900,
            realized_pnl_pct=pnl_pct,
            max_adverse_pct=0.5,
            slippage_bps=1.0,
            side=side,
            entry_price=prices[i],
            window_low=min(history),
            window_high=max(history),
        )
    loop.learn()
    bundle = loop.evolve(prices, split=0.5, slippage_seed=5, news=news)
    if (
        bundle
        and bundle.get("verdict") is not None
        and bundle["verdict"].approved
        and bundle.get("candidate_config") is not None
    ):
        out = bundle["out_sample"]
        loop.merge(
            bundle["candidate_config"],
            sharpe=out.candidate.sharpe,
            max_drawdown_pct=out.candidate.max_drawdown_pct,
            proposal_id=bundle["proposal"].proposal_id,
        )
    return loop
