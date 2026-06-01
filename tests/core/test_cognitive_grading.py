"""Unit tests for the multi-dimensional grading subsystem."""

from __future__ import annotations

from cognitive.grading import (
    grade_agent,
    grade_config_version,
    grade_proposal,
    grade_trade,
    letter_grade,
)


def test_letter_grade_bands_and_modifiers():
    assert letter_grade(98) == "A+"
    assert letter_grade(91) == "A-"
    assert letter_grade(85) == "B"
    assert letter_grade(80) == "B-"
    assert letter_grade(59) == "F"
    assert letter_grade(0) == "F"
    assert letter_grade(150) == "A+"  # clamped


def test_trade_grade_is_multidimensional_not_just_pnl():
    # A winner with severe slippage: direction strong, execution poor.
    winner_bad_exec = grade_trade(
        trade_id="T1",
        decision_score=0.5,
        realized_pnl_pct=2.0,
        max_adverse_pct=0.5,
        slippage_bps=12.0,
        side="buy",
        entry_price=100.0,
        window_low=98.0,
        window_high=104.0,
    )
    # A loser with clean execution: direction poor, execution strong.
    loser_clean_exec = grade_trade(
        trade_id="T2",
        decision_score=0.5,
        realized_pnl_pct=-2.0,
        max_adverse_pct=2.0,
        slippage_bps=0.0,
        side="buy",
        entry_price=100.0,
        window_low=98.0,
        window_high=104.0,
    )
    # The dimensions move independently — that is the whole point.
    assert winner_bad_exec.direction_grade in {"A", "A-", "A+", "B+", "B"}
    assert winner_bad_exec.execution_grade == "F"  # 12 bps slippage
    assert loser_clean_exec.direction_grade == "F"
    assert loser_clean_exec.execution_grade in {"A", "A+", "A-"}  # 0 slippage
    assert set(winner_bad_exec.components) == {"direction", "risk", "execution", "timing"}


def test_execution_grade_penalizes_slippage():
    clean = grade_trade(
        trade_id="T",
        decision_score=0.4,
        realized_pnl_pct=1.0,
        max_adverse_pct=0.3,
        slippage_bps=0.0,
        side="buy",
        entry_price=100,
        window_low=99,
        window_high=101,
    )
    sloppy = grade_trade(
        trade_id="T",
        decision_score=0.4,
        realized_pnl_pct=1.0,
        max_adverse_pct=0.3,
        slippage_bps=10.0,
        side="buy",
        entry_price=100,
        window_low=99,
        window_high=101,
    )
    assert clean.components["execution"] > sloppy.components["execution"]


def test_grade_agent_not_rated_below_min_samples():
    card = grade_agent("news", {"samples": 5, "correct_rate": 0.9, "total_pnl_attribution": 10})
    assert card.grade == "NR"
    rated = grade_agent("news", {"samples": 100, "correct_rate": 0.9, "total_pnl_attribution": 50})
    assert rated.grade != "NR" and rated.score > 0


def test_grade_proposal_and_config_version_monotonic():
    better = grade_proposal(
        proposal_id="P", proposal_type="weight_change", pnl_delta=2.0, sharpe_delta=0.3
    )
    worse = grade_proposal(
        proposal_id="P", proposal_type="weight_change", pnl_delta=-2.0, sharpe_delta=-0.3
    )
    assert better.score > worse.score
    strong = grade_config_version(version=2, sharpe=1.5, max_drawdown_pct=3.0)
    weak = grade_config_version(version=3, sharpe=0.2, max_drawdown_pct=15.0)
    assert strong.score > weak.score
