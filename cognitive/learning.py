"""LEARNING ENGINE — attribution + OBSERVATIONS only. It never edits anything.

The strict separation the architecture depends on:

    trades -> grades -> Learning Engine -> OBSERVATIONS -> Proposal Agent -> ...

Learning consumes trade attribution and the grades, and produces *observations*
(insights with a confidence and an evidence bundle). It has NO method that
writes config, weights, prompts, or tools. That firebreak is what keeps the
system non-RL and auditable: the only thing that can turn an observation into a
change is the Proposal Agent, and the only thing that can apply a change is a
merged Git PR judged by the backtest.

This module owns:
  * :func:`attribute` — split realized PnL across the signals that drove a trade.
  * :class:`ImportanceTracker` — a pure fold of attribution into per-signal
    importance METADATA (reconstructable from the stream; never weights).
  * :class:`LearningEngine` — turns that metadata into typed observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.config import WEIGHT_KEYS
from cognitive.events import EventType
from cognitive.grading import grade_agent


@dataclass(frozen=True)
class Attribution:
    """How realized PnL splits across the signals that drove the decision."""

    contributions: dict[str, float]  # signal -> featureᵢ·weightᵢ at decision time
    shares: dict[str, float]  # |contribution| normalized to sum 1
    pnl_attribution: dict[str, float]  # shareᵢ · realized_pnl
    realized_pnl: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.ATTRIBUTION.value,
            "contributions": dict(self.contributions),
            "shares": dict(self.shares),
            "pnl_attribution": dict(self.pnl_attribution),
            "realized_pnl": self.realized_pnl,
        }


def attribute(breakdown: dict[str, float], realized_pnl: float) -> Attribution:
    """Split ``realized_pnl`` across signals by their share of |contribution|."""
    contributions = {key: float(breakdown.get(key, 0.0)) for key in WEIGHT_KEYS}
    total = sum(abs(value) for value in contributions.values())
    if total > 0:
        shares = {key: round(abs(value) / total, 6) for key, value in contributions.items()}
    else:
        shares = dict.fromkeys(WEIGHT_KEYS, 0.0)
    pnl_attribution = {key: round(shares[key] * realized_pnl, 6) for key in WEIGHT_KEYS}
    return Attribution(
        contributions=contributions,
        shares=shares,
        pnl_attribution=pnl_attribution,
        realized_pnl=round(realized_pnl, 6),
    )


@dataclass
class _SignalAcc:
    """Mutable running accumulator for one signal's importance metadata."""

    samples: int = 0
    abs_contribution: float = 0.0
    pnl: float = 0.0
    correct: int = 0


class ImportanceTracker:
    """Running per-signal importance METADATA — a pure fold over the stream.

    Folds (attribution, trade-outcome-sign) pairs into per-signal statistics.
    It is reconstructable entirely from the ATTRIBUTION + TRADE_OUTCOME events on
    the stream, so it is observable, not hidden state — and it deliberately
    produces METADATA, never config weights.
    """

    def __init__(self) -> None:
        self._acc: dict[str, _SignalAcc] = {key: _SignalAcc() for key in WEIGHT_KEYS}

    def update(self, attribution: Attribution, *, outcome_sign: int) -> None:
        """Fold one closed trade. ``outcome_sign`` is sign(realized_pnl)."""
        for key in WEIGHT_KEYS:
            acc = self._acc[key]
            contribution = attribution.contributions[key]
            acc.samples += 1
            acc.abs_contribution += abs(contribution)
            acc.pnl += attribution.pnl_attribution[key]
            contribution_sign = (contribution > 0) - (contribution < 0)
            if contribution_sign != 0 and contribution_sign == outcome_sign:
                acc.correct += 1

    def metadata(self) -> dict[str, dict[str, float]]:
        """Snapshot the per-signal importance metadata (read-only view)."""
        out: dict[str, dict[str, float]] = {}
        for key, acc in self._acc.items():
            out[key] = {
                "samples": acc.samples,
                "avg_abs_contribution": round(acc.abs_contribution / acc.samples, 6)
                if acc.samples
                else 0.0,
                "total_pnl_attribution": round(acc.pnl, 6),
                "correct_rate": round(acc.correct / acc.samples, 6) if acc.samples else 0.0,
            }
        return out


@dataclass(frozen=True)
class Observation:
    """An insight produced by learning. Carries NO instruction — only evidence."""

    observation: str
    confidence: float
    signal: str
    direction: str  # "outperforming" | "underperforming"
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.OBSERVATION.value,
            "observation": self.observation,
            "confidence": self.confidence,
            "signal": self.signal,
            "direction": self.direction,
            "evidence": dict(self.evidence),
        }


class LearningEngine:
    """Turns importance metadata into typed observations. Edits nothing."""

    def __init__(
        self,
        *,
        min_samples: int = 30,
        outperform_rate: float = 0.60,
        underperform_rate: float = 0.40,
    ) -> None:
        self.min_samples = min_samples
        self.outperform_rate = outperform_rate
        self.underperform_rate = underperform_rate

    def observe(self, metadata: dict[str, dict[str, float]]) -> list[Observation]:
        """Emit one observation per signal that has a statistically backed edge."""
        observations: list[Observation] = []
        for signal, stats in metadata.items():
            samples = int(stats.get("samples", 0))
            if samples < self.min_samples:
                continue
            correct_rate = float(stats.get("correct_rate", 0.0))
            contribution = float(stats.get("total_pnl_attribution", 0.0))
            grade = grade_agent(signal, stats, min_samples=self.min_samples).grade
            effect = abs(correct_rate - 0.5) * 2.0
            coverage = min(1.0, samples / (self.min_samples * 3))
            confidence = round(max(0.0, min(1.0, 0.6 * effect + 0.4 * coverage)), 2)
            evidence = {
                "agent_grade": grade,
                "correct_rate": correct_rate,
                "contribution": contribution,
                "sample_size": samples,
            }
            if correct_rate >= self.outperform_rate and contribution >= 0:
                observations.append(
                    Observation(
                        observation=f"{signal}_agent_outperforming",
                        confidence=confidence,
                        signal=signal,
                        direction="outperforming",
                        evidence=evidence,
                    )
                )
            elif correct_rate <= self.underperform_rate or contribution < 0:
                observations.append(
                    Observation(
                        observation=f"{signal}_agent_underperforming",
                        confidence=confidence,
                        signal=signal,
                        direction="underperforming",
                        evidence=evidence,
                    )
                )
        return observations
