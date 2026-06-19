"""SystemArchitect — a periodic, deterministic high-level proposal synthesizer.

The per-trade reflection loop is good at LOCAL hypotheses ("tighten this stop",
"this signal is too weak"). It does not step back and look at the system as a
whole. The SystemArchitect is that macro view: on an interval it reviews
ACCUMULATED state — per-model net ROI and the recent grade trajectory — and
emits a SMALL number of high-level, *strategic* proposals the reflection loop
misses ("model X loses money — govern it", "grades are structurally low —
rethink the approach, don't just trim weights").

Design choices that keep it honest and cheap:

* **Deterministic, no LLM.** It reads hard numbers (PnL, grades) and applies
  fixed rules, so it never hallucinates, costs no tokens, and works even when
  the LLM provider is rate-limited (the failure mode behind half the "proposals
  are bullshit" reports).
* **Not a stream consumer.** A startup background loop calls :meth:`run_once`
  on ``SYSTEM_ARCHITECT_INTERVAL_SECONDS``. It holds NO always-on Redis
  connection, so it does not count against the Redis pool-sizing invariant
  (``memory-storage.md``).
* **Evidence-tiered, never spammy.** Every proposal carries a Claude-Code-ready
  implementation brief whose evidence is honestly tiered (preliminary / emerging
  / solid) — a thin-sample observation is surfaced as a watch item, not a
  confident command (the issue #341 lesson). It shares the StrategyProposer's
  creation guardrails (daily cap + dedup) AND latches each observation in-process
  so the same finding is not re-proposed every interval.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.constants import (
    SOURCE_SYSTEM_ARCHITECT,
    STREAM_NOTIFICATIONS,
    STREAM_PROPOSALS,
    FieldName,
    ProposalType,
    Severity,
)
from api.events.bus import EventBus
from api.observability import log_structured
from api.runtime_state import get_runtime_store
from api.services.agents.db_helpers import persist_proposal
from api.services.agents.proposal_guardrails import register_proposal_creation
from api.services.agents.trade_scorer import aggregate_model_performance
from api.services.proposal_brief import build_implementation_brief

# Don't flag a model on fewer than this many trades — that is the issue #341
# n=1 noise floor. At/above it the proposal is still evidence-TIERED (a small
# sample reads as "preliminary / watch item"), but below it there is nothing
# worth surfacing at all.
_MIN_MODEL_TRADES = 3
# Sustained-underperformance observation: need at least this many recent grade
# cycles, and a mean score below the threshold, before calling the approach
# structurally mis-fit (a single bad grade is just noise).
_UNDERPERFORMANCE_MIN_GRADES = 5
_UNDERPERFORMANCE_WINDOW = 8
_UNDERPERFORMANCE_SCORE_THRESHOLD = 0.55  # mean grade score (0-1) below this


class SystemArchitect:
    """Deterministically synthesises strategic proposals from accumulated state."""

    name = SOURCE_SYSTEM_ARCHITECT

    def __init__(
        self,
        bus: EventBus,
        redis_client: Any = None,
        *,
        grade_agent: Any = None,
    ) -> None:
        self.bus = bus
        # Used only for the creation guardrails (daily cap + dedup); None → the
        # guardrail fails open, exactly like the StrategyProposer path.
        self._redis = redis_client
        # Optional: the live GradeAgent, whose in-memory buffers are the freshest
        # source of trade evaluations + the grade trajectory (same buffers the
        # ReflectionAgent reads). Falls back to the runtime store when absent.
        self._grade_agent = grade_agent
        # In-process latch: each distinct observation is proposed at most once per
        # process so a persistent condition is not re-filed every interval.
        self._emitted: set[str] = set()

    async def run_once(self) -> int:
        """Run one synthesis pass. Returns the number of proposals emitted.

        Never raises into the caller (a background loop) — any failure is logged
        and the pass yields zero.
        """
        if not settings.SYSTEM_ARCHITECT_ENABLED:
            return 0
        try:
            observations = self._gather_observations()
        except Exception:
            log_structured("warning", "system_architect_gather_failed", exc_info=True)
            return 0

        emitted = 0
        for proposal, signature in observations:
            if signature in self._emitted:
                continue
            try:
                if not await register_proposal_creation(self._redis, proposal):
                    continue  # daily cap / dedup — retry a later interval, don't latch
                await self._publish(proposal)
            except Exception:
                log_structured(
                    "warning", "system_architect_publish_failed", signature=signature, exc_info=True
                )
                continue
            self._emitted.add(signature)
            emitted += 1

        log_structured(
            "info", "system_architect_pass", observations=len(observations), emitted=emitted
        )
        return emitted

    # ------------------------------------------------------------------
    # Observations — each returns (proposal, stable signature) or None.
    # ------------------------------------------------------------------

    def _gather_observations(self) -> list[tuple[dict[str, Any], str]]:
        observations: list[tuple[dict[str, Any], str]] = []
        for builder in (self._model_governance_observation, self._underperformance_observation):
            result = builder()
            if result is not None:
                observations.append(result)
        return observations

    def _model_governance_observation(self) -> tuple[dict[str, Any], str] | None:
        """The evidence-backed version of issue #341: a model that is net-negative
        over enough trades is surfaced as a model-governance proposal — with the
        disable / down-weight / fallback mechanism menu — instead of an n=1 guess."""
        rows = aggregate_model_performance(self._recent_evaluations())
        candidates = [
            row
            for row in rows
            if _int(row.get(FieldName.TRADE_COUNT)) >= _MIN_MODEL_TRADES
            and _float(row.get(FieldName.NET_ROI)) < 0
        ]
        if not candidates:
            return None
        worst = min(candidates, key=lambda row: _float(row.get(FieldName.NET_ROI)))
        model = str(worst.get(FieldName.MODEL_USED) or "unknown")
        trades = _int(worst.get(FieldName.TRADE_COUNT))
        net_roi = _float(worst.get(FieldName.NET_ROI))
        win_rate = worst.get(FieldName.WIN_RATE)
        description = (
            f"LLM model '{model}' is net-negative over the recent window: net ROI "
            f"{net_roi:.4f} (PnL minus decision cost) across {trades} trades. Decide whether "
            "to down-weight it, route to a fallback model, or disable it — overall or in the "
            "regimes where it loses most."
        )
        evidence = {
            FieldName.SAMPLE_SIZE: trades,
            FieldName.WIN_RATE: win_rate,
            FieldName.TOTAL_PNL: worst.get(FieldName.TOTAL_PNL),
            FieldName.MODEL_PERFORMANCE: [worst],
        }
        content = {
            FieldName.DESCRIPTION: description,
            FieldName.REASON: f"net ROI {net_roi:.4f} over {trades} trades",
        }
        proposal = self._make_proposal(
            ProposalType.CODE_CHANGE, description, content, evidence, category="model governance"
        )
        return proposal, f"model_governance:{model}"

    def _underperformance_observation(self) -> tuple[dict[str, Any], str] | None:
        """Sustained low grades are a STRUCTURAL signal: rather than only trimming
        weights (what GradeAgent already does), propose a design-level rethink — a
        regime filter, a strategy rotation, or a new challenger."""
        scores = self._recent_grade_scores()
        if len(scores) < _UNDERPERFORMANCE_MIN_GRADES:
            return None
        recent = scores[-_UNDERPERFORMANCE_WINDOW:]
        mean = sum(recent) / len(recent)
        if mean >= _UNDERPERFORMANCE_SCORE_THRESHOLD:
            return None
        description = (
            f"Agent grades have been sustained low — mean score {mean:.0%} over the last "
            f"{len(recent)} grading cycles. The current approach may be structurally mis-fit to "
            "the regime; consider a regime filter, a strategy rotation, or spawning a new "
            "challenger rather than only trimming signal weights."
        )
        # Sample is grading cycles, not win rate — the mean grade lives in the
        # description so the brief never mislabels it.
        evidence = {FieldName.SAMPLE_SIZE: len(recent)}
        content = {
            FieldName.DESCRIPTION: description,
            FieldName.REASON: f"mean grade score {mean:.0%} over {len(recent)} grading cycles",
        }
        proposal = self._make_proposal(
            ProposalType.CODE_CHANGE, description, content, evidence, category="strategy regime fit"
        )
        return proposal, "structural_underperformance"

    # ------------------------------------------------------------------
    # State sources + proposal assembly
    # ------------------------------------------------------------------

    def _recent_evaluations(self) -> list[dict[str, Any]]:
        """Recent trade evaluations — the GradeAgent buffer when injected, else the
        runtime store (the memory-mode source of truth)."""
        buffer = getattr(self._grade_agent, "_eval_buffer", None)
        if buffer:
            return list(buffer)
        return get_runtime_store().get_trade_evaluations(200)

    def _recent_grade_scores(self) -> list[float]:
        """Recent composite grade scores (0-1), oldest first. Prefers the
        GradeAgent's trajectory history (works in both DB and memory mode)."""
        history = getattr(self._grade_agent, "_grade_score_history", None)
        if history:
            return [_float(score) for score, _vector in history]
        scores: list[float] = []
        for grade in reversed(get_runtime_store().get_grades(_UNDERPERFORMANCE_WINDOW)):
            pct = grade.get(FieldName.SCORE_PCT)
            if pct is not None:
                scores.append(_float(pct) / 100.0)
        return scores

    def _make_proposal(
        self,
        proposal_type: str,
        summary: str,
        content: dict[str, Any],
        evidence: dict[str, Any],
        *,
        category: str,
    ) -> dict[str, Any]:
        content[FieldName.EVIDENCE] = evidence
        content[FieldName.BRIEF] = build_implementation_brief(
            proposal_type=str(proposal_type),
            summary=summary,
            content=content,
            evidence=evidence,
            category=category,
        )
        return {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.SOURCE: SOURCE_SYSTEM_ARCHITECT,
            FieldName.TYPE: "proposal",
            FieldName.PROPOSAL_TYPE: proposal_type,
            FieldName.REQUIRES_APPROVAL: True,
            FieldName.CONTENT: content,
            FieldName.TRACE_ID: f"architect_{uuid.uuid4().hex[:8]}",
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }

    async def _publish(self, proposal: dict[str, Any]) -> None:
        await self.bus.publish(STREAM_PROPOSALS, proposal)
        # Persist so the dashboard queue (which reads the persisted store, not the
        # stream) shows it — mirroring StrategyProposer / GradeAgent.
        await persist_proposal(proposal)
        content = proposal.get(FieldName.CONTENT) or {}
        message = str(content.get(FieldName.DESCRIPTION) or "strategic proposal")[:120]
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_SYSTEM_ARCHITECT,
                FieldName.TYPE: "notification",
                FieldName.SEVERITY: Severity.INFO,
                FieldName.NOTIFICATION_TYPE: "proposal",
                FieldName.MESSAGE: f"System Architect: {message}",
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
