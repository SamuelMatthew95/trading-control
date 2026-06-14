"""ReflectionAgent — LLM-based pattern analysis across recent fills into hypotheses."""

from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from api.config import settings
from api.constants import (
    AGENT_REFLECTION,
    REDIS_KEY_LLM_COST,
    REDIS_KEY_LLM_TOKENS,
    REFLECTION_MIN_HYPOTHESES,
    SOURCE_REFLECTION,
    STREAM_AGENT_GRADES,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_NOTIFICATIONS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    LogType,
    Severity,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent, PairedCloseDeduper
from api.services.agents.db_helpers import (
    persist_reflection_record,
    write_agent_log,
)
from api.services.agents.prompts import (
    FALLBACK_REFLECTION,
    REFLECTION_IMPROVE_PROMPT,
    REFLECTION_SYSTEM_PROMPT,
)
from api.services.agents.trade_scorer import (
    aggregate_model_performance,
    compute_learning_metrics,
    compute_mistake_clusters,
    compute_patterns,
    compute_recommendations,
)
from api.services.param_evolution import tunable_parameters

if TYPE_CHECKING:
    from api.services.agents.grade_agent import GradeAgent

# ---------------------------------------------------------------------------
# ReflectionAgent — LLM-based pattern analysis across recent fills
# ---------------------------------------------------------------------------


class ReflectionAgent(MultiStreamAgent):
    """Analyzes recent fills via LLM and generates improvement hypotheses."""

    _state_name = AGENT_REFLECTION

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[
                STREAM_TRADE_PERFORMANCE,
                STREAM_TRADE_COMPLETED,
                STREAM_AGENT_GRADES,
                STREAM_FACTOR_IC_HISTORY,
            ],
            consumer="reflection-agent",
            agent_state=agent_state,
        )
        self._fills = 0
        self._recent_fills: deque[dict[str, Any]] = deque(maxlen=50)
        self._recent_grades: deque[dict[str, Any]] = deque(maxlen=20)
        self._recent_ic: deque[dict[str, Any]] = deque(maxlen=20)
        # The same round-trip close arrives on BOTH trade_performance and
        # trade_completed; analyze it once or total_pnl doubles and the
        # reflection cadence fires early.
        self._close_dedup = PairedCloseDeduper()
        # Holds the GradeAgent eval_buffer reference injected at startup (optional)
        self._grade_agent: GradeAgent | None = None
        # Carry-forward of the previous reflection (summary + hypotheses +
        # winning/losing factors). Fed back into the next prompt so each
        # reflection LEARNS FROM THE LAST — comparing new fills against prior
        # conclusions and refining them — instead of starting from scratch every
        # time. This is what makes the loop cumulative rather than batch-static.
        self._last_reflection: dict[str, Any] = {}

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream in {STREAM_TRADE_PERFORMANCE, STREAM_TRADE_COMPLETED}:
            if self._close_dedup.is_duplicate(data):
                return
            self._fills += 1
            self._recent_fills.append(
                {
                    FieldName.SYMBOL: data.get(FieldName.SYMBOL),
                    FieldName.SIDE: data.get(FieldName.SIDE),
                    FieldName.PNL: data.get(FieldName.PNL),
                    FieldName.PNL_PERCENT: data.get(FieldName.PNL_PERCENT),
                    FieldName.FILL_PRICE: data.get(FieldName.FILL_PRICE),
                    FieldName.FILLED_AT: data.get(FieldName.FILLED_AT),
                    # Decision provenance carried on the fill events so the
                    # per-model reflection summary (_build_prompt) is populated.
                    FieldName.MODEL_USED: data.get(FieldName.MODEL_USED),
                    FieldName.PRIMARY_EDGE: data.get(FieldName.PRIMARY_EDGE),
                }
            )
        elif stream == STREAM_AGENT_GRADES:
            self._recent_grades.append(
                {
                    FieldName.GRADE: data.get(FieldName.GRADE),
                    FieldName.SCORE: data.get(FieldName.SCORE),
                    FieldName.METRICS: data.get(FieldName.METRICS, {}),
                    FieldName.TIMESTAMP: data.get(FieldName.TIMESTAMP),
                }
            )
        elif stream == STREAM_FACTOR_IC_HISTORY:
            self._recent_ic.append(
                {
                    FieldName.FACTOR: data.get(FieldName.FACTOR_NAME),
                    FieldName.IC: data.get(FieldName.IC_SCORE),
                    FieldName.WEIGHT: data.get(FieldName.WEIGHT),
                    FieldName.TIMESTAMP: data.get(FieldName.TIMESTAMP),
                }
            )

        trigger = max(int(settings.REFLECT_EVERY_N_FILLS), 1)
        if self._fills == 0 or self._fills % trigger != 0:
            try:
                from api.redis_client import get_redis as _get_redis_lazy  # noqa: PLC0415

                _redis = await _get_redis_lazy()
                await _write_heartbeat(
                    _redis,
                    self._state_name,
                    f"fill_buffered:{self._fills}/{trigger}",
                    self._fills,
                    extra={FieldName.EXEC_STATUS: "idle:buffering"},
                )
            except Exception:
                log_structured("warning", "reflection_idle_heartbeat_failed", exc_info=True)
            return
        if len(self._recent_fills) < max(int(settings.REFLECT_MIN_FILLS), 1):
            return

        await self._run_reflection()

    async def trigger_reflection(self) -> dict[str, Any]:
        """Force one reflection cycle now, independent of the fill-count trigger.

        The automatic path only reflects every ``REFLECT_EVERY_N_FILLS`` closed
        trades; at low paper-trade volume that can be a long wait, so this gives
        an operator (via ``POST /dashboard/learning/reflect-now``) an on-demand
        way to generate hypotheses → proposals / prompt-evolution. Reflects on
        whatever fills are currently buffered; the published reflection still
        flows to StrategyProposer exactly as the automatic path does.
        """
        await self._run_reflection()
        return {
            FieldName.STATUS: "ok",
            FieldName.FILLS_ANALYZED: self._fills,
            FieldName.BUFFERED_FILLS: len(self._recent_fills),
        }

    async def _run_reflection(self) -> None:
        trace_id = f"reflection_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

        today = datetime.now(timezone.utc).date().isoformat()
        redis = None
        try:
            from api.redis_client import get_redis  # noqa: PLC0415  (circular import)

            redis = await get_redis()
            budget_used = int(await redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)
            if budget_used >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
                log_structured("warning", "reflection_skipped_budget_exceeded", trace_id=trace_id)
                await self.bus.publish(
                    STREAM_NOTIFICATIONS,
                    {
                        FieldName.MSG_ID: str(uuid.uuid4()),
                        FieldName.SOURCE: SOURCE_REFLECTION,
                        FieldName.TYPE: "notification",
                        FieldName.SEVERITY: Severity.WARNING,
                        FieldName.NOTIFICATION_TYPE: "reflection_skipped",
                        FieldName.MESSAGE: "Reflection skipped: daily LLM token budget exceeded",
                        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                    },
                )
                return
        except Exception:
            pass  # Proceed without budget check if Redis unavailable

        prompt = self._build_prompt()
        reflection_data: dict[str, Any] = {}

        try:
            from api.services.llm_router import call_llm_with_system  # noqa: PLC0415

            raw_text, tokens_used, cost_usd = await call_llm_with_system(
                prompt, REFLECTION_SYSTEM_PROMPT, trace_id
            )
            reflection_data = self._parse_llm_response(raw_text)

            if redis is not None:
                await redis.incrby(REDIS_KEY_LLM_TOKENS.format(date=today), tokens_used)
                await redis.incrbyfloat(REDIS_KEY_LLM_COST.format(date=today), cost_usd)

            log_structured(
                "info",
                "reflection_completed",
                trace_id=trace_id,
                hypotheses=len(reflection_data.get(FieldName.HYPOTHESES, [])),
                tokens=tokens_used,
            )
        except Exception:
            log_structured(
                "warning", "reflection_llm_failed_using_fallback", exc_info=True, trace_id=trace_id
            )
            reflection_data = {
                **FALLBACK_REFLECTION,
                FieldName.SUMMARY: f"LLM unavailable after {self._fills} fills.",
            }

        # Evaluator-Optimizer: if the first pass produced too few actionable hypotheses,
        # call the LLM once more with a targeted improve prompt to force richer output.
        hypotheses = reflection_data.get(FieldName.HYPOTHESES, [])
        if len(hypotheses) < REFLECTION_MIN_HYPOTHESES and redis is not None:
            try:
                budget_now = int(await redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)
                if budget_now < settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
                    from api.services.llm_router import call_llm_with_system  # noqa: PLC0415

                    raw_improved, tokens_imp, cost_imp = await call_llm_with_system(
                        prompt, REFLECTION_IMPROVE_PROMPT, trace_id
                    )
                    improved = self._parse_llm_response(raw_improved)
                    if len(improved.get(FieldName.HYPOTHESES, [])) > len(hypotheses):
                        reflection_data = improved
                        await redis.incrby(REDIS_KEY_LLM_TOKENS.format(date=today), tokens_imp)
                        await redis.incrbyfloat(REDIS_KEY_LLM_COST.format(date=today), cost_imp)
                        log_structured(
                            "info",
                            "reflection_refined_by_evaluator_optimizer",
                            trace_id=trace_id,
                            original_hypotheses=len(hypotheses),
                            refined_hypotheses=len(improved.get(FieldName.HYPOTHESES, [])),
                        )
            except Exception:
                log_structured("warning", "reflection_refinement_failed", exc_info=True)

        # Quant layer: compute mistake clusters from trade evaluations
        quant = self._compute_quant_reflection()

        reflection_payload: dict[str, Any] = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.SOURCE: SOURCE_REFLECTION,
            FieldName.TYPE: "reflection_output",
            FieldName.TRACE_ID: trace_id,
            FieldName.FILLS_ANALYZED: self._fills,
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            **reflection_data,
            # Merge quant fields — these override any LLM-generated equivalents
            FieldName.PATTERNS: quant[FieldName.PATTERNS],
            FieldName.MISTAKE_CLUSTERS: quant[FieldName.MISTAKE_CLUSTERS],
            FieldName.RECOMMENDATIONS: quant[FieldName.RECOMMENDATIONS],
            FieldName.TRADES_ANALYZED: quant[FieldName.TRADES_ANALYZED],
            FieldName.WIN_RATE: quant[FieldName.WIN_RATE],
            FieldName.AVG_RETURN: quant[FieldName.AVG_RETURN],
            FieldName.MODEL_PERFORMANCE: quant[FieldName.MODEL_PERFORMANCE],
            FieldName.CONFIDENCE: quant[FieldName.CONFIDENCE],
        }

        # Carry this reflection's conclusions into the next cycle so the loop
        # compounds (compare → refine) instead of restarting each time. Keep a
        # compact subset to bound the next prompt's size.
        self._last_reflection = {
            FieldName.SUMMARY: reflection_data.get(FieldName.SUMMARY, ""),
            FieldName.HYPOTHESES: reflection_data.get(FieldName.HYPOTHESES, []),
            FieldName.WINNING_FACTORS: reflection_data.get(FieldName.WINNING_FACTORS, []),
            FieldName.LOSING_FACTORS: reflection_data.get(FieldName.LOSING_FACTORS, []),
            FieldName.FILLS_ANALYZED: self._fills,
        }

        await self.bus.publish(STREAM_REFLECTION_OUTPUTS, reflection_payload)
        await write_agent_log(trace_id, LogType.REFLECTION, reflection_payload)
        await persist_reflection_record(reflection_payload)
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_REFLECTION,
                FieldName.TYPE: "notification",
                FieldName.SEVERITY: Severity.INFO,
                FieldName.NOTIFICATION_TYPE: "reflection",
                FieldName.MESSAGE: reflection_data.get(FieldName.SUMMARY, "Reflection completed."),
                FieldName.HYPOTHESIS_COUNT: len(reflection_data.get(FieldName.HYPOTHESES, [])),
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )

        # Write heartbeat so dashboard shows REFLECTION_AGENT as ACTIVE
        if redis is not None:
            try:
                await _write_heartbeat(
                    redis,
                    self._state_name,
                    f"reflection fills={self._fills} hypotheses={len(reflection_data.get(FieldName.HYPOTHESES, []))}",
                    self._fills,
                )
            except Exception:
                log_structured("warning", "reflection_heartbeat_failed", exc_info=True)

    def _compute_quant_reflection(self) -> dict[str, Any]:
        """Deterministic quant analysis of recent trade evaluations.

        Uses the GradeAgent's eval_buffer if available (injected at startup),
        otherwise falls back to computing from InMemoryStore or recent_fills data.
        """
        evaluations: list[dict[str, Any]] = []

        # Prefer live eval buffer from GradeAgent
        if self._grade_agent is not None:
            evaluations = list(self._grade_agent._eval_buffer)

        # If no evals yet, fall back to in-memory store
        if not evaluations:
            from api.runtime_state import get_runtime_store  # noqa: PLC0415
            from api.runtime_state import is_db_available as _is_db_available  # noqa: PLC0415

            if not _is_db_available():
                evaluations = get_runtime_store().get_trade_evaluations(50)

        if not evaluations:
            # Synthesize minimal evaluations from recent fills as last resort
            for fill in list(self._recent_fills):
                from api.services.agents.trade_scorer import score_trade as _st  # noqa: PLC0415

                try:
                    evaluations.append(_st(fill))
                except Exception:
                    pass

        patterns = compute_patterns(evaluations)
        clusters = compute_mistake_clusters(evaluations)
        recommendations = compute_recommendations(clusters, patterns)
        metrics = compute_learning_metrics(evaluations)

        return {
            FieldName.PATTERNS: patterns,
            FieldName.MISTAKE_CLUSTERS: clusters,
            FieldName.RECOMMENDATIONS: recommendations,
            FieldName.TRADES_ANALYZED: len(evaluations),
            FieldName.WIN_RATE: metrics.get(FieldName.WIN_RATE, 0.0),
            FieldName.AVG_RETURN: metrics.get(FieldName.AVG_RETURN, 0.0),
            # Per-model performance so reflections (and the operator) can see
            # which LLM is actually producing the wins/losses.
            FieldName.MODEL_PERFORMANCE: aggregate_model_performance(evaluations),
            FieldName.CONFIDENCE: round(
                0.5 + min(len(evaluations), 50) / 100.0, 2
            ),  # confidence grows with sample size
        }

    def _build_prompt(self) -> str:
        recent_fills = list(self._recent_fills)[-20:]
        total_pnl = sum(float(f.get(FieldName.PNL) or 0) for f in recent_fills)
        win_rate = (
            sum(1 for f in recent_fills if float(f.get(FieldName.PNL) or 0) > 0) / len(recent_fills)
            if recent_fills
            else 0
        )
        return json.dumps(
            {
                FieldName.FILLS_ANALYZED: len(recent_fills),
                FieldName.TOTAL_PNL: round(total_pnl, 4),
                FieldName.WIN_RATE: round(win_rate, 4),
                FieldName.RECENT_FILLS: recent_fills,
                FieldName.RECENT_GRADES: list(self._recent_grades)[-5:],
                FieldName.RECENT_IC_CHANGES: list(self._recent_ic)[-5:],
                # Per-model win-rate/PnL so the LLM can reason about which model
                # is trading well, not just aggregate outcomes.
                FieldName.MODEL_PERFORMANCE: aggregate_model_performance(recent_fills),
                # The previous reflection's conclusions — the LLM is asked to
                # build on / compare against / refine these rather than restart,
                # so successive reflections compound into better hypotheses.
                FieldName.PRIOR_REFLECTION: self._last_reflection,
                # The auto-tunable parameters (current value + safe bounds) so a
                # 'parameter' hypothesis can name a CONCRETE, in-bounds change —
                # which is what becomes a real config PR downstream.
                FieldName.TUNABLE_PARAMETERS: tunable_parameters(),
            },
            default=str,
        )

    def _parse_llm_response(self, raw_text: str) -> dict[str, Any]:
        """Parse LLM JSON response; fall back to defaults on parse error."""
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
            if "\n" in cleaned:
                first, rest = cleaned.split("\n", 1)
                if first.strip() in {"json", "JSON", ""}:
                    cleaned = rest
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3].strip()
        try:
            parsed = json.loads(cleaned)
            for key in ("winning_factors", "losing_factors", "hypotheses", "summary"):
                if key not in parsed:
                    parsed[key] = FALLBACK_REFLECTION.get(key, [])
            return parsed
        except json.JSONDecodeError:
            log_structured("warning", "reflection_json_parse_failed", raw=cleaned[:200])
            return dict(FALLBACK_REFLECTION)
