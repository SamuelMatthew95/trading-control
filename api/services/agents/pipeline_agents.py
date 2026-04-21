"""Pipeline agents: GradeAgent, ICUpdater, ReflectionAgent, StrategyProposer, NotificationAgent.

Each agent class focuses exclusively on its domain logic.
Math lives in ``scoring``, prompts in ``prompts``, DB writes in ``db_helpers``,
and the poll loop in ``base``.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
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
    NOTIFICATION_DEDUP_TTL_SECONDS,
    REDIS_IC_WEIGHTS_TTL_SECONDS,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_LLM_COST,
    REDIS_KEY_LLM_TOKENS,
    REDIS_KEY_NOTIFICATION_DEDUP,
    REFLECTION_MIN_HYPOTHESES,
    SOURCE_GRADE,
    SOURCE_IC_UPDATER,
    SOURCE_NOTIFICATION,
    SOURCE_REASONING,
    SOURCE_REFLECTION,
    SOURCE_STRATEGY_PROPOSER,
    STOP_LOSS_PCT,
    STREAM_AGENT_GRADES,
    STREAM_AGENT_LOGS,
    STREAM_DECISIONS,
    STREAM_EXECUTIONS,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_GITHUB_PRS,
    STREAM_MARKET_TICKS,
    STREAM_NOTIFICATIONS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_TRADE_PERFORMANCE,
    TAKE_PROFIT_PCT,
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
    write_agent_log,
    write_grade_to_db,
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
            streams=[STREAM_EXECUTIONS, STREAM_TRADE_PERFORMANCE],
            consumer="grade-agent",
            agent_state=agent_state,
        )
        self._fills = 0
        self._pnl_buffer: deque[float] = deque(maxlen=100)
        self._confidence_buffer: deque[float] = deque(maxlen=100)
        self._consecutive_low_grades = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == STREAM_TRADE_PERFORMANCE:
            self._pnl_buffer.append(float(data.get("pnl") or 0.0))
            self._fills += 1
        elif stream == STREAM_EXECUTIONS:
            self._confidence_buffer.append(float(data.get("confidence") or 0.5))

        trigger = max(int(settings.GRADE_EVERY_N_FILLS), 1)
        if self._fills == 0 or self._fills % trigger != 0:
            return

        await self._compute_and_publish_grade()

    async def _compute_and_publish_grade(self) -> None:
        trace_id = f"grade_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        lookback_n = int(settings.GRADE_LOOKBACK_N)

        try:
            accuracy = self._win_rate(lookback_n)
            ic = await self._information_coefficient(lookback_n)
            cost_eff = await self._cost_efficiency(lookback_n)
            latency = await self._latency_score()
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

        payload = {
            "msg_id": str(uuid.uuid4()),
            "type": "agent_grade",
            "source": SOURCE_GRADE,
            "agent": SOURCE_REASONING,
            "trace_id": trace_id,
            "grade": grade,
            "score": score,
            "score_pct": round(score * 100, 1),
            "metrics": {
                "accuracy": round(accuracy, 4),
                "ic": round(ic, 4),
                "ic_normalized": round(ic_norm, 4),
                "cost_efficiency": round(cost_eff, 4),
                "cost_normalized": round(cost_norm, 4),
                "latency_score": round(latency, 4),
            },
            "fills_graded": self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await self.bus.publish(STREAM_AGENT_GRADES, payload)
        log_structured("info", "grade_computed", grade=grade, score=score, fills=self._fills, ic=ic)

        await write_agent_log(trace_id, LogType.GRADE, payload)
        await write_grade_to_db(trace_id, payload["score_pct"], payload["metrics"])
        await self._take_grade_action(grade, payload)
        await self._backfill_grade_to_lifecycle(grade, payload, trace_id)

        # Write heartbeat with last grade score for dashboard display
        try:
            from api.redis_client import get_redis as _get_redis

            _redis = await _get_redis()
            await _write_heartbeat(
                _redis,
                self._state_name,
                f"grade={grade} score={payload['score_pct']}",
                self._fills,
                extra={"last_grade_score": payload["score_pct"]},
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
            from sqlalchemy import text as _text

            from api.database import AsyncSessionFactory
            from api.services.agents.db_helpers import upsert_trade_lifecycle

            grade_label = (
                f"Grade {grade}: accuracy={payload['metrics']['accuracy']:.0%} "
                f"IC={payload['metrics']['ic']:+.3f}"
            )
            async with AsyncSessionFactory() as _sess:
                row = await _sess.execute(
                    _text("""
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
                    grade_score=payload["score_pct"],
                    grade_label=grade_label,
                    status="graded",
                    graded_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            log_structured("warning", "grade_lifecycle_update_failed", exc_info=True)

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
                        {"n": lookback_n},
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
                        {"n": lookback_n},
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

    async def _take_grade_action(self, grade: str, payload: dict[str, Any]) -> None:
        """Publish notifications and proposals based on grade threshold."""
        severity = GRADE_SEVERITY.get(grade)
        if severity:
            await self.bus.publish(
                STREAM_NOTIFICATIONS,
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_GRADE,
                    "type": "notification",
                    "severity": severity,
                    "notification_type": "agent_grade",
                    "message": (
                        f"Agent grade {grade} ({payload['score_pct']}%) — "
                        f"accuracy={payload['metrics']['accuracy']:.1%} "
                        f"IC={payload['metrics']['ic']:+.3f}"
                    ),
                    "payload": payload,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                        "reduction_pct": 30,
                        "reason": f"Grade {grade}: score {payload['score_pct']}%",
                        "grade_payload": payload,
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
                            "consecutive_low_grades": self._consecutive_low_grades,
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
                        "reason": f"Grade F: score {payload['score_pct']}%",
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
            streams=[STREAM_TRADE_PERFORMANCE],
            consumer="ic-updater",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self._fills = 0
        self._score_pnl_buffer: deque[tuple[float, float]] = deque(maxlen=200)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._fills += 1
        pnl = float(data.get("pnl") or 0.0)
        composite_score = await self._fetch_composite_score(data.get("trace_id"))
        self._score_pnl_buffer.append((composite_score, pnl))

        trigger = max(int(settings.IC_UPDATE_EVERY_N_FILLS), 1)
        if self._fills % trigger != 0:
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
            "momentum": momentum_ic,
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
                    "ic_score": round(ic_val, 6),
                    "weight": weights.get(factor, 0.0),
                    "fills": self._fills,
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
                "weights": weights,
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
                extra={"composite_ic": round(composite_ic, 4), "weights": weights},
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
            streams=[STREAM_TRADE_PERFORMANCE, STREAM_AGENT_GRADES, STREAM_FACTOR_IC_HISTORY],
            consumer="reflection-agent",
            agent_state=agent_state,
        )
        self._fills = 0
        self._recent_fills: deque[dict[str, Any]] = deque(maxlen=50)
        self._recent_grades: deque[dict[str, Any]] = deque(maxlen=20)
        self._recent_ic: deque[dict[str, Any]] = deque(maxlen=20)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == STREAM_TRADE_PERFORMANCE:
            self._fills += 1
            self._recent_fills.append(
                {
                    "symbol": data.get("symbol"),
                    "side": data.get("side"),
                    "pnl": data.get("pnl"),
                    "pnl_percent": data.get("pnl_percent"),
                    "fill_price": data.get("fill_price"),
                    "filled_at": data.get("filled_at"),
                }
            )
        elif stream == STREAM_AGENT_GRADES:
            self._recent_grades.append(
                {
                    "grade": data.get("grade"),
                    "score": data.get("score"),
                    "metrics": data.get("metrics", {}),
                    "timestamp": data.get("timestamp"),
                }
            )
        elif stream == STREAM_FACTOR_IC_HISTORY:
            self._recent_ic.append(
                {
                    "factor": data.get("factor_name"),
                    "ic": data.get("ic_score"),
                    "weight": data.get("weight"),
                    "timestamp": data.get("timestamp"),
                }
            )

        trigger = max(int(settings.REFLECT_EVERY_N_FILLS), 1)
        if self._fills == 0 or self._fills % trigger != 0:
            return
        if len(self._recent_fills) < 3:
            return

        await self._run_reflection()

    async def _run_reflection(self) -> None:
        trace_id = f"reflection_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

        today = datetime.now(timezone.utc).date().isoformat()
        redis = None
        try:
            from api.redis_client import get_redis  # avoid circular import at module level

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
            from api.services.llm_router import call_llm_with_system

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
                hypotheses=len(reflection_data.get("hypotheses", [])),
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
        hypotheses = reflection_data.get("hypotheses", [])
        if len(hypotheses) < REFLECTION_MIN_HYPOTHESES and redis is not None:
            try:
                budget_now = int(await redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)
                if budget_now < settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
                    from api.services.llm_router import call_llm_with_system

                    raw_improved, tokens_imp, cost_imp = await call_llm_with_system(
                        prompt, REFLECTION_IMPROVE_PROMPT, trace_id
                    )
                    improved = self._parse_llm_response(raw_improved)
                    if len(improved.get("hypotheses", [])) > len(hypotheses):
                        reflection_data = improved
                        await redis.incrby(REDIS_KEY_LLM_TOKENS.format(date=today), tokens_imp)
                        await redis.incrbyfloat(REDIS_KEY_LLM_COST.format(date=today), cost_imp)
                        log_structured(
                            "info",
                            "reflection_refined_by_evaluator_optimizer",
                            trace_id=trace_id,
                            original_hypotheses=len(hypotheses),
                            refined_hypotheses=len(improved.get("hypotheses", [])),
                        )
            except Exception:
                log_structured("warning", "reflection_refinement_failed", exc_info=True)

        reflection_payload: dict[str, Any] = {
            "msg_id": str(uuid.uuid4()),
            "source": SOURCE_REFLECTION,
            "type": "reflection_output",
            "trace_id": trace_id,
            "fills_analyzed": self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **reflection_data,
        }

        await self.bus.publish(STREAM_REFLECTION_OUTPUTS, reflection_payload)
        await write_agent_log(trace_id, LogType.REFLECTION, reflection_payload)
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                "msg_id": str(uuid.uuid4()),
                "source": SOURCE_REFLECTION,
                "type": "notification",
                "severity": Severity.INFO,
                "notification_type": "reflection",
                "message": reflection_data.get("summary", "Reflection completed."),
                "hypothesis_count": len(reflection_data.get("hypotheses", [])),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Write heartbeat so dashboard shows REFLECTION_AGENT as ACTIVE
        if redis is not None:
            try:
                await _write_heartbeat(
                    redis,
                    self._state_name,
                    f"reflection fills={self._fills} hypotheses={len(reflection_data.get('hypotheses', []))}",
                    self._fills,
                )
            except Exception:
                log_structured("warning", "reflection_heartbeat_failed", exc_info=True)

    def _build_prompt(self) -> str:
        recent_fills = list(self._recent_fills)[-20:]
        total_pnl = sum(float(f.get("pnl") or 0) for f in recent_fills)
        win_rate = (
            sum(1 for f in recent_fills if float(f.get("pnl") or 0) > 0) / len(recent_fills)
            if recent_fills
            else 0
        )
        return json.dumps(
            {
                "fills_analyzed": len(recent_fills),
                "total_pnl": round(total_pnl, 4),
                "win_rate": round(win_rate, 4),
                "recent_fills": recent_fills,
                "recent_grades": list(self._recent_grades)[-5:],
                "recent_ic_changes": list(self._recent_ic)[-5:],
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
        hypotheses: list[dict[str, Any]] = data.get("hypotheses") or []
        min_confidence = float(settings.HYPOTHESIS_MIN_CONFIDENCE)
        now_iso = datetime.now(timezone.utc).isoformat()

        strong = [h for h in hypotheses if float(h.get("confidence") or 0) >= min_confidence]

        if not strong:
            log_structured(
                "info",
                "strategy_proposer_no_strong_hypotheses",
                total=len(hypotheses),
                threshold=min_confidence,
                reflection_trace_id=data.get("trace_id"),
            )
            return

        # Agentic planning step: rank strong hypotheses by expected impact before acting
        strong = await self._plan_and_rank(hypotheses, strong, data.get("trace_id", ""))

        for hypothesis in strong:
            proposal = self._build_proposal(hypothesis, data, now_iso)

            if proposal["proposal_type"] == ProposalType.CODE_CHANGE:
                await self.bus.publish(
                    STREAM_GITHUB_PRS,
                    {
                        "msg_id": str(uuid.uuid4()),
                        "source": SOURCE_STRATEGY_PROPOSER,
                        "type": "pr_request",
                        "title": f"Strategy rule proposal: {hypothesis.get('description', '')[:80]}",
                        "body": json.dumps(
                            {
                                "hypothesis": hypothesis,
                                "reflection_trace_id": data.get("trace_id"),
                                "fills_analyzed": data.get("fills_analyzed"),
                            },
                            default=str,
                        ),
                        "timestamp": now_iso,
                    },
                )

            await self.bus.publish(STREAM_PROPOSALS, proposal)
            await persist_proposal(proposal)
            await self.bus.publish(
                STREAM_NOTIFICATIONS,
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_STRATEGY_PROPOSER,
                    "type": "notification",
                    "severity": Severity.INFO,
                    "notification_type": "proposal",
                    "message": (
                        f"New {proposal['proposal_type']} proposal "
                        f"(confidence={float(hypothesis.get('confidence') or 0):.0%}): "
                        f"{hypothesis.get('description', '')[:100]}"
                    ),
                    "timestamp": now_iso,
                },
            )

        log_structured(
            "info",
            "strategy_proposals_published",
            total_hypotheses=len(hypotheses),
            strong_hypotheses=len(strong),
            reflection_trace_id=data.get("trace_id"),
        )

        # Write heartbeat so dashboard shows STRATEGY_PROPOSER as ACTIVE
        try:
            from api.redis_client import get_redis as _get_redis

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
            from api.services.llm_router import call_llm_with_system

            plan_prompt = json.dumps(
                {"all_hypotheses": all_hypotheses, "strong_hypotheses": strong},
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
            ranked_indices = plan.get("ranked_indices", [])

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
        hyp_type = str(hypothesis.get("type") or "parameter").lower()
        description = str(hypothesis.get("description") or "")
        confidence = float(hypothesis.get("confidence") or 0)

        base = {
            "msg_id": str(uuid.uuid4()),
            "source": SOURCE_STRATEGY_PROPOSER,
            "type": "proposal",
            "requires_approval": True,
            "reflection_trace_id": reflection_data.get("trace_id"),
            "timestamp": now_iso,
            "content": {
                "description": description,
                "confidence": confidence,
                "hypothesis_type": hyp_type,
            },
        }

        if hyp_type == HypothesisType.PARAMETER:
            base["proposal_type"] = ProposalType.PARAMETER_CHANGE
            base["content"]["implementation"] = "db_update"
            base["content"]["note"] = "Update config parameter via DB — no deploy required."
        elif hyp_type == HypothesisType.RULE:
            base["proposal_type"] = ProposalType.CODE_CHANGE
            base["content"]["implementation"] = "github_pr"
            base["content"]["note"] = "Rule change requires PR review and deploy."
        elif hyp_type == HypothesisType.NEW_AGENT:
            # Propose spawning a challenger agent instance with different config
            base["proposal_type"] = ProposalType.NEW_AGENT
            base["requires_approval"] = True
            base["content"]["implementation"] = "challenger_spawn"
            base["content"]["challenger_config"] = reflection_data.get("challenger_config", {})
            base["content"]["note"] = (
                "Spawn a parallel challenger agent with the proposed config changes. "
                "It runs alongside the current agent; retire it via the dashboard."
            )
        else:
            base["proposal_type"] = ProposalType.REGIME_ADJUSTMENT
            base["content"]["regime_context"] = reflection_data.get("regime_edge", {})

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

    def _msg_execution(self, data: dict[str, Any]) -> str:
        symbol = str(data.get("symbol") or "?")
        side = str(data.get("side") or "").upper()
        qty = float(data.get("qty") or 0)
        fill_price = float(data.get("fill_price") or data.get("price") or 0)
        dollar_value = fill_price * qty

        parts = [f"{side} FILLED — {symbol}"]
        if fill_price > 0:
            parts.append(
                f"Price: ${fill_price:,.2f} | Qty: {qty:.4g} | Value: ${dollar_value:,.2f}"
            )
        if side == "BUY" and fill_price > 0:
            stop_price = fill_price * (1 - STOP_LOSS_PCT)
            tp_price = fill_price * (1 + TAKE_PROFIT_PCT)
            parts.append(
                f"Stop: ${stop_price:,.2f} (-{STOP_LOSS_PCT:.0%}) | "
                f"TP: ${tp_price:,.2f} (+{TAKE_PROFIT_PCT:.0%})"
            )
        return " · ".join(parts)

    def _msg_trade_performance(self, data: dict[str, Any]) -> str:
        symbol = str(data.get("symbol") or "?")
        side = str(data.get("side") or "").upper()
        exit_price = float(data.get("exit_price") or data.get("fill_price") or 0)
        entry_price = float(data.get("entry_price") or exit_price)
        pnl = float(data.get("pnl") or 0)
        pnl_pct = float(data.get("pnl_percent") or 0)

        if pnl == 0.0:
            # Opening fill — no realized PnL yet
            qty = float(data.get("qty") or 0)
            return f"OPENED — {symbol} ({side}) · Price: ${exit_price:,.2f} | Qty: {qty:.4g}"

        sign = "+" if pnl >= 0 else ""
        return (
            f"CLOSED — {symbol} ({side}) · "
            f"Exit: ${exit_price:,.2f} | Entry: ${entry_price:,.2f} · "
            f"Trade PnL: {sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%) | "
            f"Session: {'+' if self._session_pnl >= 0 else ''}${self._session_pnl:,.2f}"
        )

    def _msg_signal(self, data: dict[str, Any]) -> str:
        symbol = str(data.get("symbol") or "?")
        sig_type = str(data.get("type") or data.get("signal_type") or "signal")
        price = float(data.get("price") or data.get("last_price") or 0)
        score = float(data.get("composite_score") or data.get("score") or 0)

        parts = [f"SIGNAL — {symbol} | {sig_type}"]
        if price > 0:
            parts.append(f"Price: ${price:,.2f}")
        if score:
            parts.append(f"Score: {score:.1f}")
        return " · ".join(parts)

    def _msg_risk_alert(self, data: dict[str, Any]) -> str:
        symbol = str(data.get("symbol") or "?")
        reason = str(data.get("reason") or data.get("message") or "risk event")
        return f"RISK ALERT — {symbol} · {reason}"

    def _msg_decision(self, data: dict[str, Any]) -> str:
        symbol = str(data.get("symbol") or "?")
        action = str(data.get("action") or "?").upper()
        score = float(data.get("reasoning_score") or 0)
        edge = str(data.get("primary_edge") or "")
        rr = float(data.get("rr_ratio") or 0)

        parts = [f"DECISION — {symbol} | {action}"]
        if score:
            parts.append(f"Score: {score:.2f}")
        if edge:
            parts.append(f"Edge: {edge[:40]}")
        if rr:
            parts.append(f"R/R: {rr:.1f}x")
        return " · ".join(parts)

    def _build_message(self, stream: str, event_type: str, data: dict[str, Any]) -> str:
        if stream == STREAM_EXECUTIONS:
            return self._msg_execution(data)
        if stream == STREAM_TRADE_PERFORMANCE:
            return self._msg_trade_performance(data)
        if stream == STREAM_SIGNALS:
            return self._msg_signal(data)
        if stream == STREAM_RISK_ALERTS:
            return self._msg_risk_alert(data)
        if stream == STREAM_DECISIONS:
            return self._msg_decision(data)

        # Generic fallback for all other streams
        symbol = data.get("symbol")
        action = data.get("action") or data.get("side")
        agent_name = data.get("agent_name") or data.get("agent")
        grade = data.get("grade")
        score = data.get("score")
        reason = data.get("reason")

        details: list[str] = []
        if symbol:
            details.append(str(symbol))
        if action:
            details.append(str(action))
        if grade:
            details.append(f"grade={grade}")
        if score is not None:
            details.append(f"score={score}")
        if agent_name:
            details.append(f"agent={agent_name}")
        if reason:
            details.append(f"reason={reason}")

        if details:
            return f"{stream}:{event_type} — " + ", ".join(details)
        return f"{stream}:{event_type}"

    def _build_notification_type(self, stream: str, data: dict[str, Any]) -> str:
        if stream == STREAM_EXECUTIONS:
            side = str(data.get("side") or "").lower()
            return (
                f"execution.{side}"
                if side in {OrderSide.BUY, OrderSide.SELL}
                else f"stream:{stream}"
            )
        if stream == STREAM_TRADE_PERFORMANCE:
            pnl = float(data.get("pnl") or 0.0)
            if pnl > 0:
                return "trade.profit"
            if pnl < 0:
                return "trade.loss"
            return "trade.opened"
        if stream == STREAM_SIGNALS:
            sig = str(data.get("type") or data.get("signal_type") or "signal").lower()
            return f"signal.{sig}"
        if stream == STREAM_RISK_ALERTS:
            return "risk.alert"
        if stream == STREAM_DECISIONS:
            action = str(data.get("action") or "").lower()
            return f"decision.{action}" if action else f"stream:{stream}"
        return f"stream:{stream}"

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
            pnl_val = float(data.get("pnl") or 0.0)
            if pnl_val != 0.0:
                self._session_pnl += pnl_val

        if stream not in self._PUBLISH_STREAMS:
            # Still write heartbeat so the dashboard reflects agent health.
            await self._heartbeat(stream, data)
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

        event_type = str(data.get(FieldName.TYPE) or data.get("notification_type") or stream)
        symbol_key = str(data.get(FieldName.SYMBOL) or data.get("asset") or "")
        trace_key = str(data.get(FieldName.TRACE_ID) or data.get(FieldName.MSG_ID) or "")
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
        msg_id = str(data.get(FieldName.MSG_ID) or redis_id)

        notification = {
            "msg_id": str(uuid.uuid4()),
            "schema_version": DB_SCHEMA_VERSION,
            "source": SOURCE_NOTIFICATION,
            "severity": severity,
            "notification_type": self._build_notification_type(stream, data),
            "stream_source": stream,
            "message": self._build_message(stream, event_type, data),
            "metadata": {"observed_msg_id": msg_id, "stream": stream, "event_type": event_type},
            "timestamp": now_iso,
        }

        try:
            from api.core.writer.safe_writer import SafeWriter

            writer = SafeWriter(AsyncSessionFactory)
            await writer.write_notification(
                notification["msg_id"], STREAM_NOTIFICATIONS, notification
            )
        except Exception:
            log_structured("warning", "notification_persist_failed", stream=stream, exc_info=True)

        await self.bus.publish(STREAM_NOTIFICATIONS, notification)
        log_structured("debug", "notification_forwarded", stream=stream, severity=severity)

        await self._heartbeat(stream, data, event_type=event_type)

    async def _heartbeat(
        self, stream: str, data: dict[str, Any], *, event_type: str | None = None
    ) -> None:
        """Write a heartbeat so the dashboard shows NOTIFICATION_AGENT as ACTIVE.

        Called both when a notification is published and when an event is
        consumed-but-suppressed, so the agent looks alive either way.
        """
        if event_type is None:
            event_type = str(data.get("type") or data.get("notification_type") or stream)
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
        if explicit := data.get("severity"):
            return str(explicit)
        grade = str(data.get("grade") or "")
        if grade == Grade.F:
            return Severity.CRITICAL
        if grade == Grade.D:
            return Severity.URGENT
        # Negative PnL on a closing fill → warning
        if stream == STREAM_TRADE_PERFORMANCE:
            pnl = float(data.get("pnl") or 0.0)
            if pnl < 0:
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
        import uuid as _uuid_mod

        self._challenger_id = str(_uuid_mod.uuid4())[:8]
        super().__init__(
            bus,
            dlq,
            streams=[STREAM_EXECUTIONS, STREAM_TRADE_PERFORMANCE],
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

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == STREAM_TRADE_PERFORMANCE:
            self._pnl_buffer.append(float(data.get("pnl") or 0.0))
            self._fills += 1

        if self._fills > 0 and self._fills % max(int(self._config.get("grade_every", 10)), 1) == 0:
            await self._grade()

        if self._fills >= self._max_fills:
            await self._retire_with_summary()

    async def _grade(self) -> None:
        """Compute a grade for this challenger window and publish results."""
        recent = list(self._pnl_buffer)[-20:]
        if not recent:
            return
        win_rate = sum(1 for p in recent if p > 0) / len(recent)
        avg_pnl = sum(recent) / len(recent)
        grade_result = {
            "challenger_id": self._challenger_id,
            "instance_id": self._instance_id,
            "fills": self._fills,
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 4),
            "config": self._config,
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
                "timestamp": grade_result["timestamp"],
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
            "challenger_id": self._challenger_id,
            "instance_id": self._instance_id,
            "total_fills": self._fills,
            "total_pnl": round(total_pnl, 4),
            "win_rate": round(win_rate, 4),
            "config": self._config,
            "grade_history": self._grade_history[-5:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
                        f"Win rate: {win_rate:.0%}, Total PnL: {total_pnl:+.2f}"
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
