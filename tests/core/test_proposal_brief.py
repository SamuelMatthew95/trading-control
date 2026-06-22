"""Tests for the proposal implementation-brief builder + evidence tiering.

Pure unit tests — no DB, no Redis, no network. These lock in the #341 fix: a
small-sample proposal is framed as a WATCH ITEM (not a confident "disable X"),
and every brief is Claude-Code-ready (mechanism options, affected area,
acceptance criteria, project constraints, and a ready-to-paste prompt).
"""

from __future__ import annotations

from api.constants import PROPOSAL_SOLID_EVIDENCE_TRADES, FieldName
from api.services.proposal_brief import (
    TIER_EMERGING,
    TIER_PRELIMINARY,
    TIER_SOLID,
    build_implementation_brief,
    classify_evidence,
    evidence_blocks_issue,
    evidence_from_reflection,
    evidence_is_solid,
)

# ---------------------------------------------------------------------------
# Evidence tiering — labelling, never a gate
# ---------------------------------------------------------------------------


def test_single_trade_is_preliminary():
    assert classify_evidence(1, has_backtest=False) == TIER_PRELIMINARY
    assert classify_evidence(1, has_backtest=True) == TIER_PRELIMINARY


def test_handful_of_trades_is_emerging():
    assert classify_evidence(8, has_backtest=False) == TIER_EMERGING
    # A real but young pattern is emerging even with a backtest, until the
    # sample clears the solid bar.
    assert classify_evidence(PROPOSAL_SOLID_EVIDENCE_TRADES - 1, has_backtest=True) == TIER_EMERGING


def test_large_sample_with_backtest_is_solid():
    assert classify_evidence(PROPOSAL_SOLID_EVIDENCE_TRADES, has_backtest=True) == TIER_SOLID
    # No backtest → never solid no matter the sample.
    assert classify_evidence(500, has_backtest=False) == TIER_EMERGING


def test_evidence_is_solid_helper():
    assert evidence_is_solid(
        {FieldName.SAMPLE_SIZE: 50, FieldName.BACKTEST: {FieldName.WIN_RATE: 0.6}}
    )
    assert not evidence_is_solid({FieldName.SAMPLE_SIZE: 2, FieldName.BACKTEST: None})


def test_evidence_blocks_issue_gates_only_present_insufficient_evidence():
    """The issue-filing gate: block ONLY when an evidence block is present and
    explicitly insufficient. Absent/empty evidence (structural proposals) and
    solid evidence both pass through to a GitHub issue."""
    # Absent / empty → never blocks (structural architect proposals still file).
    assert not evidence_blocks_issue({})
    assert not evidence_blocks_issue(None)  # type: ignore[arg-type]
    # Explicit evidence_sufficient flag is honoured (the recurring-noise shape).
    assert evidence_blocks_issue(
        {FieldName.SAMPLE_SIZE: 5, FieldName.BACKTEST: None, FieldName.EVIDENCE_SUFFICIENT: False}
    )
    assert not evidence_blocks_issue(
        {FieldName.SAMPLE_SIZE: 40, FieldName.EVIDENCE_SUFFICIENT: True}
    )
    # No explicit flag → fall back to the solid bar.
    assert evidence_blocks_issue({FieldName.SAMPLE_SIZE: 2, FieldName.BACKTEST: None})
    assert not evidence_blocks_issue(
        {FieldName.SAMPLE_SIZE: 50, FieldName.BACKTEST: {FieldName.WIN_RATE: 0.6}}
    )


# ---------------------------------------------------------------------------
# The #341 case — model governance off a single trade
# ---------------------------------------------------------------------------


def test_preliminary_model_regime_brief_is_a_watch_item():
    """The exact #341 shape: 'disable gemini in risk-off' off one trade. The brief
    must NOT read as a go-ahead — it frames it as a watch item and spells out the
    evidence needed, while still surfacing the right mechanism options."""
    brief = build_implementation_brief(
        proposal_type="regime_adjustment",
        summary="Reduce or disable gemini:gemini-2.5-flash-lite in the risk-off macro regime",
        content={
            FieldName.DESCRIPTION: "Model underperformed in risk-off.",
            FieldName.REASON: "one losing trade, pnl -4.05",
        },
        evidence={FieldName.SAMPLE_SIZE: 1, FieldName.REGIME: "risk_off"},
        category="regime",
    )
    assert "Preliminary" in brief
    assert "WATCH ITEM" in brief
    assert "do NOT" in brief or "DO NOT" in brief
    # Model-governance mechanism menu (the triage's "decide the mechanism" ask).
    assert "down-weight" in brief.lower()
    assert "fallback" in brief.lower()
    assert "disable" in brief.lower()
    # Names the evidence threshold that WOULD make it actionable.
    assert str(PROPOSAL_SOLID_EVIDENCE_TRADES) in brief


def test_brief_is_claude_code_ready():
    brief = build_implementation_brief(
        proposal_type="code_change",
        summary="Add an order-book imbalance perception tool",
        content={FieldName.DESCRIPTION: "imbalance predicts short-horizon reversals"},
        evidence={FieldName.SAMPLE_SIZE: 40, FieldName.BACKTEST: {FieldName.WIN_RATE: 0.61}},
    )
    # The handoff scaffolding a human/Claude needs to open a PR.
    assert "Ready-to-paste Claude Code prompt" in brief
    assert "Acceptance criteria" in brief
    assert "Affected area" in brief
    assert "FieldName" in brief  # project invariants are spelled out
    assert "open a pull request" in brief.lower()
    # Solid evidence reads as ready, not a watch item.
    assert "Ready to implement" in brief


def test_self_extension_brief_points_at_the_architect():
    """A self-extension proposal (the system proposing a new automated check) must
    point Claude Code at SystemArchitect and offer the add-an-observer mechanism."""
    brief = build_implementation_brief(
        proposal_type="code_change",
        summary="Automate the response to a recurring late_entry mistake",
        content={FieldName.DESCRIPTION: "Add a new SystemArchitect observer for late_entry"},
        evidence={FieldName.SAMPLE_SIZE: 8},
        category="self-extension new observer",
    )
    assert "system_architect.py" in brief
    assert "_*_observation" in brief or "observer" in brief.lower()


def test_brief_is_robust_to_empty_inputs():
    brief = build_implementation_brief(
        proposal_type="regime_adjustment",
        summary="",
        content={},
        evidence={},
    )
    assert "regime adjustment" in brief
    assert "Preliminary" in brief  # empty evidence → n=0 → preliminary


# ---------------------------------------------------------------------------
# evidence_from_reflection
# ---------------------------------------------------------------------------


def test_evidence_from_reflection_extracts_sample_regime_and_solidity():
    reflection = {
        FieldName.TRADES_ANALYZED: 30,
        FieldName.WIN_RATE: 0.55,
        FieldName.AVG_RETURN: 0.012,
        FieldName.REGIME_EDGE: {FieldName.CURRENT_REGIME: "risk_off"},
        FieldName.MODEL_PERFORMANCE: [
            {FieldName.MODEL_USED: "gemini:flash", FieldName.TOTAL_PNL: -4.0}
        ],
        FieldName.BACKTEST: {FieldName.WIN_RATE: 0.55},
    }
    evidence = evidence_from_reflection(reflection)
    assert evidence[FieldName.SAMPLE_SIZE] == 30
    assert evidence[FieldName.REGIME] == "risk_off"
    assert evidence[FieldName.EVIDENCE_SUFFICIENT] is True


def test_evidence_from_reflection_small_sample_not_sufficient():
    evidence = evidence_from_reflection({FieldName.TRADES_ANALYZED: 2})
    assert evidence[FieldName.SAMPLE_SIZE] == 2
    assert evidence[FieldName.EVIDENCE_SUFFICIENT] is False
