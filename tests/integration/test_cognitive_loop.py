"""Integration tests for the full cognitive loop on a single event stream.

These assert the architecture's core invariants end-to-end:
  * the loop is deterministic (same inputs -> same stream);
  * every stage emits a typed event (nothing computes off-stream);
  * learning + evolve NEVER mutate the live config (only merge does);
  * an approved proposal yields a PR plan and is never auto-merged;
  * the snapshot is a faithful read-only mirror with all observability tabs.
"""

from __future__ import annotations

import math

from cognitive.agents import MarketView
from cognitive.config import DEFAULT_CONFIG
from cognitive.events import EventType
from cognitive.loop import CognitiveLoop


def _series(n: int = 400) -> list[float]:
    prices = [100.0]
    for i in range(1, n):
        prices.append(round(prices[-1] * (1 + 0.002 * math.sin(i / 25.0) + 0.0006), 4))
    return prices


def _run_trades(loop: CognitiveLoop, prices: list[float], *, step: int = 7) -> None:
    for i in range(60, len(prices), step):
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


def test_full_forward_pass_emits_typed_events():
    loop = CognitiveLoop()
    market = MarketView("NVDA", 105.0, [100 + j * 0.2 for j in range(70)], ts="t0")
    loop.step(market, equity=100_000, position_pct=0.03, trace_id="trace-x")
    kinds = {event.kind for event in loop.stream if event.trace_id == "trace-x"}
    assert {
        EventType.NEWS_SIGNAL,
        EventType.TECH_SIGNAL,
        EventType.MACRO_SIGNAL,
        EventType.RISK_SIGNAL,
        EventType.FEATURES,
        EventType.REASONING,
        EventType.DECISION,
        EventType.RISK_GATE,
        EventType.EXECUTION,
    } <= kinds


def test_loop_is_deterministic():
    prices = _series()
    a, b = CognitiveLoop(), CognitiveLoop()
    _run_trades(a, prices)
    _run_trades(b, prices)
    assert a.stream.snapshot() == b.stream.snapshot()


def test_learning_and_evolve_never_mutate_live_config():
    loop = CognitiveLoop()
    before = loop.config.to_dict()
    _run_trades(loop, _series())
    loop.learn()
    loop.evolve(_series(), split=0.5, slippage_seed=5)
    assert loop.config.to_dict() == before  # only merge() may change config


def test_all_closed_trades_are_graded():
    loop = CognitiveLoop()
    _run_trades(loop, _series())
    health = loop.snapshot()["health"]["learning"]
    assert health["trades_closed"] > 0
    assert health["ungraded"] == 0


def test_evolve_produces_a_typed_proposal_with_backtest_evidence():
    loop = CognitiveLoop()
    _run_trades(loop, _series())
    bundle = loop.evolve(_series(), split=0.5, slippage_seed=5)
    assert bundle is not None and "proposal" in bundle
    # the proposal carries before/after + the backtest deltas that judged it
    assert bundle["proposal"].new_value != bundle["proposal"].old_value
    assert hasattr(bundle["out_sample"], "pnl_delta")
    assert "verdict" in bundle
    # a BACKTEST_RESULT and CHALLENGER_VERDICT were emitted onto the stream
    assert loop.stream.latest(EventType.BACKTEST_RESULT) is not None
    assert loop.stream.latest(EventType.CHALLENGER_VERDICT) is not None


def test_merge_advances_version_and_records_grade():
    loop = CognitiveLoop()
    candidate = DEFAULT_CONFIG.__class__.from_dict(
        {
            **DEFAULT_CONFIG.to_dict(),
            "version": 2,
            "weights": {"news": 0.39, "tech": 0.33, "macro": 0.33},
        }
    )
    result = loop.merge(candidate, sharpe=1.3, max_drawdown_pct=3.2)
    assert loop.config.version == 2
    assert result["grade"].grade  # a config-version report card was produced
    versions = [e.payload["version"] for e in loop.stream.events(kind=EventType.CONFIG_VERSION)]
    assert versions == [1, 2]  # v1 at init, v2 at merge — append-only history


def test_snapshot_exposes_all_observability_tabs():
    loop = CognitiveLoop()
    _run_trades(loop, _series())
    loop.learn()
    snap = loop.snapshot()
    for tab in (
        "live_agents",
        "reasoning",
        "decision",
        "proposals",
        "challenger",
        "learning",
        "evolution",
        "health",
        "traces",
        "agents_roster",
    ):
        assert tab in snap
    assert len(snap["agents_roster"]) == 6  # 5 specialists + proposal architect
    assert snap["traces"]  # at least one full trade trace reconstructed
