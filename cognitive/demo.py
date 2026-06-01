"""Deterministic demo trajectory so the observability API has data without a live feed.

The live system would drive :class:`cognitive.loop.CognitiveLoop` from real market
events; in this environment (no broker feed) we seed it with a fixed synthetic run
so every UI tab is populated and the output is fully reproducible. Lives outside
``api/`` so it can freely index event payloads without the FieldName ceremony.
"""

from __future__ import annotations

import math

from cognitive.agents import MarketView
from cognitive.config import load_config
from cognitive.loop import CognitiveLoop


def demo_prices(n: int = 400) -> list[float]:
    """A deterministic trending+oscillating synthetic price path."""
    prices = [100.0]
    for i in range(1, n):
        prices.append(round(prices[-1] * (1 + 0.002 * math.sin(i / 25.0) + 0.0006), 4))
    return prices


def build_seeded_loop() -> CognitiveLoop:
    """Run a fixed scenario (trades -> grade -> learn -> evolve -> maybe merge)."""
    loop = CognitiveLoop(load_config())
    prices = demo_prices()
    for i in range(60, len(prices), 7):
        history = prices[max(0, i - 64) : i + 1]
        market = MarketView(
            "NVDA", prices[i], history, news_sentiment=0.6, news_confidence=0.85, ts=f"t{i}"
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
    bundle = loop.evolve(prices, split=0.5, slippage_seed=5)
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
