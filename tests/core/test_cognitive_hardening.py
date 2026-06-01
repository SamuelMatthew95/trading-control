"""Tests for the hardening pass: event retention, walk-forward validation,
proposal governance, per-trade config lineage, and the risk-independence
stream invariant."""

from __future__ import annotations

import math

from cognitive.agents import MarketView
from cognitive.backtest_gate import walk_forward
from cognitive.challenger import review
from cognitive.config import DEFAULT_CONFIG, CognitiveConfig
from cognitive.events import EventStream, EventType
from cognitive.governance import (
    BLOCKED_COOLDOWN,
    BLOCKED_DUPLICATE,
    BLOCKED_QUOTA,
    ProposalGovernor,
)
from cognitive.loop import CognitiveLoop
from cognitive.proposal import Proposal


def _series(n: int = 400) -> list[float]:
    prices = [100.0]
    for i in range(1, n):
        prices.append(round(prices[-1] * (1 + 0.002 * math.sin(i / 25.0) + 0.0006), 4))
    return prices


def _run_trades(loop: CognitiveLoop, prices: list[float], *, step: int = 7) -> None:
    for i in range(60, len(prices), step):
        history = prices[max(0, i - 64) : i + 1]
        market = MarketView("NVDA", prices[i], history, news_sentiment=0.6, news_confidence=0.85)
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


# --- #3 Event-stream retention -------------------------------------------
def test_event_stream_retention_evicts_oldest_keeps_seq_monotonic():
    stream = EventStream(max_events=5)
    for _ in range(20):
        stream.emit(EventType.DECISION, {"action": "hold"})
    assert len(stream) == 5  # only the tail is retained
    assert stream.dropped == 15
    assert stream.emitted == 20
    seqs = [event.seq for event in stream]
    assert seqs == [15, 16, 17, 18, 19]  # monotonic, unique, survives eviction


# --- #1 Walk-forward validation ------------------------------------------
def test_walk_forward_reports_folds_and_consistency():
    prices = _series()
    result = walk_forward(prices, DEFAULT_CONFIG, DEFAULT_CONFIG, folds=4)
    assert len(result.folds) == 4
    # identical configs => zero delta on every fold => zero consistency
    assert result.consistency == 0.0
    assert result.mean_pnl_delta == 0.0


class _FakeMetrics:
    def __init__(self, trades: int) -> None:
        self.trades = trades
        self.total_return_pct = 1.0
        self.sharpe = 0.5
        self.max_drawdown_pct = 2.0
        self.false_positive_rate = 0.1


class _FakeDelta:
    def __init__(self, pnl: float, sharpe: float, dd: float, trades: int) -> None:
        self.pnl_delta = pnl
        self.sharpe_delta = sharpe
        self.drawdown_delta = dd
        self.false_positive_rate_delta = 0.0
        self.baseline = _FakeMetrics(trades)
        self.candidate = _FakeMetrics(trades)


def test_challenger_rejects_low_walk_forward_consistency():
    good = _FakeDelta(pnl=2.0, sharpe=0.2, dd=-0.5, trades=50)
    rejected = review(
        in_sample=good,
        out_sample=good,
        learning_samples=50,
        candidate_config_valid=True,
        attribution_supports=True,
        walk_forward_consistency=0.25,  # below the 0.6 floor
    )
    assert not rejected.approved
    assert rejected.checks["walk_forward_consistent"] is False
    approved = review(
        in_sample=good,
        out_sample=good,
        learning_samples=50,
        candidate_config_valid=True,
        attribution_supports=True,
        walk_forward_consistency=0.8,
    )
    assert approved.approved


# --- #2 Proposal governance ----------------------------------------------
def test_governor_quota_dedup_and_cooldown():
    governor = ProposalGovernor(quota=2, window=10, cooldown=3)
    news = Proposal.weight_change(signal="news", old_value=0.34, new_value=0.39, reason="r")
    tech = Proposal.weight_change(signal="tech", old_value=0.33, new_value=0.38, reason="r")
    macro = Proposal.weight_change(signal="macro", old_value=0.33, new_value=0.38, reason="r")

    assert governor.admit(news) == (True, "admitted")
    assert governor.admit(news)[1] == BLOCKED_DUPLICATE  # exact repeat
    assert governor.admit(tech) == (True, "admitted")
    assert governor.admit(macro)[1] == BLOCKED_QUOTA  # 2 already admitted in window

    governor.record_outcome(tech, approved=False)  # bench weights.tech
    assert governor.admit(tech)[1] == BLOCKED_COOLDOWN


# --- #4 Per-trade config lineage -----------------------------------------
def _last_payload(loop: CognitiveLoop, kind: EventType, trace_id: str) -> dict:
    for event in reversed(list(loop.stream)):
        if event.kind == kind and event.trace_id == trace_id:
            return event.payload
    return {}


def test_trades_stamp_config_version_and_provenance():
    loop = CognitiveLoop()
    market = MarketView("NVDA", 105.0, [100 + j * 0.2 for j in range(70)])
    loop.step(market, equity=100_000, position_pct=0.03, trace_id="t1")
    assert _last_payload(loop, EventType.DECISION, "t1")["config_version"] == 1
    assert _last_payload(loop, EventType.EXECUTION, "t1")["config_version"] == 1

    # Land a v2 config and confirm subsequent trades carry the new lineage.
    candidate = CognitiveConfig.from_dict(
        {
            **DEFAULT_CONFIG.to_dict(),
            "version": 2,
            "weights": {"news": 0.39, "tech": 0.33, "macro": 0.33},
        }
    )
    loop.merge(candidate, sharpe=1.0, max_drawdown_pct=2.0, proposal_id="P-news-up")
    res2 = loop.step(market, equity=100_000, position_pct=0.03, trace_id="t2")
    loop.close_trade(
        res2["trace_id"],
        realized_pnl=10.0,
        realized_pnl_pct=1.0,
        max_adverse_pct=0.5,
        slippage_bps=1.0,
        side="buy",
        entry_price=105.0,
        window_low=100.0,
        window_high=110.0,
    )
    decision = _last_payload(loop, EventType.DECISION, "t2")
    outcome = _last_payload(loop, EventType.TRADE_OUTCOME, "t2")
    assert decision["config_version"] == 2
    assert decision["config_proposal_id"] == "P-news-up"
    assert outcome["config_version"] == 2 and outcome["config_proposal_id"] == "P-news-up"


# --- #5 Risk independence: no execution without a gate -------------------
def test_no_execution_event_without_a_preceding_risk_gate():
    loop = CognitiveLoop()
    _run_trades(loop, _series())
    gate_traces = {e.trace_id for e in loop.stream.events(kind=EventType.RISK_GATE)}
    exec_traces = {e.trace_id for e in loop.stream.events(kind=EventType.EXECUTION)}
    # every execution belongs to a trace that also produced a risk gate
    assert exec_traces and exec_traces <= gate_traces


# --- #1 News is genuinely backtestable when a sentiment series is supplied -
def test_news_weight_is_inert_without_sentiment_but_active_with_it():
    from cognitive.backtest_gate import evaluate_proposal

    prices = _series()
    news = [(1.0 if (i // 20) % 2 == 0 else -1.0) for i in range(len(prices))]
    candidate = CognitiveConfig.from_dict(
        {**DEFAULT_CONFIG.to_dict(), "weights": {"news": 0.6, "tech": 0.33, "macro": 0.33}}
    )
    # Without a sentiment series the news feature is constant 0, so changing the
    # news weight changes nothing — the bug the hardening pass fixed.
    without = evaluate_proposal(prices, DEFAULT_CONFIG, candidate, slippage_seed=3)
    assert without.pnl_delta == 0.0
    # With a sentiment series the news weight actually moves the backtest.
    with_news = evaluate_proposal(prices, DEFAULT_CONFIG, candidate, news=news, slippage_seed=3)
    assert with_news.candidate.as_dict() != with_news.baseline.as_dict()
