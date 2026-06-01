"""Unit tests for the evolution half: proposal engine, scorecard, challenger,
backtest gate, and gitops PR construction."""

from __future__ import annotations

import math

from cognitive.backtest_gate import evaluate_proposal, run_config_backtest
from cognitive.challenger import review
from cognitive.config import DEFAULT_CONFIG, CognitiveConfig
from cognitive.gitops import (
    apply_proposal_to_config,
    apply_to_config_text,
    branch_name,
    build_pull_request,
    config_diff,
)
from cognitive.learning import Observation
from cognitive.proposal import (
    Proposal,
    ProposalAgent,
    ProposalScorecard,
    ProposalStatus,
    ProposalType,
)


def _series(n: int = 400) -> list[float]:
    prices = [100.0]
    for i in range(1, n):
        prices.append(round(prices[-1] * (1 + 0.002 * math.sin(i / 25.0) + 0.0006), 4))
    return prices


# --- Backtest gate (the judge) --------------------------------------------
def test_backtest_is_deterministic_and_paired():
    prices = _series()
    a = run_config_backtest(prices, DEFAULT_CONFIG, slippage_seed=7)
    b = run_config_backtest(prices, DEFAULT_CONFIG, slippage_seed=7)
    assert a.as_dict() == b.as_dict()
    cand = CognitiveConfig.from_dict(
        {**DEFAULT_CONFIG.to_dict(), "weights": {"news": 0.34, "tech": 0.45, "macro": 0.33}}
    )
    delta = evaluate_proposal(prices, DEFAULT_CONFIG, cand, slippage_seed=7)
    # identical-config delta is exactly zero (paired, same slippage sequence)
    same = evaluate_proposal(prices, DEFAULT_CONFIG, DEFAULT_CONFIG, slippage_seed=7)
    assert same.pnl_delta == 0.0 and same.sharpe_delta == 0.0
    assert delta.baseline.trades >= 0  # metrics populated


# --- Proposal engine ------------------------------------------------------
def test_proposal_agent_turns_observation_into_typed_weight_change():
    obs = [
        Observation(
            observation="tech_agent_outperforming",
            confidence=0.9,
            signal="tech",
            direction="outperforming",
            evidence={"agent_grade": "A", "correct_rate": 0.9, "sample_size": 50},
        )
    ]
    proposal = ProposalAgent().propose(obs, DEFAULT_CONFIG)
    assert proposal is not None
    assert proposal.proposal_type == ProposalType.WEIGHT_CHANGE.value
    assert proposal.target == "weights.tech"
    assert proposal.new_value > proposal.old_value  # outperforming -> nudge up
    assert proposal.diff()["weights.tech"] == {"old": proposal.old_value, "new": proposal.new_value}


def test_proposal_agent_demands_more_confidence_when_history_is_poor():
    obs = [
        Observation("news_agent_outperforming", 0.70, "news", "outperforming", {"sample_size": 40})
    ]
    weak_history = ProposalScorecard()
    for _ in range(10):
        weak_history.record(ProposalType.WEIGHT_CHANGE.value, success=False)
    # with a 0% historical success rate the bar rises above 0.55 -> no proposal
    assert ProposalAgent().propose(obs, DEFAULT_CONFIG, weak_history) is None
    # with no history (prior 0.5) the same observation is allowed
    assert ProposalAgent().propose(obs, DEFAULT_CONFIG) is not None


def test_scorecard_tracks_success_rate_by_type():
    card = ProposalScorecard()
    card.record(ProposalType.WEIGHT_CHANGE.value, success=True)
    card.record(ProposalType.WEIGHT_CHANGE.value, success=False)
    assert card.success_rate(ProposalType.WEIGHT_CHANGE.value) == 0.5
    assert card.success_rate(ProposalType.PROMPT_CHANGE.value) == 0.5  # prior for unseen type
    assert card.snapshot()[ProposalType.WEIGHT_CHANGE.value]["attempts"] == 2


def test_proposal_type_hierarchy_constructors():
    assert (
        Proposal.prompt_change(target="news_agent_prompt", new_value="x", reason="r").proposal_type
        == ProposalType.PROMPT_CHANGE.value
    )
    assert (
        Proposal.tool_change(target="volatility_filter", action="enable", reason="r").proposal_type
        == ProposalType.TOOL_CHANGE.value
    )


# --- Challenger (safety validator) ----------------------------------------
class _FakeMetrics:
    def __init__(self, trades):
        self.trades = trades
        self.total_return_pct = 1.0
        self.sharpe = 0.5
        self.max_drawdown_pct = 2.0
        self.win_rate = 0.55
        self.false_positive_rate = 0.1
        self.signals = trades


class _FakeDelta:
    def __init__(self, pnl, sharpe, dd, trades):
        self.pnl_delta = pnl
        self.sharpe_delta = sharpe
        self.drawdown_delta = dd
        self.false_positive_rate_delta = 0.0
        self.baseline = _FakeMetrics(trades)
        self.candidate = _FakeMetrics(trades)


def test_challenger_approves_robust_improvement():
    good = _FakeDelta(pnl=2.0, sharpe=0.2, dd=-0.5, trades=50)
    verdict = review(
        in_sample=good,
        out_sample=good,
        learning_samples=50,
        candidate_config_valid=True,
        attribution_supports=True,
    )
    assert verdict.approved and verdict.risk_score == 0.0


def test_challenger_rejects_overfit():
    in_s = _FakeDelta(pnl=3.0, sharpe=0.5, dd=0.0, trades=50)
    out_s = _FakeDelta(pnl=-1.0, sharpe=-0.2, dd=0.0, trades=50)
    verdict = review(
        in_sample=in_s,
        out_sample=out_s,
        learning_samples=50,
        candidate_config_valid=True,
        attribution_supports=True,
    )
    assert not verdict.approved
    assert verdict.checks["no_overfit"] is False
    assert verdict.risk_score > 0


def test_challenger_rejects_small_sample_and_bad_attribution():
    delta = _FakeDelta(pnl=2.0, sharpe=0.2, dd=0.0, trades=5)
    verdict = review(
        in_sample=delta,
        out_sample=delta,
        learning_samples=5,
        candidate_config_valid=True,
        attribution_supports=False,
    )
    assert not verdict.approved
    assert verdict.checks["statistical_sanity"] is False
    assert verdict.checks["historically_consistent"] is False


# --- GitOps ---------------------------------------------------------------
def test_apply_proposal_bumps_version_and_stays_in_bounds():
    proposal = Proposal.weight_change(signal="news", old_value=0.34, new_value=0.39, reason="r")
    updated = apply_proposal_to_config(DEFAULT_CONFIG, proposal)
    assert updated is not None
    assert updated.weights["news"] == 0.39
    assert updated.version == DEFAULT_CONFIG.version + 1


def test_apply_proposal_rejects_non_config_types():
    prompt = Proposal.prompt_change(target="p", new_value="x", reason="r")
    assert apply_proposal_to_config(DEFAULT_CONFIG, prompt) is None


def test_apply_to_config_text_produces_canonical_json():
    raw = '{"buy_threshold": 0.15, "risk": {"max_daily_loss_pct": 0.02, "max_exposure_pct": 0.3, "max_position_size_pct": 0.05}, "sell_threshold": -0.15, "version": 1, "weights": {"macro": 0.33, "news": 0.34, "tech": 0.33}}'
    proposal = Proposal.weight_change(signal="news", old_value=0.34, new_value=0.39, reason="r")
    ok, text, err = apply_to_config_text(raw, proposal)
    assert ok and err is None
    assert '"news": 0.39' in text
    assert text.endswith("\n")


def test_config_diff_and_branch_name_and_pr_body():
    proposal = Proposal.weight_change(
        signal="news", old_value=0.34, new_value=0.39, reason="news strong"
    )
    after = apply_proposal_to_config(DEFAULT_CONFIG, proposal)
    diff = config_diff(DEFAULT_CONFIG.to_dict(), after.to_dict())
    paths = {c["path"] for c in diff}
    assert "weights.news" in paths and "version" in paths
    assert branch_name(proposal) == "cognitive-evolution/weights-news-0-39"

    good = _FakeDelta(pnl=2.0, sharpe=0.2, dd=-0.5, trades=50)
    verdict = review(
        in_sample=good,
        out_sample=good,
        learning_samples=50,
        candidate_config_valid=True,
        attribution_supports=True,
    )
    pr = build_pull_request(proposal, verdict, good, good, DEFAULT_CONFIG, after)
    assert pr.as_dict()["auto_merge"] is False
    assert "NO auto-merge" in pr.body
    assert "weights.news" in pr.body
    assert ProposalStatus.APPROVED.value  # enum import sanity
