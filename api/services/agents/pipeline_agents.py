"""Pipeline agents: GradeAgent, ICUpdater, ReflectionAgent, StrategyProposer, NotificationAgent.

Each agent class focuses exclusively on its domain logic.
Math lives in ``scoring``, prompts in ``prompts``, DB writes in ``db_helpers``,
and the poll loop in ``base``.
"""

from __future__ import annotations

import json
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_CHALLENGER,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_NOTIFICATION,
    AGENT_REFLECTION,
    AGENT_STRATEGY_PROPOSER,
    LLM_CALL_DELAY_MS,
    LLM_DELAY_ADJUSTMENT_STEP_MS,
    LLM_DELAY_MAX_MS,
    LLM_RATE_LIMIT_GRADE_THRESHOLD,
    NOTIFICATION_DEDUP_TTL_SECONDS,
    NOTIFICATIONS_STREAM_MAXLEN,
    REDIS_IC_WEIGHTS_TTL_SECONDS,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_LLM_COST,
    REDIS_KEY_LLM_TOKENS,
    REDIS_KEY_NOTIFICATION_DEDUP,
    REFLECTION_MIN_HYPOTHESES,
    SOURCE_GRADE,
    SOURCE_IC_UPDATER,
    SOURCE_NOTIFICATION,
    SOURCE_REFLECTION,
    SOURCE_STRATEGY_PROPOSER,
    STREAM_AGENT_GRADES,
    STREAM_AGENT_LOGS,
    STREAM_DECISIONS,
    STREAM_EXECUTIONS,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_GITHUB_PRS,
    STREAM_MARKET_EVENTS,
    STREAM_MARKET_TICKS,
    STREAM_NOTIFICATIONS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    Grade,
    HypothesisType,
    LogType,
    OrderSide,
    ProposalType,
    Severity,
)
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import is_db_available
from api.schema_version import DB_SCHEMA_VERSION
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent
from api.services.agents.db_helpers import (
    persist_factor_ic,
    persist_proposal,
    persist_reflection_record,
    persist_strategy_record,
    persist_trade_evaluation,
    write_agent_log,
    write_grade_to_db,
)
from api.services.agents.grade_analytics import (
    build_self_correction,
    is_actionable,
)
from api.services.agents.notification_payloads import (
    build_trade_notification,
)
from api.services.agents.prompts import (
    FALLBACK_REFLECTION,
    REFLECTION_IMPROVE_PROMPT,
    REFLECTION_SYSTEM_PROMPT,
    STRATEGY_PLANNING_PROMPT,
)
from api.services.agents.scoring import (
    GRADE_SEVERITY,
    compute_weighted_score,
    normalize_cost_eff,
    normalize_ic,
    score_to_grade,
    spearman_correlation,
)
from api.services.agents.trade_scorer import (
    aggregate_model_performance,
    compute_learning_metrics,
    compute_mistake_clusters,
    compute_patterns,
    compute_recommendations,
    score_trade,
)
from api.services.llm_metrics import llm_metrics as _llm_metrics
from api.services.redis_store import get_redis_store as _get_redis_store
from api.services.tool_registry import get_tool_registry

# ---------------------------------------------------------------------------
# GradeAgent — real 4-dimension performance scoring
# ---------------------------------------------------------------------------


class GradeAgent(MultiStreamAgent):
    """Grades agent performance across 4 weighted dimensions every N fills.

    Score = accuracy×0.35 + IC×0.30 + cost_efficiency×0.20 + latency×0.15
    """

    _state_name = AGENT_GRADE

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[
                STREAM_EXECUTIONS,
                STREAM_TRADE_PERFORMANCE,
                STREAM_TRADE_COMPLETED,
                # Consumed only to learn which tools informed each decision, so a
                # completed trade's realized PnL can be attributed back to those
                # tools (tool grading). No grade cycle is triggered by decisions.
                STREAM_DECISIONS,
            ],
            consumer="grade-agent",
            agent_state=agent_state,
        )
        self._fills = 0
        self._pnl_buffer: deque[float] = deque(maxlen=100)
        self._confidence_buffer: deque[float] = deque(maxlen=100)
        self._consecutive_low_grades = 0
        # Per-trade evaluation buffer for ReflectionAgent to consume
        self._eval_buffer: deque[dict] = deque(maxlen=200)
        # Tracks the rate_limited_count seen at the last delay adjustment so we
        # only ratchet up when *new* 429s appear, not just because old ones are
        # still inside the 5-minute sliding window.
        self._last_rl_count_at_adjustment: int = 0
        # Rolling (composite_score, dimension_vector) history feeding the
        # self-correction analytics — grade anomaly detection + trajectory.
        self._grade_score_history: deque[tuple[float, dict[str, Any]]] = deque(maxlen=50)
        # Edge-trigger latch: alert once when the diagnostic enters a drop/decay
        # state, stay quiet until it recovers (avoids per-cycle notification spam).
        self._self_correction_active: bool = False
        # Last emitted tool-governance suggestion set (";"-joined tool:action).
        # Edge-triggers the tool-governance proposal so an unchanged set is not
        # re-proposed every grading cycle.
        self._last_tool_governance_key: str | None = None
        # trace_id -> tool names used in that decision, captured from the
        # decisions stream. When the matching trade closes we attribute its
        # realized PnL back to these tools so tool alpha is OUTCOME-driven
        # (not just decision-time latency/reliability). Bounded so a long run
        # cannot grow it without limit.
        self._trace_tools: OrderedDict[str, list[str]] = OrderedDict()

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == STREAM_TRADE_COMPLETED:
            self._pnl_buffer.append(float(data.get(FieldName.PNL) or 0.0))
            self._fills += 1
            await self._score_and_persist_trade(data)
        elif stream == STREAM_TRADE_PERFORMANCE:
            self._pnl_buffer.append(float(data.get(FieldName.PNL) or 0.0))
            self._fills += 1
            await self._score_and_persist_trade(data)
        elif stream == STREAM_EXECUTIONS:
            self._confidence_buffer.append(float(data.get(FieldName.CONFIDENCE) or 0.5))
        elif stream == STREAM_DECISIONS:
            # Cache the tools used so a later trade can be graded against them.
            self._remember_decision_tools(data)
            return  # decisions never trigger a grade cycle

        trigger = max(int(settings.GRADE_EVERY_N_FILLS), 1)
        if self._fills == 0 or self._fills % trigger != 0:
            # Write idle heartbeat so dashboard shows GradeAgent as active even
            # between grading cycles.
            try:
                from api.redis_client import get_redis as _get_redis  # noqa: PLC0415

                _redis = await _get_redis()
                await _write_heartbeat(
                    _redis,
                    self._state_name,
                    f"fill_buffered:{self._fills}/{trigger}",
                    self._fills,
                    extra={FieldName.EXEC_STATUS: "idle:buffering"},
                )
            except Exception:
                log_structured("warning", "grade_idle_heartbeat_failed", exc_info=True)
            return

        await self._compute_and_publish_grade()

    async def _score_and_persist_trade(self, data: dict[str, Any]) -> None:
        """Score one completed trade deterministically and persist the evaluation."""
        try:
            evaluation = score_trade(data)
            self._eval_buffer.append(evaluation)
            await persist_trade_evaluation(evaluation)
            log_structured(
                "debug",
                "trade_scored",
                trade_id=evaluation.get(FieldName.TRADE_EVAL_ID),
                grade=evaluation.get(FieldName.GRADE),
                overall_score=evaluation.get(FieldName.OVERALL_SCORE),
            )
        except Exception:
            log_structured("warning", "trade_score_failed", exc_info=True)

        # Tool grading — attribute this trade's realized PnL back to the tools
        # that informed the decision behind it, closing the loop from outcome to
        # tool alpha. This is what makes suggest_tool_changes (negative-alpha →
        # disable) and the tool-governance proposal driven by real outcomes.
        self._attribute_pnl_to_tools(data)

    def _remember_decision_tools(self, data: dict[str, Any]) -> None:
        """Cache trace_id -> tool names from a decision event (bounded LRU)."""
        trace_id = data.get(FieldName.TRACE_ID)
        if not trace_id:
            return
        tools = data.get(FieldName.TOOLS_USED) or []
        names = [
            t.get(FieldName.NAME) for t in tools if isinstance(t, dict) and t.get(FieldName.NAME)
        ]
        if not names:
            return
        self._trace_tools[trace_id] = names
        self._trace_tools.move_to_end(trace_id)
        while len(self._trace_tools) > 500:  # bound the map on long runs
            self._trace_tools.popitem(last=False)

    def _attribute_pnl_to_tools(self, data: dict[str, Any]) -> None:
        """Fold a completed trade's realized PnL into the alpha of each tool that
        informed its decision. Pops the trace so the paired trade_completed /
        trade_performance events for one trade attribute exactly once."""
        trace_id = data.get(FieldName.TRACE_ID)
        if not trace_id:
            return
        names = self._trace_tools.pop(trace_id, None)
        if not names:
            return
        pnl = data.get(FieldName.PNL)
        if pnl is None:
            return
        try:
            registry = get_tool_registry()
            for name in names:
                registry.record_call(name, latency_ms=0.0, success=True, realized_pnl=float(pnl))
        except Exception:
            log_structured("warning", "tool_pnl_attribution_failed", exc_info=True)

    async def _compute_and_publish_grade(self) -> None:
        trace_id = f"grade_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        lookback_n = int(settings.GRADE_LOOKBACK_N)

        try:
            accuracy = self._win_rate(lookback_n)
            ic = await self._information_coefficient(lookback_n)
            cost_eff = await self._cost_efficiency(lookback_n)
            latency = await self._latency_score()
            llm_health, llm_snap = self._llm_health_score()
        except Exception:
            log_structured("error", "grade_metric_computation_failed", exc_info=True)
            return

        ic_norm = normalize_ic(ic)
        cost_norm = normalize_cost_eff(cost_eff)
        score = compute_weighted_score(
            accuracy,
            ic_norm,
            cost_norm,
            latency,
            w_accuracy=float(settings.GRADE_WEIGHT_ACCURACY),
            w_ic=float(settings.GRADE_WEIGHT_IC),
            w_cost=float(settings.GRADE_WEIGHT_COST),
            w_latency=float(settings.GRADE_WEIGHT_LATENCY),
        )
        grade = score_to_grade(score)

        dimension_vector = {
            FieldName.ACCURACY: round(accuracy, 4),
            FieldName.IC_NORMALIZED: round(ic_norm, 4),
            FieldName.COST_NORMALIZED: round(cost_norm, 4),
            FieldName.LATENCY_SCORE: round(latency, 4),
        }
        self_correction = self._self_correction(score, dimension_vector)

        payload = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.TYPE: "agent_grade",
            FieldName.SOURCE: SOURCE_GRADE,
            FieldName.AGENT: AGENT_GRADE,
            "agent_name": AGENT_GRADE,
            FieldName.TRACE_ID: trace_id,
            "grade": grade,
            FieldName.SCORE: score,
            FieldName.CONFIDENCE_SCORE: round(score * 100, 2),
            FieldName.REASONING: (
                f"accuracy={accuracy:.3f}, ic={ic:.3f}, cost_eff={cost_eff:.3f}, "
                f"latency={latency:.3f}, llm_health={llm_health:.3f}"
            ),
            FieldName.SCORE_PCT: round(score * 100, 1),
            FieldName.METRICS: {
                FieldName.ACCURACY: round(accuracy, 4),
                FieldName.IC: round(ic, 4),
                FieldName.IC_NORMALIZED: round(ic_norm, 4),
                FieldName.COST_EFFICIENCY: round(cost_eff, 4),
                FieldName.COST_NORMALIZED: round(cost_norm, 4),
                FieldName.LATENCY_SCORE: round(latency, 4),
                FieldName.LLM_HEALTH_SCORE: llm_health,
                FieldName.LLM_RATE_LIMITED: llm_snap.get(FieldName.RATE_LIMITED_COUNT, 0),
                FieldName.LLM_TIMEOUT_COUNT: llm_snap.get(FieldName.TIMEOUT_COUNT, 0),
                FieldName.LLM_SUCCESS_RATE_PCT: round(
                    llm_snap.get(FieldName.SUCCESS_RATE_PCT, 100.0), 1
                ),
                FieldName.LLM_EFFECTIVE_DELAY_MS: llm_snap.get(
                    FieldName.EFFECTIVE_DELAY_MS, LLM_CALL_DELAY_MS
                ),
            },
            FieldName.FILLS_GRADED: self._fills,
            FieldName.SELF_CORRECTION: self_correction,
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }

        await self.bus.publish(STREAM_AGENT_GRADES, payload)
        log_structured(
            "info",
            "grade_computed",
            grade=grade,
            score=score,
            fills=self._fills,
            ic=ic,
            llm_health=llm_health,
            llm_rate_limited=llm_snap.get(FieldName.RATE_LIMITED_COUNT, 0),
        )

        await write_agent_log(trace_id, LogType.GRADE, payload)
        await write_grade_to_db(
            trace_id,
            payload[FieldName.SCORE_PCT],
            payload[FieldName.METRICS],
            self_correction=self_correction,
        )
        await self._take_grade_action(grade, payload)
        await self._emit_self_correction_alert(self_correction, trace_id)
        await self._emit_tool_governance(trace_id)
        await self._adjust_llm_call_rate(llm_snap)
        await self._backfill_grade_to_lifecycle(grade, payload, trace_id)

        # Write heartbeat with last grade score for dashboard display
        try:
            from api.redis_client import get_redis as _get_redis  # noqa: PLC0415

            _redis = await _get_redis()
            await _write_heartbeat(
                _redis,
                self._state_name,
                f"grade={grade} score={payload[FieldName.SCORE_PCT]}",
                self._fills,
                extra={FieldName.LAST_GRADE_SCORE: payload[FieldName.SCORE_PCT]},
            )
        except Exception:
            log_structured("warning", "grade_heartbeat_failed", exc_info=True)

    async def _backfill_grade_to_lifecycle(
        self, grade: str, payload: dict[str, Any], trace_id: str
    ) -> None:
        """Back-fill grade onto the most recent unfilled trade_lifecycle row. DB mode only."""
        if not is_db_available():
            return
        try:
            from api.database import AsyncSessionFactory  # noqa: PLC0415
            from api.services.agents.db_helpers import upsert_trade_lifecycle  # noqa: PLC0415

            grade_label = (
                f"Grade {grade}: accuracy={payload[FieldName.METRICS][FieldName.ACCURACY]:.0%} "
                f"IC={payload[FieldName.METRICS][FieldName.IC]:+.3f}"
            )
            async with AsyncSessionFactory() as _sess:
                row = await _sess.execute(
                    text("""
                        SELECT execution_trace_id FROM trade_lifecycle
                        WHERE status = 'filled' AND grade IS NULL
                        ORDER BY created_at DESC LIMIT 1
                    """)
                )
                latest = row.first()
            if latest and latest[0]:
                await upsert_trade_lifecycle(
                    execution_trace_id=latest[0],
                    symbol="",  # already set — upsert won't overwrite
                    side=OrderSide.BUY,
                    grade_trace_id=trace_id,
                    grade=grade,
                    grade_score=payload[FieldName.SCORE_PCT],
                    grade_label=grade_label,
                    status="graded",
                    graded_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            log_structured("warning", "grade_lifecycle_update_failed", exc_info=True)

    def _self_correction(self, score: float, dimension_vector: dict[str, Any]) -> dict[str, Any]:
        """Build the self-correction diagnostic, then fold this cycle into history.

        The current grade is compared against the *prior* cycles (so it is never
        part of its own baseline); the trajectory uses the full recent window
        including this cycle.
        """
        baseline_scores = [s for s, _ in self._grade_score_history]
        baseline_vectors = [v for _, v in self._grade_score_history]
        recent_scores = [*baseline_scores, score]
        diagnostic = build_self_correction(
            baseline_scores,
            score,
            baseline_vectors,
            dimension_vector,
            recent_scores,
        )
        self._grade_score_history.append((score, dimension_vector))
        return diagnostic

    async def _emit_self_correction_alert(
        self, self_correction: dict[str, Any], trace_id: str
    ) -> None:
        """Edge-triggered alert on a grade drop or decaying trend.

        Fires a single notification when the diagnostic first becomes actionable
        (entering drop/decay) and stays silent until it recovers — no per-cycle
        spam. Surfaces a degrading trajectory *before* the hard D/F gates in
        ``_take_grade_action`` retire the agent. The full diagnostic always
        rides along in the grade payload regardless; this is only the push
        alert. Positive spikes are never paged on.
        """
        if not is_actionable(self_correction):
            # Recovered (or never tripped) — reset so the next entry re-fires.
            self._self_correction_active = False
            return
        if self._self_correction_active:
            # Already alerted for this episode — don't re-page every cycle.
            return
        self._self_correction_active = True
        log_structured(
            "warning",
            "grade_self_correction",
            anomaly=self_correction[FieldName.ANOMALY_DETECTED],
            direction=self_correction[FieldName.DIRECTION],
            z_score=self_correction[FieldName.Z_SCORE],
            trace_id=trace_id,
        )
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_GRADE,
                FieldName.TYPE: "notification",
                FieldName.SEVERITY: Severity.WARNING,
                FieldName.NOTIFICATION_TYPE: "grade_self_correction",
                FieldName.MESSAGE: self_correction[FieldName.MESSAGE],
                FieldName.PAYLOAD: {
                    FieldName.SELF_CORRECTION: self_correction,
                    FieldName.TRACE_ID: trace_id,
                },
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _emit_tool_governance(self, trace_id: str) -> None:
        """Turn the ToolRegistry's read-only advice into an actionable proposal.

        The registry already scores each tool's alpha + reliability from live
        reasoning telemetry, but the only consumer was a passive dashboard
        panel — the loop never closed ("it's not automating"). Each grade cycle
        we surface the actionable suggestions (disable / review) as a single
        human-approval proposal + notification, edge-triggered so an unchanged
        set does not re-propose every cycle. The full suggestion list (incl.
        the ``prioritize`` hint) rides along in the proposal content.
        """
        try:
            suggestions = get_tool_registry().suggest_tool_changes()
        except Exception:
            log_structured("warning", "tool_governance_suggest_failed", exc_info=True)
            return

        # 'prioritize' alone is informational; only disable/review are actionable.
        actionable = [s for s in suggestions if s.action in ("disable", "review")]
        if not actionable:
            self._last_tool_governance_key = None
            return

        key = ";".join(f"{s.tool}:{s.action}" for s in actionable)
        if key == self._last_tool_governance_key:
            return  # unchanged set — already proposed this episode
        self._last_tool_governance_key = key

        serialized = [
            {
                FieldName.TOOL: s.tool,
                FieldName.ACTION: s.action,
                FieldName.SEVERITY: s.severity,
                FieldName.REASON: s.reason,
            }
            for s in suggestions
        ]
        # Full per-tool attribution (alpha / failure / usage), ranked, so the
        # proposal shows HOW each tool is performing — the operator can act on a
        # disable, or use the gaps to decide which new tools to add/enable.
        attribution = [
            {
                FieldName.TOOL: t.name,
                FieldName.ALPHA: round(t.alpha_score, 6),
                FieldName.FAILURE_RATE: round(t.failure_rate, 4),
                FieldName.CALL_COUNT: t.call_count,
                FieldName.ENABLED: t.enabled,
            }
            for t in get_tool_registry().attribution()
        ]
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.bus.publish(
            STREAM_PROPOSALS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_GRADE,
                FieldName.TYPE: "proposal",
                FieldName.PROPOSAL_TYPE: ProposalType.TOOL_GOVERNANCE,
                FieldName.REQUIRES_APPROVAL: True,
                FieldName.CONTENT: {
                    FieldName.SUGGESTIONS: serialized,
                    FieldName.ATTRIBUTION: attribution,
                    FieldName.REASON: (
                        f"{len(actionable)} tool-governance action(s) from live "
                        "reasoning telemetry (alpha / reliability / usage)"
                    ),
                },
                FieldName.TRACE_ID: trace_id,
                FieldName.TIMESTAMP: now_iso,
            },
        )
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_GRADE,
                FieldName.TYPE: "notification",
                FieldName.SEVERITY: Severity.INFO,
                FieldName.NOTIFICATION_TYPE: "tool_governance",
                FieldName.MESSAGE: f"Tool governance suggests: {key}",
                FieldName.TIMESTAMP: now_iso,
            },
        )
        log_structured(
            "info", "tool_governance_proposal_published", suggestions=key, trace_id=trace_id
        )

    def _win_rate(self, lookback_n: int) -> float:
        recent = list(self._pnl_buffer)[-lookback_n:]
        if not recent:
            return 0.5
        return sum(1 for pnl in recent if pnl > 0) / len(recent)

    async def _information_coefficient(self, lookback_n: int) -> float:
        """Spearman correlation between agent confidence and realized returns."""
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT ar.confidence, tp.pnl
                            FROM agent_runs ar
                            JOIN orders o ON o.trace_id = ar.trace_id
                            JOIN trade_performance tp ON tp.order_id = o.id
                            ORDER BY ar.created_at DESC
                            LIMIT :n
                        """),
                        {FieldName.N: lookback_n},
                    )
                    rows = result.all()
                    if len(rows) >= 3:
                        confs = [float(r[0]) for r in rows if r[0] is not None]
                        pnls = [float(r[1]) for r in rows if r[1] is not None]
                        if len(confs) >= 3:
                            return spearman_correlation(confs, pnls)
            except Exception:
                log_structured("warning", "ic_db_query_failed_using_buffer", exc_info=True)

        confs = list(self._confidence_buffer)[-lookback_n:]
        pnls = list(self._pnl_buffer)[-lookback_n:]
        paired = list(zip(confs, pnls, strict=False))
        if len(paired) < 3:
            return 0.0
        xs, ys = zip(*paired, strict=False)
        return spearman_correlation(list(xs), list(ys))

    async def _cost_efficiency(self, lookback_n: int) -> float:
        """Total PnL divided by total LLM cost for last N fills."""
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT COALESCE(SUM(cost_usd), 0)
                            FROM (SELECT cost_usd FROM agent_runs ORDER BY created_at DESC LIMIT :n) sub
                        """),
                        {FieldName.N: lookback_n},
                    )
                    total_cost = float(result.scalar() or 0.0)
            except Exception:
                total_cost = 0.0
        else:
            total_cost = 0.0

        total_pnl = sum(list(self._pnl_buffer)[-lookback_n:])
        if total_cost < 0.0001:
            return total_pnl * 0.1
        return total_pnl / total_cost

    async def _latency_score(self) -> float:
        """1 - (p95_latency_ms / timeout_ms). Higher score means lower latency."""
        timeout_ms = float(settings.LLM_TIMEOUT_SECONDS) * 1000.0
        if not is_db_available():
            return 0.8
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
                        FROM agent_runs
                        WHERE latency_ms > 0 AND created_at > NOW() - INTERVAL '7 days'
                    """)
                )
                p95 = result.scalar()
                if p95 is None:
                    return 0.8
                return max(0.0, 1.0 - (float(p95) / timeout_ms))
        except Exception:
            return 0.8

    def _llm_health_score(self) -> tuple[float, dict[str, Any]]:
        """Read live LLM metrics and return (health_score [0,1], snapshot).

        Health degrades with rate limits and timeouts on top of the raw
        success rate, so even a high success_rate is penalised when the
        window contains many blocked calls.
        """
        snap = _llm_metrics.snapshot()
        success_rate = snap.get(FieldName.SUCCESS_RATE_PCT, 100.0) / 100.0
        rate_limited = snap.get(FieldName.RATE_LIMITED_COUNT, 0)
        timeout_count = snap.get(FieldName.TIMEOUT_COUNT, 0)
        penalty = min(1.0, rate_limited * 0.10 + timeout_count * 0.15)
        health = round(max(0.0, success_rate - penalty), 4)
        return health, snap

    async def _adjust_llm_call_rate(self, llm_snap: dict) -> None:
        """Raise the inter-call delay only when new rate-limited calls appear.

        Called every grading cycle. The 5-minute sliding window can keep a
        burst above the threshold for minutes after the burst ends, so we gate
        on whether rate_limited_count has *increased* since the last time we
        adjusted — preventing repeated ratcheting from a single burst.
        """
        rate_limited = llm_snap.get(FieldName.RATE_LIMITED_COUNT, 0)
        if rate_limited < LLM_RATE_LIMIT_GRADE_THRESHOLD:
            # Count dropped below threshold; reset so a future burst can act.
            self._last_rl_count_at_adjustment = 0
            return

        if rate_limited <= self._last_rl_count_at_adjustment:
            return  # no new 429s since last adjustment — window still draining

        current_delay = _llm_metrics.get_call_delay_ms()
        new_delay = min(current_delay + LLM_DELAY_ADJUSTMENT_STEP_MS, LLM_DELAY_MAX_MS)
        self._last_rl_count_at_adjustment = rate_limited
        if new_delay == current_delay:
            return  # already at cap

        _llm_metrics.set_call_delay_ms(new_delay)
        log_structured(
            "info",
            "grade_agent_raised_llm_delay",
            from_ms=current_delay,
            to_ms=new_delay,
            rate_limited_count=rate_limited,
        )
        await self.bus.publish(
            STREAM_PROPOSALS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_GRADE,
                FieldName.TYPE: "proposal",
                "proposal_type": ProposalType.PARAMETER_CHANGE,
                "content": {
                    FieldName.PARAMETER: "LLM_CALL_DELAY_MS",
                    FieldName.PREVIOUS_VALUE: current_delay,
                    FieldName.NEW_VALUE: new_delay,
                    "reason": (
                        f"GradeAgent detected {rate_limited} rate-limited calls "
                        f"in the last 5-minute window (threshold={LLM_RATE_LIMIT_GRADE_THRESHOLD})"
                    ),
                    FieldName.AUTO_APPLIED: True,
                },
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _take_grade_action(self, grade: str, payload: dict[str, Any]) -> None:
        """Publish notifications and proposals based on grade threshold."""
        severity = GRADE_SEVERITY.get(grade)
        if severity:
            await self.bus.publish(
                STREAM_NOTIFICATIONS,
                {
                    FieldName.MSG_ID: str(uuid.uuid4()),
                    FieldName.SOURCE: SOURCE_GRADE,
                    FieldName.TYPE: "notification",
                    "severity": severity,
                    "notification_type": "agent_grade",
                    "message": (
                        f"Agent grade {grade} ({payload[FieldName.SCORE_PCT]}%) — "
                        f"accuracy={payload[FieldName.METRICS][FieldName.ACCURACY]:.1%} "
                        f"IC={payload[FieldName.METRICS][FieldName.IC]:+.3f}"
                    ),
                    FieldName.PAYLOAD: payload,
                    FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                },
            )

        if grade == Grade.C:
            await self.bus.publish(
                STREAM_PROPOSALS,
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_GRADE,
                    "type": "proposal",
                    "proposal_type": ProposalType.SIGNAL_WEIGHT_REDUCTION,
                    "content": {
                        "action": "reduce_signal_weight",
                        FieldName.REDUCTION_PCT: 30,
                        "reason": f"Grade {grade}: score {payload[FieldName.SCORE_PCT]}%",
                        FieldName.GRADE_PAYLOAD: payload,
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            self._consecutive_low_grades += 1

        elif grade == Grade.D:
            self._consecutive_low_grades += 1
            if self._consecutive_low_grades >= int(settings.RETIRE_AFTER_N_GRADES):
                await self.bus.publish(
                    STREAM_PROPOSALS,
                    {
                        "msg_id": str(uuid.uuid4()),
                        "source": SOURCE_GRADE,
                        "type": "proposal",
                        "proposal_type": ProposalType.AGENT_SUSPENSION,
                        "content": {
                            "action": "suspend_from_live_stream",
                            FieldName.CONSECUTIVE_LOW_GRADES: self._consecutive_low_grades,
                            "reason": f"{self._consecutive_low_grades} consecutive D grades",
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

        elif grade == Grade.F:
            self._consecutive_low_grades += 1
            await self.bus.publish(
                STREAM_PROPOSALS,
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_GRADE,
                    "type": "proposal",
                    "proposal_type": ProposalType.AGENT_RETIREMENT,
                    "content": {
                        "action": "retire_immediately",
                        "reason": f"Grade F: score {payload[FieldName.SCORE_PCT]}%",
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        else:
            self._consecutive_low_grades = 0


# ---------------------------------------------------------------------------
# ICUpdater — Spearman-based alpha factor reweighting
# ---------------------------------------------------------------------------


class ICUpdater(MultiStreamAgent):
    """Reweights alpha factors using Spearman IC against realized returns.

    Zeros factors below IC_ZERO_THRESHOLD, then normalizes remaining weights to 1.0.
    Writes updated weights to Redis key ``alpha:ic_weights``.
    """

    _state_name = AGENT_IC_UPDATER

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client: Redis,
        *,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[STREAM_TRADE_PERFORMANCE, STREAM_TRADE_COMPLETED],
            consumer="ic-updater",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self._fills = 0
        self._score_pnl_buffer: deque[tuple[float, float]] = deque(maxlen=200)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._fills += 1
        pnl = float(data.get(FieldName.PNL) or 0.0)
        composite_score = await self._fetch_composite_score(data.get(FieldName.TRACE_ID))
        self._score_pnl_buffer.append((composite_score, pnl))

        trigger = max(int(settings.IC_UPDATE_EVERY_N_FILLS), 1)
        if self._fills % trigger != 0:
            try:
                await _write_heartbeat(
                    self.redis,
                    self._state_name,
                    f"fill_buffered:{self._fills}/{trigger}",
                    self._fills,
                    extra={FieldName.EXEC_STATUS: "idle:buffering"},
                )
            except Exception:
                log_structured("warning", "ic_updater_idle_heartbeat_failed", exc_info=True)
            return

        await self._recompute_and_publish()

    async def _fetch_composite_score(self, trace_id: str | None) -> float:
        """Look up the composite_score from agent_runs for this trace_id."""
        if not trace_id or not is_db_available():
            return 0.5
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT (signal_data::jsonb->>'composite_score')::float
                        FROM agent_runs WHERE trace_id = :trace_id LIMIT 1
                    """),
                    {"trace_id": trace_id},
                )
                val = result.scalar()
                return float(val) if val is not None else 0.5
        except Exception:
            return 0.5

    async def _recompute_and_publish(self) -> None:
        """Compute IC per factor, zero weak ones, normalize, write to Redis and DB."""
        lookback_n = min(len(self._score_pnl_buffer), 100)
        recent = list(self._score_pnl_buffer)[-lookback_n:]

        if len(recent) < 3:
            log_structured("info", "ic_updater_insufficient_data", fills=self._fills)
            return

        scores = [p[0] for p in recent]
        pnls = [p[1] for p in recent]

        composite_ic = spearman_correlation(scores, pnls)
        momentum_signals = [1.0 if s > 0.5 else -1.0 for s in scores]
        momentum_ic = spearman_correlation(momentum_signals, pnls)

        raw_factors: dict[str, float] = {
            "composite_score": composite_ic,
            FieldName.MOMENTUM: momentum_ic,
        }

        threshold = float(settings.IC_ZERO_THRESHOLD)
        active = {f: max(ic, 0.0) for f, ic in raw_factors.items() if abs(ic) > threshold}

        total = sum(active.values())
        weights: dict[str, float] = (
            {"composite_score": 1.0}
            if total <= 0
            else {k: round(v / total, 6) for k, v in active.items()}
        )

        await self.redis.set(
            REDIS_KEY_IC_WEIGHTS, json.dumps(weights), ex=REDIS_IC_WEIGHTS_TTL_SECONDS
        )

        log_structured(
            "info",
            "ic_weights_updated",
            weights=weights,
            composite_ic=composite_ic,
            momentum_ic=momentum_ic,
            fills=self._fills,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        for factor, ic_val in raw_factors.items():
            await self.bus.publish(
                STREAM_FACTOR_IC_HISTORY,
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_IC_UPDATER,
                    "type": "ic_update",
                    "factor_name": factor,
                    FieldName.IC_SCORE: round(ic_val, 6),
                    FieldName.WEIGHT: weights.get(factor, 0.0),
                    FieldName.FILLS: self._fills,
                    "timestamp": now_iso,
                },
            )
            await persist_factor_ic(factor, ic_val, now_iso)

        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                "msg_id": str(uuid.uuid4()),
                "source": SOURCE_IC_UPDATER,
                "type": "notification",
                "severity": Severity.INFO,
                "notification_type": "ic_update",
                "message": (
                    f"IC weights updated after {self._fills} fills — "
                    f"composite={composite_ic:+.3f} momentum={momentum_ic:+.3f}"
                ),
                FieldName.WEIGHTS: weights,
                "timestamp": now_iso,
            },
        )

        # Write heartbeat so dashboard shows IC_UPDATER as ACTIVE
        try:
            await _write_heartbeat(
                self.redis,
                self._state_name,
                f"ic_update fills={self._fills} composite_ic={composite_ic:+.3f}",
                self._fills,
                extra={FieldName.COMPOSITE_IC: round(composite_ic, 4), FieldName.WEIGHTS: weights},
            )
        except Exception:
            log_structured("warning", "ic_updater_heartbeat_failed", exc_info=True)


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
        # Holds the GradeAgent eval_buffer reference injected at startup (optional)
        self._grade_agent: GradeAgent | None = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream in {STREAM_TRADE_PERFORMANCE, STREAM_TRADE_COMPLETED}:
            self._fills += 1
            self._recent_fills.append(
                {
                    FieldName.SYMBOL: data.get(FieldName.SYMBOL),
                    FieldName.SIDE: data.get(FieldName.SIDE),
                    "pnl": data.get(FieldName.PNL),
                    "pnl_percent": data.get(FieldName.PNL_PERCENT),
                    "fill_price": data.get(FieldName.FILL_PRICE),
                    "filled_at": data.get(FieldName.FILLED_AT),
                    # Decision provenance carried on the fill events so the
                    # per-model reflection summary (_build_prompt) is populated.
                    FieldName.MODEL_USED: data.get(FieldName.MODEL_USED),
                    FieldName.PRIMARY_EDGE: data.get(FieldName.PRIMARY_EDGE),
                }
            )
        elif stream == STREAM_AGENT_GRADES:
            self._recent_grades.append(
                {
                    "grade": data.get(FieldName.GRADE),
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
        if len(self._recent_fills) < 3:
            return

        await self._run_reflection()

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
                        "msg_id": str(uuid.uuid4()),
                        "source": SOURCE_REFLECTION,
                        "type": "notification",
                        "severity": Severity.WARNING,
                        "notification_type": "reflection_skipped",
                        "message": "Reflection skipped: daily LLM token budget exceeded",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                "summary": f"LLM unavailable after {self._fills} fills.",
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
            "msg_id": str(uuid.uuid4()),
            "source": SOURCE_REFLECTION,
            "type": "reflection_output",
            "trace_id": trace_id,
            FieldName.FILLS_ANALYZED: self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
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

        await self.bus.publish(STREAM_REFLECTION_OUTPUTS, reflection_payload)
        await write_agent_log(trace_id, LogType.REFLECTION, reflection_payload)
        await persist_reflection_record(reflection_payload)
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                "msg_id": str(uuid.uuid4()),
                "source": SOURCE_REFLECTION,
                "type": "notification",
                "severity": Severity.INFO,
                "notification_type": "reflection",
                "message": reflection_data.get(FieldName.SUMMARY, "Reflection completed."),
                FieldName.HYPOTHESIS_COUNT: len(reflection_data.get(FieldName.HYPOTHESES, [])),
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
                "win_rate": round(win_rate, 4),
                FieldName.RECENT_FILLS: recent_fills,
                FieldName.RECENT_GRADES: list(self._recent_grades)[-5:],
                FieldName.RECENT_IC_CHANGES: list(self._recent_ic)[-5:],
                # Per-model win-rate/PnL so the LLM can reason about which model
                # is trading well, not just aggregate outcomes.
                FieldName.MODEL_PERFORMANCE: aggregate_model_performance(recent_fills),
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


# ---------------------------------------------------------------------------
# StrategyProposer — converts reflection hypotheses into concrete proposals
# ---------------------------------------------------------------------------


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

        for hypothesis in strong:
            proposal = self._build_proposal(hypothesis, data, now_iso)

            if proposal[FieldName.PROPOSAL_TYPE] == ProposalType.CODE_CHANGE:
                await self.bus.publish(
                    STREAM_GITHUB_PRS,
                    {
                        "msg_id": str(uuid.uuid4()),
                        "source": SOURCE_STRATEGY_PROPOSER,
                        "type": "pr_request",
                        "title": f"Strategy rule proposal: {hypothesis.get(FieldName.DESCRIPTION, '')[:80]}",
                        "body": json.dumps(
                            {
                                FieldName.HYPOTHESIS: hypothesis,
                                "reflection_trace_id": data.get(FieldName.TRACE_ID),
                                FieldName.FILLS_ANALYZED: data.get(FieldName.FILLS_ANALYZED),
                            },
                            default=str,
                        ),
                        "timestamp": now_iso,
                    },
                )

            await self.bus.publish(STREAM_PROPOSALS, proposal)
            await persist_proposal(proposal)
            # Also persist to typed strategies table for learning dashboard
            await persist_strategy_record(
                {
                    FieldName.RULES: proposal.get(FieldName.CONTENT, {}),
                    "description": hypothesis.get(FieldName.DESCRIPTION, ""),
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
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_STRATEGY_PROPOSER,
                    "type": "notification",
                    "severity": Severity.INFO,
                    "notification_type": "proposal",
                    "message": (
                        f"New {proposal[FieldName.PROPOSAL_TYPE]} proposal "
                        f"(confidence={float(hypothesis.get(FieldName.CONFIDENCE) or 0):.0%}): "
                        f"{hypothesis.get(FieldName.DESCRIPTION, '')[:100]}"
                    ),
                    "timestamp": now_iso,
                },
            )

        log_structured(
            "info",
            "strategy_proposals_published",
            total_hypotheses=len(hypotheses),
            strong_hypotheses=len(strong),
            reflection_trace_id=data.get(FieldName.TRACE_ID),
        )

        # Write heartbeat so dashboard shows STRATEGY_PROPOSER as ACTIVE
        try:
            from api.redis_client import get_redis as _get_redis  # noqa: PLC0415

            _redis = await _get_redis()
            await _write_heartbeat(
                _redis,
                self._state_name,
                f"proposals published strong={len(strong)}/{len(hypotheses)}",
                len(strong),
            )
        except Exception:
            log_structured("warning", "strategy_proposer_heartbeat_failed", exc_info=True)

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

    def _build_proposal(
        self, hypothesis: dict[str, Any], reflection_data: dict[str, Any], now_iso: str
    ) -> dict[str, Any]:
        hyp_type = str(hypothesis.get(FieldName.TYPE) or "parameter").lower()
        description = str(hypothesis.get(FieldName.DESCRIPTION) or "")
        confidence = float(hypothesis.get(FieldName.CONFIDENCE) or 0)

        base = {
            "msg_id": str(uuid.uuid4()),
            "source": SOURCE_STRATEGY_PROPOSER,
            "type": "proposal",
            "requires_approval": True,
            "reflection_trace_id": reflection_data.get(FieldName.TRACE_ID),
            "timestamp": now_iso,
            "content": {
                "description": description,
                "confidence": confidence,
                FieldName.HYPOTHESIS_TYPE: hyp_type,
            },
        }

        if hyp_type == HypothesisType.PARAMETER:
            base[FieldName.PROPOSAL_TYPE] = ProposalType.PARAMETER_CHANGE
            base[FieldName.CONTENT][FieldName.IMPLEMENTATION] = "db_update"
            base[FieldName.CONTENT][FieldName.NOTE] = (
                "Update config parameter via DB — no deploy required."
            )
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
        else:
            base[FieldName.PROPOSAL_TYPE] = ProposalType.REGIME_ADJUSTMENT
            base[FieldName.CONTENT][FieldName.REGIME_CONTEXT] = reflection_data.get(
                FieldName.REGIME_EDGE, {}
            )

        return base


# ---------------------------------------------------------------------------
# NotificationAgent — classify and route all system events
# ---------------------------------------------------------------------------

_STREAM_SEVERITY: dict[str, str] = {
    STREAM_RISK_ALERTS: Severity.URGENT,
    STREAM_PROPOSALS: Severity.INFO,
    STREAM_AGENT_GRADES: Severity.INFO,
    STREAM_REFLECTION_OUTPUTS: Severity.INFO,
    STREAM_FACTOR_IC_HISTORY: Severity.INFO,
    STREAM_EXECUTIONS: Severity.INFO,
    STREAM_TRADE_PERFORMANCE: Severity.INFO,
    STREAM_DECISIONS: Severity.INFO,
    STREAM_SIGNALS: Severity.INFO,
    STREAM_MARKET_TICKS: Severity.INFO,
    STREAM_AGENT_LOGS: Severity.INFO,
}


class NotificationAgent(MultiStreamAgent):
    """Observes all output streams, deduplicates events, and persists notifications."""

    _state_name = AGENT_NOTIFICATION

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client: Redis,
        *,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[
                STREAM_MARKET_TICKS,
                STREAM_SIGNALS,
                STREAM_DECISIONS,
                STREAM_EXECUTIONS,
                STREAM_RISK_ALERTS,
                STREAM_AGENT_LOGS,
                STREAM_TRADE_PERFORMANCE,
                STREAM_AGENT_GRADES,
                STREAM_FACTOR_IC_HISTORY,
                STREAM_REFLECTION_OUTPUTS,
                STREAM_PROPOSALS,
            ],
            consumer="notification-agent",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self._dedup_window_secs = NOTIFICATION_DEDUP_TTL_SECONDS
        self._session_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Rich per-stream message builders
    # ------------------------------------------------------------------

    def _msg_trade_performance(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        side = str(data.get(FieldName.SIDE) or "").upper()
        exit_price = float(data.get(FieldName.EXIT_PRICE) or data.get(FieldName.FILL_PRICE) or 0)
        entry_price = float(data.get(FieldName.ENTRY_PRICE) or exit_price)
        pnl = float(data.get(FieldName.PNL) or 0)
        pnl_pct = float(data.get(FieldName.PNL_PERCENT) or 0)

        if pnl == 0.0:
            # Opening fill — no realized PnL yet
            qty = float(data.get(FieldName.QTY) or 0)
            return f"OPENED — {symbol} ({side}) · Price: ${exit_price:,.2f} | Qty: {qty:.4g}"

        sign = "+" if pnl >= 0 else ""
        return (
            f"CLOSED — {symbol} ({side}) · "
            f"Exit: ${exit_price:,.2f} | Entry: ${entry_price:,.2f} · "
            f"Trade PnL: {sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%) | "
            f"Session: {'+' if self._session_pnl >= 0 else ''}${self._session_pnl:,.2f}"
        )

    def _msg_signal(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        sig_type = str(data.get(FieldName.TYPE) or data.get(FieldName.SIGNAL_TYPE) or "signal")
        price = float(data.get(FieldName.PRICE) or data.get(FieldName.LAST_PRICE) or 0)
        score = float(data.get(FieldName.COMPOSITE_SCORE) or data.get(FieldName.SCORE) or 0)

        parts = [f"SIGNAL — {symbol} | {sig_type}"]
        if price > 0:
            parts.append(f"Price: ${price:,.2f}")
        if score:
            parts.append(f"Score: {score:.1f}")
        return " · ".join(parts)

    def _msg_risk_alert(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        reason = str(data.get(FieldName.REASON) or data.get(FieldName.MESSAGE) or "risk event")
        return f"RISK ALERT — {symbol} · {reason}"

    def _msg_decision(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        action = str(data.get(FieldName.ACTION) or "?").upper()
        score = float(data.get(FieldName.REASONING_SCORE) or 0)
        edge = str(data.get(FieldName.PRIMARY_EDGE) or "")
        rr = float(data.get(FieldName.RR_RATIO) or 0)

        parts = [f"DECISION — {symbol} | {action}"]
        if score:
            parts.append(f"Score: {score:.2f}")
        if edge:
            parts.append(f"Edge: {edge[:40]}")
        if rr:
            parts.append(f"R/R: {rr:.1f}x")
        return " · ".join(parts)

    # User-facing notifications are restricted to actual executed buy/sell
    # fills. Other streams (signals, decisions, grades, reflections, risk
    # alerts, proposals) are still consumed for internal state (e.g. session
    # PnL on STREAM_TRADE_PERFORMANCE), but they do not surface to the
    # dashboard notification panel.
    _PUBLISH_STREAMS: frozenset[str] = frozenset({STREAM_EXECUTIONS})

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == STREAM_NOTIFICATIONS:
            return

        # Track cumulative session PnL from closing fills — runs even when the
        # notification itself is suppressed, so session totals stay accurate.
        if stream == STREAM_TRADE_PERFORMANCE:
            pnl_val = float(data.get(FieldName.PNL) or 0.0)
            if pnl_val != 0.0:
                self._session_pnl += pnl_val

        if stream not in self._PUBLISH_STREAMS:
            # Still write heartbeat so the dashboard reflects agent health.
            await self._heartbeat(stream, data)
            return

        event_type = str(
            data.get(FieldName.TYPE) or data.get(FieldName.NOTIFICATION_TYPE) or stream
        )
        if event_type.lower() != "order_filled":
            await self._heartbeat(stream, data, event_type=event_type)
            return

        # Require a valid buy/sell side on the fill before surfacing it.
        side_raw = str(data.get(FieldName.SIDE) or data.get(FieldName.ACTION) or "").strip().lower()
        try:
            OrderSide(side_raw)
        except ValueError:
            log_structured(
                "debug",
                "notification_dropped_invalid_side",
                stream=stream,
                side=side_raw,
            )
            await self._heartbeat(stream, data)
            return

        symbol_key = str(data.get(FieldName.SYMBOL) or data.get(FieldName.ASSET) or "")
        msg_id = str(data.get(FieldName.MSG_ID) or redis_id)
        trace_key = str(data.get(FieldName.TRACE_ID) or msg_id)
        dedup_key = REDIS_KEY_NOTIFICATION_DEDUP.format(
            stream=stream,
            event_type=event_type,
            side=side_raw,
            symbol=symbol_key,
            trace=trace_key,
        )

        if await self.redis.exists(dedup_key):
            return
        await self.redis.setex(dedup_key, self._dedup_window_secs, "1")

        now_iso = datetime.now(timezone.utc).isoformat()
        severity = self._classify_severity(stream, data)
        notification = build_trade_notification(
            data=data,
            side=side_raw,
            stream=stream,
            event_type=event_type,
            observed_msg_id=msg_id,
            severity=severity,
            timestamp=now_iso,
            schema_version=DB_SCHEMA_VERSION,
            source=SOURCE_NOTIFICATION,
        )

        if is_db_available():
            try:
                from api.core.writer.safe_writer import SafeWriter  # noqa: PLC0415

                writer = SafeWriter(AsyncSessionFactory)
                await writer.write_notification(
                    notification[FieldName.MSG_ID], STREAM_NOTIFICATIONS, notification
                )
            except Exception:
                log_structured(
                    "warning", "notification_persist_failed", stream=stream, exc_info=True
                )
                # DB write failed mid-flight — keep the dashboard hydrated by
                # mirroring to the in-memory store as a best-effort fallback.
                from api.runtime_state import get_runtime_store  # noqa: PLC0415

                get_runtime_store().record_notification(notification)
                log_structured(
                    "warning",
                    "notification_persistence_miss_live_only",
                    stream=stream,
                    notification_id=notification.get(FieldName.NOTIFICATION_ID),
                    trace_id=notification.get(FieldName.TRACE_ID),
                )
        else:
            from api.runtime_state import get_runtime_store  # noqa: PLC0415

            get_runtime_store().record_notification(notification)

        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            notification,
            maxlen=NOTIFICATIONS_STREAM_MAXLEN,
        )
        log_structured("debug", "notification_forwarded", stream=stream, severity=severity)

        # Mirror to Redis-backed REST store so /api/notifications surfaces this
        # notification on the next page load (the WebSocket-only path lost
        # everything if the client wasn't connected at the moment of fire).
        await self._mirror_notification_to_redis_store(
            notification, severity=severity, observed_msg_id=msg_id
        )

        await self._heartbeat(stream, data, event_type=event_type)

    @staticmethod
    async def _mirror_notification_to_redis_store(
        notification: dict[str, Any],
        *,
        severity: str,
        observed_msg_id: str,
    ) -> None:
        """Push a copy of the freshly-fired notification into RedisStore.

        Best-effort: a failure here must never crash the agent loop, since the
        primary delivery channel (WS broadcast) has already succeeded by the
        time we get called.
        """
        store = _get_redis_store()
        if store is None:
            return
        try:
            rest_payload = dict(notification)
            # Preserve the canonical notification_id as the REST list `id` so
            # dedup with the WebSocket stream stays consistent.
            rest_payload.setdefault(
                FieldName.ID, notification.get(FieldName.NOTIFICATION_ID) or observed_msg_id
            )
            rest_payload.setdefault(FieldName.SEVERITY, severity)
            await store.push_notification(rest_payload)
        except Exception:
            log_structured("warning", "notification_redis_store_mirror_failed", exc_info=True)

    async def _heartbeat(
        self, stream: str, data: dict[str, Any], *, event_type: str | None = None
    ) -> None:
        """Write a heartbeat so the dashboard shows NOTIFICATION_AGENT as ACTIVE.

        Called both when a notification is published and when an event is
        consumed-but-suppressed, so the agent looks alive either way.
        """
        if event_type is None:
            event_type = str(
                data.get(FieldName.TYPE) or data.get(FieldName.NOTIFICATION_TYPE) or stream
            )
        try:
            await _write_heartbeat(
                self.redis,
                self._state_name,
                f"stream={stream} event_type={event_type}",
                0,
            )
        except Exception:
            log_structured("warning", "notification_heartbeat_failed", exc_info=True)

    def _classify_severity(self, stream: str, data: dict[str, Any]) -> str:
        if explicit := data.get(FieldName.SEVERITY):
            return str(explicit)
        grade = str(data.get(FieldName.GRADE) or "")
        if grade == Grade.F:
            return Severity.CRITICAL
        if grade == Grade.D:
            return Severity.URGENT
        # Negative PnL on a closing fill → warning
        if stream == STREAM_TRADE_PERFORMANCE:
            pnl = float(data.get(FieldName.PNL) or 0.0)
            if pnl < 0:
                return Severity.WARNING
        if stream == STREAM_EXECUTIONS:
            try:
                pnl = float(data.get(FieldName.PNL))
            except (TypeError, ValueError):
                pnl = None
            if pnl is not None and pnl < 0:
                return Severity.WARNING
        return _STREAM_SEVERITY.get(stream, Severity.INFO)


# ---------------------------------------------------------------------------
# ChallengerAgent — parallel experimental agent instance
# ---------------------------------------------------------------------------


class ChallengerAgent(MultiStreamAgent):
    """A parallel, independently-graded agent instance with an experimental config.

    StrategyProposer can propose a ``new_agent`` when reflection surfaces a
    hypothesis that requires a different parameter set to validate.  Once
    approved via the dashboard, the orchestrator spawns a ChallengerAgent
    alongside the existing pipeline agents.

    The challenger:
      - Receives the same ``executions`` and ``trade_performance`` stream events
      - Computes its own grade using its ``challenger_config`` overrides
      - Records results in ``agent_grades`` and ``trade_lifecycle`` under its
        own ``instance_id``, so performance can be compared in the dashboard
      - Retires itself after ``max_fills`` events (default: 200) and publishes
        a final comparison summary to the ``proposals`` stream

    The orchestrator must call ``.start()`` after instantiation and ``.stop()``
    when retiring the instance.
    """

    _state_name = AGENT_CHALLENGER

    DEFAULT_MAX_FILLS = 200

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        *,
        challenger_config: dict[str, Any] | None = None,
        max_fills: int = DEFAULT_MAX_FILLS,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        self._challenger_id = str(uuid.uuid4())[:8]
        super().__init__(
            bus,
            dlq,
            # STREAM_MARKET_EVENTS (the UNFILTERED price stream from PricePoller)
            # drives the REAL shadow trades, NOT STREAM_SIGNALS: SignalGenerator
            # throttles LOW/noise ticks before publishing signals, so consuming
            # signals would feed the shadow strategy a sparsified series and skew
            # its PnL/win-rate vs the backtest harness (which sees every bar). Safe
            # from stealing because each agent has its OWN fan-out group.
            # executions/trade_performance remain the grading cadence clock.
            streams=[STREAM_MARKET_EVENTS, STREAM_EXECUTIONS, STREAM_TRADE_PERFORMANCE],
            consumer=f"challenger-{self._challenger_id}",
            agent_state=agent_state,
        )
        # Override the base class default (None) so grade/retire payloads carry
        # a stable identifier even when register_agent_instance() never runs
        # (e.g. unit tests, or when start() is bypassed).
        self._instance_id = self._challenger_id
        self._config: dict[str, Any] = challenger_config or {}
        self._max_fills = max_fills
        self._fills = 0
        self._pnl_buffer: deque[float] = deque(maxlen=100)
        self._grade_history: list[dict[str, Any]] = []
        self._lifecycle_registered = False
        # Shadow engines: this challenger's configured strategy AND the baseline,
        # both fed the SAME live signals so we can A/B their real performance on
        # live data and propose promotion only when the challenger beats baseline.
        self._shadow, self._baseline_shadow = self._build_shadow_engines()

    def _build_shadow_engines(self):
        """Construct (own, baseline) ShadowTradeEngines from the configured strategy.

        Returns (None, None) when no (or an unknown) strategy is configured, so a
        config-less challenger is a safe no-op on signal events.
        """
        strategy_name = str(self._config.get(FieldName.STRATEGY) or "")
        if not strategy_name:
            return None, None
        try:
            from api.services.shadow_trader import ShadowTradeEngine  # noqa: PLC0415
            from backtest.strategies import STRATEGIES  # noqa: PLC0415

            baseline_name = "baseline_momentum"
            if strategy_name not in STRATEGIES:
                return None, None
            own = ShadowTradeEngine(strategy_name, STRATEGIES[strategy_name])
            baseline = (
                ShadowTradeEngine(baseline_name, STRATEGIES[baseline_name])
                if baseline_name in STRATEGIES
                else None
            )
            return own, baseline
        except Exception:
            log_structured("warning", "challenger_shadow_engine_init_failed", exc_info=True)
            return None, None

    async def start(self) -> None:
        """Begin consuming streams AND register at SHADOW immediately.

        Eager registration (rather than waiting for the first fill in
        ``process``) means an auto-spawned shadow challenger appears on the
        lifecycle panel as soon as the app starts, even before any live trade
        flows — which matters when the pipeline is idle.
        """
        await super().start()
        self._ensure_lifecycle_registered()

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._ensure_lifecycle_registered()

        # Unfiltered market_events drive the REAL shadow trades: the challenger runs
        # its OWN strategy (and baseline) on EVERY price tick the poller emits — the
        # same series the backtest harness measures — not the throttled signal stream.
        if stream == STREAM_MARKET_EVENTS:
            self._observe_shadow(data)
            return

        if stream == STREAM_TRADE_PERFORMANCE:
            self._pnl_buffer.append(float(data.get(FieldName.PNL) or 0.0))
            self._fills += 1

        if (
            self._fills > 0
            and self._fills % max(int(self._config.get(FieldName.GRADE_EVERY, 10)), 1) == 0
        ):
            await self._grade()

        if self._fills >= self._max_fills:
            await self._retire_with_summary()

    def _observe_shadow(self, data: dict[str, Any]) -> None:
        """Run the configured strategy (and baseline) on one market-events price tick.

        This is what makes the challenger's config REAL: it executes the strategy on
        EVERY live tick as shadow trades, instead of grading the baseline's fills like
        every challenger used to. No real capital is touched.

        market_events wraps the tick in a JSON ``payload`` string (PricePoller); parse
        it the same way SignalGenerator does so we read the same unfiltered series.
        """
        if self._shadow is None:
            return
        raw = data.get(FieldName.PAYLOAD)
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return
        elif isinstance(raw, dict):
            payload = raw
        else:
            payload = data

        symbol = payload.get(FieldName.SYMBOL)
        try:
            price = float(payload.get(FieldName.PRICE) or 0.0)
        except (TypeError, ValueError):
            return
        if not symbol or price <= 0:
            return
        self._shadow.observe(symbol, price)
        if self._baseline_shadow is not None:
            self._baseline_shadow.observe(symbol, price)

    def _shadow_summary(self) -> dict[str, Any]:
        """Own vs baseline shadow performance on live data (empty when no engine).

        These are challenger-report fields (not payload FieldName keys); they ride
        inside the grade / retirement ``metrics`` block for the dashboard.
        """
        if self._shadow is None:
            return {}
        m = self._shadow.metrics
        summary: dict[str, Any] = {
            "shadow_trades": m.trades,
            "shadow_win_rate": round(m.win_rate, 4),
            "shadow_pnl": round(m.realized_pnl, 4),
            "shadow_sharpe": round(m.sharpe, 4),
        }
        if self._baseline_shadow is not None:
            b = self._baseline_shadow.metrics
            summary["baseline_shadow_trades"] = b.trades
            summary["baseline_shadow_win_rate"] = round(b.win_rate, 4)
            summary["baseline_shadow_pnl"] = round(b.realized_pnl, 4)
            summary["beats_baseline_shadow"] = m.realized_pnl > b.realized_pnl
        return summary

    async def _grade(self) -> None:
        """Compute a grade for this challenger window and publish results."""
        recent = list(self._pnl_buffer)[-20:]
        if not recent:
            return
        win_rate = sum(1 for p in recent if p > 0) / len(recent)
        avg_pnl = sum(recent) / len(recent)
        grade_result = {
            FieldName.CHALLENGER_ID: self._challenger_id,
            FieldName.INSTANCE_ID: self._instance_id,
            FieldName.FILLS: self._fills,
            "win_rate": round(win_rate, 4),
            FieldName.AVG_PNL: round(avg_pnl, 4),
            FieldName.CONFIG: self._config,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Real shadow-strategy evidence (own vs baseline) on live data.
            **self._shadow_summary(),
        }
        self._grade_history.append(grade_result)

        await self.bus.publish(
            STREAM_AGENT_GRADES,
            {
                "msg_id": str(uuid.uuid4()),
                "type": "challenger_grade",
                "source": f"challenger-{self._challenger_id}",
                "agent": "challenger",
                "grade": Grade.B if win_rate >= 0.5 else Grade.C,
                "score": win_rate,
                "score_pct": round(win_rate * 100, 1),
                "metrics": grade_result,
                "timestamp": grade_result[FieldName.TIMESTAMP],
            },
        )
        log_structured(
            "info",
            "challenger_grade",
            challenger_id=self._challenger_id,
            fills=self._fills,
            win_rate=win_rate,
            avg_pnl=avg_pnl,
        )

    async def _retire_with_summary(self) -> None:
        """Publish a final comparison summary and stop the challenger."""
        total_pnl = sum(self._pnl_buffer)
        win_rate = (
            sum(1 for p in self._pnl_buffer if p > 0) / len(self._pnl_buffer)
            if self._pnl_buffer
            else 0.0
        )
        summary = {
            "msg_id": str(uuid.uuid4()),
            "type": "challenger_summary",
            "source": f"challenger-{self._challenger_id}",
            FieldName.CHALLENGER_ID: self._challenger_id,
            FieldName.INSTANCE_ID: self._instance_id,
            FieldName.TOTAL_FILLS: self._fills,
            FieldName.TOTAL_PNL: round(total_pnl, 4),
            "win_rate": round(win_rate, 4),
            FieldName.CONFIG: self._config,
            FieldName.GRADE_HISTORY: self._grade_history[-5:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Real shadow-strategy evidence (own vs baseline) on live data.
            **self._shadow_summary(),
        }
        await self.bus.publish(
            STREAM_PROPOSALS,
            {
                **summary,
                "proposal_type": "challenger_result",
                "requires_approval": False,
                "content": {
                    "description": (
                        f"Challenger {self._challenger_id} completed {self._fills} fills. "
                        f"Win rate: {win_rate:.0%}, Total PnL: {total_pnl:+.2f}."
                        f"{self._backtest_verdict()}"
                    ),
                    "confidence": win_rate,
                },
            },
        )
        log_structured(
            "info",
            "challenger_retired",
            challenger_id=self._challenger_id,
            total_fills=self._fills,
            total_pnl=total_pnl,
            win_rate=win_rate,
        )
        await self.stop()

    def _backtest_verdict(self) -> str:
        """Judge this challenger's configured strategy in the backtest harness.

        Differentiation and merit are decided offline (the same harness the
        dashboard uses), so the retirement summary carries a real promote/retire
        recommendation rather than only a live win rate. Returns "" when no
        strategy is configured or the harness is unavailable.
        """
        strategy_name = str(self._config.get(FieldName.STRATEGY) or "")
        if not strategy_name:
            return ""
        try:
            from backtest.challenger import evaluate_from_stats  # noqa: PLC0415
            from backtest.compare import compare_on_prices  # noqa: PLC0415
            from backtest.data import synthetic_prices  # noqa: PLC0415
            from backtest.strategies import STRATEGIES  # noqa: PLC0415

            baseline = "baseline_momentum"
            if strategy_name not in STRATEGIES or baseline not in STRATEGIES:
                return ""
            prices = synthetic_prices(n=1500, vol_pct=1.5, seed=1)
            stats = compare_on_prices(
                prices,
                {strategy_name: STRATEGIES[strategy_name], baseline: STRATEGIES[baseline]},
            )
            verdict = evaluate_from_stats(stats, baseline=baseline)
            if verdict is None:
                return ""
            return f" Backtest verdict: {verdict.decision.upper()} — {verdict.reason}"
        except Exception:
            log_structured("warning", "challenger_backtest_verdict_failed", exc_info=True)
            return ""

    def _ensure_lifecycle_registered(self) -> None:
        """Register this challenger's strategy in the lifecycle registry once.

        A running challenger is a SHADOW-stage strategy — it consumes the live
        stream and is graded but places no orders — so it shows up on the
        dashboard's Strategy Lifecycle panel. Best-effort; never blocks process.
        """
        if self._lifecycle_registered:
            return
        self._lifecycle_registered = True
        strategy_name = str(self._config.get(FieldName.STRATEGY) or "")
        if not strategy_name:
            return
        try:
            from api.constants import StrategyStatus  # noqa: PLC0415
            from api.services.strategy_registry import get_strategy_registry  # noqa: PLC0415

            registry = get_strategy_registry()
            if registry.find_by_strategy(strategy_name) is not None:
                return  # already in the lifecycle (startup seeder, or another instance)
            version = registry.register({FieldName.STRATEGY: strategy_name})
            registry.transition(version.version_id, StrategyStatus.BACKTESTED)
            registry.transition(version.version_id, StrategyStatus.SHADOW)
        except Exception:
            log_structured("warning", "challenger_lifecycle_register_failed", exc_info=True)
