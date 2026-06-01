"""GRADING — multi-dimensional, operationally-useful report cards.

A trade that lost money is not automatically an "F", and a winner is not
automatically an "A": a sound thesis can lose to noise and a bad one can get
lucky. So every closed trade gets FOUR independent grades plus an overall:

  * Direction  — did the thesis prove correct (decision sign vs realized move)?
  * Risk       — return earned per unit of adverse excursion suffered.
  * Execution  — fill quality (slippage).
  * Timing     — did we enter near a sensible point of the trade's range?

The same letter scale (A/B/C/D/F with +/- modifiers) is reused to grade AGENTS
(rolling contribution + hit-rate), PROPOSALS (realized backtest impact), and
CONFIG VERSIONS (Sharpe / drawdown report card) — which together drive the UI's
agent-performance, proposal-performance, and system-evolution views.

Pure functions; every grade is deterministic in its inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cognitive.events import EventType

SUBJECT_TRADE = "trade"
SUBJECT_AGENT = "agent"
SUBJECT_PROPOSAL = "proposal"
SUBJECT_CONFIG = "config_version"

# Overall trade grade is a weighted blend of the four dimensions.
TRADE_GRADE_WEIGHTS: dict[str, float] = {
    "direction": 0.40,
    "risk": 0.25,
    "execution": 0.15,
    "timing": 0.20,
}


def letter_grade(score: float) -> str:
    """Map a 0..100 score to a letter with +/- modifiers (e.g. 'B+', 'A-')."""
    score = max(0.0, min(100.0, score))
    if score < 60:
        return "F"
    for letter, low in (("A", 90), ("B", 80), ("C", 70), ("D", 60)):
        if score >= low:
            offset = score - low
            if offset >= 6.667:
                return f"{letter}+"
            if offset < 3.333:
                return f"{letter}-"
            return letter
    return "F"  # pragma: no cover - unreachable, the 60 floor catches it


def direction_component(decision_score: float, realized_pnl_pct: float) -> float:
    """100 = strongly correct thesis, 50 = neutral, 0 = completely wrong.

    The directional bet proved correct iff the position was profitable (this is
    side-agnostic: a profitable short means the bearish thesis was right). The
    grade scales with how decisively it resolved AND how convicted the call was,
    so a high-conviction call that is wrong scores worse than a tentative one.
    """
    if realized_pnl_pct == 0:
        return 50.0
    correct = realized_pnl_pct > 0
    move = min(1.0, abs(realized_pnl_pct) / 3.0)
    conviction = min(1.0, abs(decision_score) / 0.5)
    strength = 0.5 * move + 0.5 * conviction
    return 50.0 + 50.0 * strength if correct else 50.0 - 50.0 * strength


def risk_component(realized_pnl_pct: float, max_adverse_pct: float) -> float:
    """Risk-adjusted: return earned vs the worst adverse excursion endured."""
    ratio = realized_pnl_pct / (abs(max_adverse_pct) + 0.5)
    return max(0.0, min(100.0, 50.0 + 50.0 * math.tanh(ratio)))


def execution_component(slippage_bps: float) -> float:
    """Fill quality: 0 bps ~ 100; degrades ~8 points per basis point."""
    return max(0.0, min(100.0, 100.0 - abs(slippage_bps) * 8.0))


def timing_component(side: str, entry_price: float, window_low: float, window_high: float) -> float:
    """Where in the trade's price range we entered (buy low / sell high = good)."""
    span = window_high - window_low
    if span <= 0:
        return 50.0
    position = (entry_price - window_low) / span  # 0 = at the low, 1 = at the high
    quality = (1.0 - position) if side == "buy" else position
    return max(0.0, min(100.0, 100.0 * quality))


@dataclass(frozen=True)
class TradeGradeCard:
    """Four-dimensional report card for one closed trade."""

    trade_id: str
    overall_grade: str
    overall_score: float
    direction_grade: str
    risk_grade: str
    execution_grade: str
    timing_grade: str
    components: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.GRADE.value,
            "subject": SUBJECT_TRADE,
            "subject_id": self.trade_id,
            "grade": self.overall_grade,
            "score": self.overall_score,
            "direction_grade": self.direction_grade,
            "risk_grade": self.risk_grade,
            "execution_grade": self.execution_grade,
            "timing_grade": self.timing_grade,
            "components": dict(self.components),
        }


def grade_trade(
    *,
    trade_id: str,
    decision_score: float,
    realized_pnl_pct: float,
    max_adverse_pct: float,
    slippage_bps: float,
    side: str,
    entry_price: float,
    window_low: float,
    window_high: float,
) -> TradeGradeCard:
    """Produce the four-dimensional report card for one closed trade."""
    components = {
        "direction": round(direction_component(decision_score, realized_pnl_pct), 2),
        "risk": round(risk_component(realized_pnl_pct, max_adverse_pct), 2),
        "execution": round(execution_component(slippage_bps), 2),
        "timing": round(timing_component(side, entry_price, window_low, window_high), 2),
    }
    overall = round(sum(components[k] * TRADE_GRADE_WEIGHTS[k] for k in components), 2)
    return TradeGradeCard(
        trade_id=trade_id,
        overall_grade=letter_grade(overall),
        overall_score=overall,
        direction_grade=letter_grade(components["direction"]),
        risk_grade=letter_grade(components["risk"]),
        execution_grade=letter_grade(components["execution"]),
        timing_grade=letter_grade(components["timing"]),
        components=components,
    )


@dataclass(frozen=True)
class AgentGradeCard:
    """Rolling-window report card for one signal agent."""

    signal: str
    grade: str
    score: float
    samples: int
    correct_rate: float
    contribution: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.GRADE.value,
            "subject": SUBJECT_AGENT,
            "subject_id": self.signal,
            "grade": self.grade,
            "score": self.score,
            "samples": self.samples,
            "correct_rate": self.correct_rate,
            "contribution": self.contribution,
        }


def grade_agent(signal: str, stats: dict[str, float], *, min_samples: int = 30) -> AgentGradeCard:
    """Grade an agent from its importance metadata (hit-rate + PnL contribution)."""
    samples = int(stats.get("samples", 0))
    correct_rate = float(stats.get("correct_rate", 0.0))
    contribution = float(stats.get("total_pnl_attribution", 0.0))
    if samples < min_samples:
        return AgentGradeCard(signal, "NR", 0.0, samples, correct_rate, contribution)
    pnl_sign = 0.5 + 0.5 * math.tanh(contribution / (abs(contribution) + 1.0))
    score = round(100.0 * (0.7 * correct_rate + 0.3 * pnl_sign), 2)
    return AgentGradeCard(signal, letter_grade(score), score, samples, correct_rate, contribution)


@dataclass(frozen=True)
class ProposalGradeCard:
    """Report card for a proposal's realized backtest impact."""

    proposal_id: str
    proposal_type: str
    grade: str
    score: float
    pnl_delta: float
    sharpe_delta: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.GRADE.value,
            "subject": SUBJECT_PROPOSAL,
            "subject_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "grade": self.grade,
            "score": self.score,
            "pnl_delta": self.pnl_delta,
            "sharpe_delta": self.sharpe_delta,
        }


def grade_proposal(
    *, proposal_id: str, proposal_type: str, pnl_delta: float, sharpe_delta: float
) -> ProposalGradeCard:
    """Grade a proposal by the improvement it produced in backtest."""
    score = round(
        max(0.0, min(100.0, 50.0 + 30.0 * math.tanh(sharpe_delta) + 20.0 * math.tanh(pnl_delta))),
        2,
    )
    return ProposalGradeCard(
        proposal_id=proposal_id,
        proposal_type=proposal_type,
        grade=letter_grade(score),
        score=score,
        pnl_delta=pnl_delta,
        sharpe_delta=sharpe_delta,
    )


@dataclass(frozen=True)
class ConfigGradeCard:
    """Report card for a merged config version."""

    version: int
    grade: str
    score: float
    sharpe: float
    max_drawdown_pct: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.GRADE.value,
            "subject": SUBJECT_CONFIG,
            "subject_id": str(self.version),
            "grade": self.grade,
            "score": self.score,
            "sharpe": self.sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
        }


def grade_config_version(
    *, version: int, sharpe: float, max_drawdown_pct: float
) -> ConfigGradeCard:
    """Grade a config version on absolute Sharpe minus a drawdown penalty."""
    score = round(max(0.0, min(100.0, 60.0 + 28.0 * math.tanh(sharpe) - 1.2 * max_drawdown_pct)), 2)
    return ConfigGradeCard(
        version=version,
        grade=letter_grade(score),
        score=score,
        sharpe=sharpe,
        max_drawdown_pct=max_drawdown_pct,
    )
