"""StrategyProposer — converts reflection hypotheses into typed, backtest-backed proposals."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.constants import (
    AGENT_STRATEGY_PROPOSER,
    REASONING_NODE,
    SOURCE_STRATEGY_PROPOSER,
    STREAM_GITHUB_PRS,
    STREAM_NOTIFICATIONS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    FieldName,
    HypothesisType,
    ProposalType,
    Severity,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent
from api.services.agents.db_helpers import (
    persist_proposal,
    persist_strategy_record,
)
from api.services.agents.prompts import (
    PROMPT_EVOLUTION_PROMPT,
    STRATEGY_PLANNING_PROMPT,
)
from api.services.agents.proposal_guardrails import register_proposal_creation
from api.services.param_evolution import (
    parameter_for_hypothesis,
    tunable_parameters,
    validate_param_change,
)

# ---------------------------------------------------------------------------
# StrategyProposer — converts reflection hypotheses into concrete proposals
# ---------------------------------------------------------------------------


def _is_noop_change(current: Any, proposed: Any) -> bool:
    """True when a proposed parameter value equals the current one (within float
    tolerance) — a no-op change should not open a config PR."""
    if current is None or proposed is None:
        return False
    try:
        return abs(float(current) - float(proposed)) <= 1e-9
    except (TypeError, ValueError):
        return False


async def _acquire_guardrail_redis() -> Any:
    """Best-effort Redis handle for the proposal-creation guardrails.

    Inline import avoids a circular dependency (redis_client transitively
    imports this module). Returns None on any failure so the guardrail fails
    open rather than blocking proposal creation.
    """
    try:
        from api.redis_client import get_redis  # noqa: PLC0415

        return await get_redis()
    except Exception:
        log_structured("warning", "proposal_guardrail_redis_unavailable", exc_info=True)
        return None


class StrategyProposer(MultiStreamAgent):
    """Turns reflection hypotheses into typed proposals that require human approval."""

    _state_name = AGENT_STRATEGY_PROPOSER

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[STREAM_REFLECTION_OUTPUTS],
            consumer="strategy-proposer",
            agent_state=agent_state,
        )

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        hypotheses: list[dict[str, Any]] = data.get(FieldName.HYPOTHESES) or []
        min_confidence = float(settings.HYPOTHESIS_MIN_CONFIDENCE)
        now_iso = datetime.now(timezone.utc).isoformat()

        strong = [
            h for h in hypotheses if float(h.get(FieldName.CONFIDENCE) or 0) >= min_confidence
        ]

        if not strong:
            log_structured(
                "info",
                "strategy_proposer_no_strong_hypotheses",
                total=len(hypotheses),
                threshold=min_confidence,
                reflection_trace_id=data.get(FieldName.TRACE_ID),
            )
            return

        # Agentic planning step: rank strong hypotheses by expected impact before acting
        strong = await self._plan_and_rank(hypotheses, strong, data.get(FieldName.TRACE_ID, ""))

        # Acquire Redis once for the creation guardrails (dedup + daily cap).
        guardrail_redis = await _acquire_guardrail_redis()

        created = 0
        for hypothesis in strong:
            proposal = self._build_proposal(hypothesis, data, now_iso)

            # Guardrail: skip a candidate that duplicates one already emitted
            # today, and stop once the daily cap is reached, so the review queue
            # is not flooded with repeats across reflection cycles.
            if not await register_proposal_creation(guardrail_redis, proposal):
                continue

            if proposal[FieldName.PROPOSAL_TYPE] == ProposalType.CODE_CHANGE:
                await self.bus.publish(
                    STREAM_GITHUB_PRS,
                    {
                        FieldName.MSG_ID: str(uuid.uuid4()),
                        FieldName.SOURCE: SOURCE_STRATEGY_PROPOSER,
                        FieldName.TYPE: "pr_request",
                        FieldName.TITLE: f"Strategy rule proposal: {hypothesis.get(FieldName.DESCRIPTION, '')[:80]}",
                        FieldName.BODY: json.dumps(
                            {
                                FieldName.HYPOTHESIS: hypothesis,
                                FieldName.REFLECTION_TRACE_ID: data.get(FieldName.TRACE_ID),
                                FieldName.FILLS_ANALYZED: data.get(FieldName.FILLS_ANALYZED),
                            },
                            default=str,
                        ),
                        FieldName.TIMESTAMP: now_iso,
                    },
                )

            await self.bus.publish(STREAM_PROPOSALS, proposal)
            await persist_proposal(proposal)
            # Also persist to typed strategies table for learning dashboard
            await persist_strategy_record(
                {
                    FieldName.RULES: proposal.get(FieldName.CONTENT, {}),
                    FieldName.DESCRIPTION: hypothesis.get(FieldName.DESCRIPTION, ""),
                    FieldName.EXPECTED_IMPROVEMENT: float(
                        hypothesis.get(FieldName.CONFIDENCE) or 0
                    ),
                    FieldName.STATUS: "pending",
                    FieldName.REFLECTION_ID: data.get(FieldName.TRACE_ID),
                }
            )
            await self.bus.publish(
                STREAM_NOTIFICATIONS,
                {
                    FieldName.MSG_ID: str(uuid.uuid4()),
                    FieldName.SOURCE: SOURCE_STRATEGY_PROPOSER,
                    FieldName.TYPE: "notification",
                    FieldName.SEVERITY: Severity.INFO,
                    FieldName.NOTIFICATION_TYPE: "proposal",
                    FieldName.MESSAGE: (
                        f"New {proposal[FieldName.PROPOSAL_TYPE]} proposal "
                        f"(confidence={float(hypothesis.get(FieldName.CONFIDENCE) or 0):.0%}): "
                        f"{hypothesis.get(FieldName.DESCRIPTION, '')[:100]}"
                    ),
                    FieldName.TIMESTAMP: now_iso,
                },
            )
            created += 1

        log_structured(
            "info",
            "strategy_proposals_published",
            total_hypotheses=len(hypotheses),
            strong_hypotheses=len(strong),
            proposals_created=created,
            reflection_trace_id=data.get(FieldName.TRACE_ID),
        )

        # Self-evolving prompt: draft an improved reasoning directive from this
        # reflection and propose it. This is the LLM suggesting its own prompt —
        # the missing link that makes the loop self-improving.
        await self._emit_prompt_evolution_proposal(data, now_iso)

        # Write heartbeat so dashboard shows STRATEGY_PROPOSER as ACTIVE
        try:
            from api.redis_client import get_redis as _get_redis  # noqa: PLC0415

            _redis = await _get_redis()
            await _write_heartbeat(
                _redis,
                self._state_name,
                f"proposals created={created} strong={len(strong)}/{len(hypotheses)}",
                created,
            )
        except Exception:
            log_structured("warning", "strategy_proposer_heartbeat_failed", exc_info=True)

    async def _emit_prompt_evolution_proposal(
        self, reflection_data: dict[str, Any], now_iso: str
    ) -> None:
        """Ask the LLM to draft an improved reasoning directive from this
        reflection, and publish it as a PROMPT_EVOLUTION proposal.

        This is the LLM suggesting its OWN prompt — the link that makes the loop
        self-improving. Best-effort: any failure logs and returns without
        disturbing the rest of the proposal cycle.
        """
        if not settings.PROMPT_EVOLUTION_ENABLED:
            return
        trace_id = str(reflection_data.get(FieldName.TRACE_ID) or uuid.uuid4())
        try:
            from api.services.llm_router import call_llm_with_system  # noqa: PLC0415
            from api.services.prompt_store import get_prompt_store  # noqa: PLC0415

            store = get_prompt_store()
            current = (await store.get_active_text(REASONING_NODE) or "") if store else ""

            evo_prompt = json.dumps(
                {
                    FieldName.DIRECTIVE: current,
                    FieldName.WINNING_FACTORS: reflection_data.get(FieldName.WINNING_FACTORS, []),
                    FieldName.LOSING_FACTORS: reflection_data.get(FieldName.LOSING_FACTORS, []),
                    FieldName.SUMMARY: reflection_data.get(FieldName.SUMMARY, ""),
                },
                default=str,
            )
            raw_text, _, _ = await call_llm_with_system(
                evo_prompt, PROMPT_EVOLUTION_PROMPT, trace_id
            )
            parsed = self._parse_evolution_response(raw_text)
        except Exception:
            log_structured(
                "warning", "prompt_evolution_llm_failed", trace_id=trace_id, exc_info=True
            )
            return

        proposed = str(parsed.get(FieldName.DIRECTIVE) or "").strip()
        rationale = str(parsed.get(FieldName.RATIONALE) or "").strip()
        if not proposed or proposed == current.strip():
            log_structured("info", "prompt_evolution_no_change", trace_id=trace_id)
            return

        proposal = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.SOURCE: SOURCE_STRATEGY_PROPOSER,
            FieldName.TYPE: "proposal",
            FieldName.PROPOSAL_TYPE: ProposalType.PROMPT_EVOLUTION,
            FieldName.REQUIRES_APPROVAL: not settings.PROMPT_EVOLUTION_AUTO_APPLY,
            FieldName.REFLECTION_TRACE_ID: reflection_data.get(FieldName.TRACE_ID),
            FieldName.TRACE_ID: trace_id,
            FieldName.TIMESTAMP: now_iso,
            FieldName.CONTENT: {
                FieldName.NODE: REASONING_NODE,
                FieldName.TEXT: proposed,
                FieldName.RATIONALE: rationale,
            },
        }

        # Same creation guardrails as the hypothesis proposals: don't re-emit an
        # identical directive twice in a day, and respect the daily cap.
        guardrail_redis = await _acquire_guardrail_redis()
        if not await register_proposal_creation(guardrail_redis, proposal):
            log_structured("info", "prompt_evolution_skipped_guardrail", trace_id=trace_id)
            return

        await self.bus.publish(STREAM_PROPOSALS, proposal)
        await persist_proposal(proposal)
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_STRATEGY_PROPOSER,
                FieldName.TYPE: "notification",
                FieldName.SEVERITY: Severity.INFO,
                FieldName.NOTIFICATION_TYPE: "proposal",
                FieldName.MESSAGE: f"Prompt-evolution proposal for {REASONING_NODE}: {rationale[:100]}",
                FieldName.TIMESTAMP: now_iso,
            },
        )
        log_structured(
            "info", "prompt_evolution_proposal_published", node=REASONING_NODE, trace_id=trace_id
        )

    @staticmethod
    def _parse_evolution_response(raw_text: str) -> dict[str, Any]:
        """Tolerant JSON parse of the evolution LLM reply (strips md fences)."""
        cleaned = (raw_text or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3]
        try:
            parsed = json.loads(cleaned.strip())
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}

    async def _plan_and_rank(
        self,
        all_hypotheses: list[dict[str, Any]],
        strong: list[dict[str, Any]],
        trace_id: str,
    ) -> list[dict[str, Any]]:
        """Agentic planning step: use LLM to rank strong hypotheses by expected impact.

        This is the Planning pattern — the agent decomposes and prioritises before acting,
        rather than processing hypotheses in arbitrary arrival order.
        Falls back to the original order on any error.
        """
        try:
            from api.services.llm_router import call_llm_with_system  # noqa: PLC0415

            plan_prompt = json.dumps(
                {FieldName.ALL_HYPOTHESES: all_hypotheses, FieldName.STRONG_HYPOTHESES: strong},
                default=str,
            )
            raw_text, _, _ = await call_llm_with_system(
                plan_prompt, STRATEGY_PLANNING_PROMPT, trace_id
            )
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
                if "\n" in cleaned:
                    first, rest = cleaned.split("\n", 1)
                    if first.strip() in {"json", "JSON", ""}:
                        cleaned = rest
                if cleaned.rstrip().endswith("```"):
                    cleaned = cleaned.rstrip()[:-3].strip()
            plan = json.loads(cleaned)
            ranked_indices = plan.get(FieldName.RANKED_INDICES, [])

            if ranked_indices and all(isinstance(i, int) for i in ranked_indices):
                reordered = [strong[i] for i in ranked_indices if 0 <= i < len(strong)]
                ranked_set = set(ranked_indices)
                remainder = [h for i, h in enumerate(strong) if i not in ranked_set]
                result = reordered + remainder
                if result:
                    log_structured(
                        "info",
                        "strategy_proposer_plan_ranked",
                        trace_id=trace_id,
                        count=len(result),
                    )
                    return result
        except Exception:
            log_structured("warning", "strategy_proposer_plan_failed_using_original", exc_info=True)
        return strong

    @staticmethod
    def _attach_concrete_param_change(
        content: dict[str, Any],
        hypothesis: dict[str, Any],
        description: str,
        default_parameter: str | None = None,
    ) -> None:
        """Promote a PARAMETER_CHANGE to a CONCRETE, bounds-valid change when the
        hypothesis names an allowlisted parameter + numeric target.

        This is what lets the applier open a real config PR (a helpful link)
        instead of recording a prose-only no-op: ``_emit_param_change_artifact``
        needs ``parameter`` + ``new_value`` on the content, and the reflection
        hypothesis used to carry neither. A change that isn't allowlisted or is
        out of bounds safely degrades to the description-only review item.

        ``default_parameter`` is the parameter inferred from the hypothesis's
        semantic category (see :func:`parameter_for_hypothesis`); it is used when
        the hypothesis did not name a parameter explicitly, so a value-bearing
        signal_confidence / threshold hypothesis still opens a concrete PR.
        """
        parameter = hypothesis.get(FieldName.PARAMETER) or default_parameter
        proposed_value = hypothesis.get(FieldName.PROPOSED_VALUE)
        if proposed_value is None:
            proposed_value = hypothesis.get(FieldName.NEW_VALUE)
        current = tunable_parameters().get(str(parameter), {}).get("current") if parameter else None
        if (
            parameter
            and validate_param_change(str(parameter), proposed_value) is None
            and not _is_noop_change(current, proposed_value)
        ):
            content[FieldName.PARAMETER] = str(parameter)
            content[FieldName.PREVIOUS_VALUE] = current
            content[FieldName.NEW_VALUE] = proposed_value
            content[FieldName.REASON] = description
            content[FieldName.NOTE] = (
                "Concrete bounds-valid parameter change — routes to a config-only PR."
            )
        else:
            content[FieldName.NOTE] = "Update config parameter via DB — no deploy required."

    def _build_proposal(
        self, hypothesis: dict[str, Any], reflection_data: dict[str, Any], now_iso: str
    ) -> dict[str, Any]:
        hyp_type = str(hypothesis.get(FieldName.TYPE) or "parameter").lower()
        description = str(hypothesis.get(FieldName.DESCRIPTION) or "")
        confidence = float(hypothesis.get(FieldName.CONFIDENCE) or 0)

        base = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.SOURCE: SOURCE_STRATEGY_PROPOSER,
            FieldName.TYPE: "proposal",
            FieldName.REQUIRES_APPROVAL: True,
            FieldName.REFLECTION_TRACE_ID: reflection_data.get(FieldName.TRACE_ID),
            FieldName.TIMESTAMP: now_iso,
            FieldName.CONTENT: {
                FieldName.DESCRIPTION: description,
                FieldName.CONFIDENCE: confidence,
                FieldName.HYPOTHESIS_TYPE: hyp_type,
            },
        }

        if hyp_type == HypothesisType.PARAMETER:
            base[FieldName.PROPOSAL_TYPE] = ProposalType.PARAMETER_CHANGE
            base[FieldName.CONTENT][FieldName.IMPLEMENTATION] = "db_update"
            self._attach_concrete_param_change(base[FieldName.CONTENT], hypothesis, description)
        elif hyp_type == HypothesisType.RULE:
            base[FieldName.PROPOSAL_TYPE] = ProposalType.CODE_CHANGE
            base[FieldName.CONTENT][FieldName.IMPLEMENTATION] = "github_pr"
            base[FieldName.CONTENT][FieldName.NOTE] = "Rule change requires PR review and deploy."
        elif hyp_type == HypothesisType.NEW_AGENT:
            # Propose spawning a challenger agent instance with different config
            base[FieldName.PROPOSAL_TYPE] = ProposalType.NEW_AGENT
            base[FieldName.REQUIRES_APPROVAL] = True
            base[FieldName.CONTENT][FieldName.IMPLEMENTATION] = "challenger_spawn"
            base[FieldName.CONTENT][FieldName.CHALLENGER_CONFIG] = reflection_data.get(
                FieldName.CHALLENGER_CONFIG, {}
            )
            base[FieldName.CONTENT][FieldName.NOTE] = (
                "Spawn a parallel challenger agent with the proposed config changes. "
                "It runs alongside the current agent; retire it via the dashboard."
            )
        elif (mapped_param := parameter_for_hypothesis(hyp_type)) is not None:
            # A hypothesis that names a tunable parameter concern (e.g.
            # "signal confidence is too low") IS a parameter-tuning request, not
            # a code/feature request. Route it to the auto-applyable
            # PARAMETER_CHANGE path instead of re-filing it every cycle as an
            # un-actionable REGIME_ADJUSTMENT GitHub issue — the recurring-issue
            # bug (#324 → #334 → …) where date-keyed dedup reopens the same
            # generic proposal daily with no path to ever auto-resolve. When the
            # hypothesis named no explicit parameter, stamp the mapped one so a
            # concrete, bounds-valid value the LLM proposed still opens a real
            # config PR; otherwise it degrades to a description-only review item
            # (still NOT a GitHub issue).
            base[FieldName.PROPOSAL_TYPE] = ProposalType.PARAMETER_CHANGE
            base[FieldName.CONTENT][FieldName.IMPLEMENTATION] = "db_update"
            self._attach_concrete_param_change(
                base[FieldName.CONTENT], hypothesis, description, default_parameter=mapped_param
            )
        else:
            base[FieldName.PROPOSAL_TYPE] = ProposalType.REGIME_ADJUSTMENT
            base[FieldName.CONTENT][FieldName.REGIME_CONTEXT] = reflection_data.get(
                FieldName.REGIME_EDGE, {}
            )

        return base
