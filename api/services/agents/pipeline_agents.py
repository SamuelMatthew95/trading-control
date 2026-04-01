"""Pipeline agents: GradeAgent, ICUpdater, ReflectionAgent, StrategyProposer, NotificationAgent.

Each agent class focuses exclusively on its domain logic.
Math lives in ``scoring``, prompts in ``prompts``, DB writes in ``db_helpers``,
and the poll loop in ``base``.
"""

from __future__ import annotations

import json
import time as _time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.config import settings
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent
from api.services.agents.db_helpers import (
    persist_factor_ic,
    persist_proposal,
    write_agent_log,
    write_grade_to_db,
)
from api.services.agents.prompts import FALLBACK_REFLECTION, REFLECTION_SYSTEM_PROMPT
from api.services.agents.scoring import (
    GRADE_SEVERITY,
    compute_weighted_score,
    normalize_cost_eff,
    normalize_ic,
    score_to_grade,
    spearman_correlation,
)


async def _write_heartbeat(
    redis: Redis,
    agent_name: str,
    last_event: str,
    event_count: int,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": "ACTIVE",
        "last_event": last_event,
        "event_count": event_count,
        "last_seen": int(_time.time()),
    }
    if extra:
        payload.update(extra)
    await redis.set(
        f"agent:status:{agent_name}",
        json.dumps(payload),
        ex=60,
    )
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO agent_heartbeats
                        (agent_name, status, last_event, event_count, last_seen)
                    VALUES (:name, 'ACTIVE', :last_event, :count, NOW())
                    ON CONFLICT (agent_name) DO UPDATE SET
                        status='ACTIVE', last_event=EXCLUDED.last_event,
                        event_count=EXCLUDED.event_count, last_seen=NOW()
                """),
                {
                    "name": agent_name,
                    "last_event": last_event,
                    "count": event_count,
                },
            )


# ---------------------------------------------------------------------------
# GradeAgent — real 4-dimension performance scoring
# ---------------------------------------------------------------------------


class GradeAgent(MultiStreamAgent):
    """Grades agent performance across 4 weighted dimensions every N fills.

    Score = accuracy×0.35 + IC×0.30 + cost_efficiency×0.20 + latency×0.15
    """

    _state_name = "GRADE_AGENT"

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=["executions", "trade_performance"],
            consumer="grade-agent",
            agent_state=agent_state,
        )
        self._fills = 0
        self._pnl_buffer: deque[float] = deque(maxlen=100)
        self._confidence_buffer: deque[float] = deque(maxlen=100)
        self._consecutive_low_grades = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "trade_performance":
            self._pnl_buffer.append(float(data.get("pnl") or 0.0))
            self._fills += 1
        elif stream == "executions":
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
            "source": "grade_agent",
            "agent": "reasoning_agent",
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

        await self.bus.publish("agent_grades", payload)
        log_structured("info", "grade_computed", grade=grade, score=score, fills=self._fills, ic=ic)

        await write_agent_log(trace_id, "grade", payload)
        await write_grade_to_db(trace_id, payload["score_pct"], payload["metrics"])
        await self._take_grade_action(grade, payload)

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

    def _win_rate(self, lookback_n: int) -> float:
        recent = list(self._pnl_buffer)[-lookback_n:]
        if not recent:
            return 0.5
        return sum(1 for pnl in recent if pnl > 0) / len(recent)

    async def _information_coefficient(self, lookback_n: int) -> float:
        """Spearman correlation between agent confidence and realized returns."""
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
            pass

        confs = list(self._confidence_buffer)[-lookback_n:]
        pnls = list(self._pnl_buffer)[-lookback_n:]
        paired = list(zip(confs, pnls, strict=False))
        if len(paired) < 3:
            return 0.0
        xs, ys = zip(*paired, strict=False)
        return spearman_correlation(list(xs), list(ys))

    async def _cost_efficiency(self, lookback_n: int) -> float:
        """Total PnL divided by total LLM cost for last N fills."""
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

        total_pnl = sum(list(self._pnl_buffer)[-lookback_n:])
        if total_cost < 0.0001:
            return total_pnl * 0.1
        return total_pnl / total_cost

    async def _latency_score(self) -> float:
        """1 - (p95_latency_ms / timeout_ms). Higher score means lower latency."""
        timeout_ms = float(settings.LLM_TIMEOUT_SECONDS) * 1000.0
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
                "notifications",
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": "grade_agent",
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

        if grade == "C":
            await self.bus.publish(
                "proposals",
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": "grade_agent",
                    "type": "proposal",
                    "proposal_type": "signal_weight_reduction",
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

        elif grade == "D":
            self._consecutive_low_grades += 1
            if self._consecutive_low_grades >= int(settings.RETIRE_AFTER_N_GRADES):
                await self.bus.publish(
                    "proposals",
                    {
                        "msg_id": str(uuid.uuid4()),
                        "source": "grade_agent",
                        "type": "proposal",
                        "proposal_type": "agent_suspension",
                        "content": {
                            "action": "suspend_from_live_stream",
                            "consecutive_low_grades": self._consecutive_low_grades,
                            "reason": f"{self._consecutive_low_grades} consecutive D grades",
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

        elif grade == "F":
            self._consecutive_low_grades += 1
            await self.bus.publish(
                "proposals",
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": "grade_agent",
                    "type": "proposal",
                    "proposal_type": "agent_retirement",
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

    _state_name = "IC_UPDATER"

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
            streams=["trade_performance"],
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
        if not trace_id:
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

        await self.redis.set("alpha:ic_weights", json.dumps(weights), ex=90000)

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
                "factor_ic_history",
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": "ic_updater",
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
            "notifications",
            {
                "msg_id": str(uuid.uuid4()),
                "source": "ic_updater",
                "type": "notification",
                "severity": "INFO",
                "notification_type": "ic_update",
                "message": (
                    f"IC weights updated after {self._fills} fills — "
                    f"composite={composite_ic:+.3f} momentum={momentum_ic:+.3f}"
                ),
                "weights": weights,
                "timestamp": now_iso,
            },
        )


# ---------------------------------------------------------------------------
# ReflectionAgent — LLM-based pattern analysis across recent fills
# ---------------------------------------------------------------------------


class ReflectionAgent(MultiStreamAgent):
    """Analyzes recent fills via LLM and generates improvement hypotheses."""

    _state_name = "REFLECTION_AGENT"

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=["trade_performance", "agent_grades", "factor_ic_history"],
            consumer="reflection-agent",
            agent_state=agent_state,
        )
        self._fills = 0
        self._recent_fills: deque[dict[str, Any]] = deque(maxlen=50)
        self._recent_grades: deque[dict[str, Any]] = deque(maxlen=20)
        self._recent_ic: deque[dict[str, Any]] = deque(maxlen=20)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "trade_performance":
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
        elif stream == "agent_grades":
            self._recent_grades.append(
                {
                    "grade": data.get("grade"),
                    "score": data.get("score"),
                    "metrics": data.get("metrics", {}),
                    "timestamp": data.get("timestamp"),
                }
            )
        elif stream == "factor_ic_history":
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
            budget_used = int(await redis.get(f"llm:tokens:{today}") or 0)
            if budget_used >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
                log_structured("warning", "reflection_skipped_budget_exceeded", trace_id=trace_id)
                await self.bus.publish(
                    "notifications",
                    {
                        "msg_id": str(uuid.uuid4()),
                        "source": "reflection_agent",
                        "type": "notification",
                        "severity": "WARNING",
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
                await redis.incrby(f"llm:tokens:{today}", tokens_used)
                await redis.incrbyfloat(f"llm:cost:{today}", cost_usd)

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

        reflection_payload: dict[str, Any] = {
            "msg_id": str(uuid.uuid4()),
            "source": "reflection_agent",
            "type": "reflection_output",
            "trace_id": trace_id,
            "fills_analyzed": self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **reflection_data,
        }

        await self.bus.publish("reflection_outputs", reflection_payload)
        await write_agent_log(trace_id, "reflection", reflection_payload)
        await self.bus.publish(
            "notifications",
            {
                "msg_id": str(uuid.uuid4()),
                "source": "reflection_agent",
                "type": "notification",
                "severity": "INFO",
                "notification_type": "reflection",
                "message": reflection_data.get("summary", "Reflection completed."),
                "hypothesis_count": len(reflection_data.get("hypotheses", [])),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

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

    _state_name = "STRATEGY_PROPOSER"

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=["reflection_outputs"],
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

        for hypothesis in strong:
            proposal = self._build_proposal(hypothesis, data, now_iso)

            if proposal["proposal_type"] == "code_change":
                await self.bus.publish(
                    "github_prs",
                    {
                        "msg_id": str(uuid.uuid4()),
                        "source": "strategy_proposer",
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

            await self.bus.publish("proposals", proposal)
            await persist_proposal(proposal)
            await self.bus.publish(
                "notifications",
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": "strategy_proposer",
                    "type": "notification",
                    "severity": "INFO",
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

    def _build_proposal(
        self, hypothesis: dict[str, Any], reflection_data: dict[str, Any], now_iso: str
    ) -> dict[str, Any]:
        hyp_type = str(hypothesis.get("type") or "parameter").lower()
        description = str(hypothesis.get("description") or "")
        confidence = float(hypothesis.get("confidence") or 0)

        base = {
            "msg_id": str(uuid.uuid4()),
            "source": "strategy_proposer",
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

        if hyp_type == "parameter":
            base["proposal_type"] = "parameter_change"
            base["content"]["implementation"] = "db_update"
            base["content"]["note"] = "Update config parameter via DB — no deploy required."
        elif hyp_type == "rule":
            base["proposal_type"] = "code_change"
            base["content"]["implementation"] = "github_pr"
            base["content"]["note"] = "Rule change requires PR review and deploy."
        else:
            base["proposal_type"] = "regime_adjustment"
            base["content"]["regime_context"] = reflection_data.get("regime_edge", {})

        return base


# ---------------------------------------------------------------------------
# NotificationAgent — classify and route all system events
# ---------------------------------------------------------------------------

_STREAM_SEVERITY: dict[str, str] = {
    "risk_alerts": "URGENT",
    "proposals": "INFO",
    "agent_grades": "INFO",
    "reflection_outputs": "INFO",
    "factor_ic_history": "INFO",
    "executions": "INFO",
    "trade_performance": "INFO",
    "orders": "INFO",
    "signals": "INFO",
    "market_ticks": "INFO",
    "agent_logs": "INFO",
}


class NotificationAgent(MultiStreamAgent):
    """Observes all output streams, deduplicates events, and persists notifications."""

    _state_name = "NOTIFICATION_AGENT"

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
                "market_ticks",
                "signals",
                "orders",
                "executions",
                "agent_logs",
                "trade_performance",
                "agent_grades",
                "factor_ic_history",
                "reflection_outputs",
                "proposals",
            ],
            consumer="notification-agent",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self._dedup_window_secs = 60

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "notifications":
            return

        event_type = str(data.get("type") or data.get("notification_type") or stream)
        dedup_key = f"notif:dedup:{stream}:{event_type}"

        if await self.redis.exists(dedup_key):
            return
        await self.redis.setex(dedup_key, self._dedup_window_secs, "1")

        now_iso = datetime.now(timezone.utc).isoformat()
        severity = self._classify_severity(stream, data)
        msg_id = str(data.get("msg_id") or redis_id)

        notification = {
            "msg_id": str(uuid.uuid4()),
            "schema_version": "v3",
            "source": "notification_agent",
            "severity": severity,
            "notification_type": f"stream:{stream}",
            "message": f"Event on {stream}: {event_type}",
            "metadata": {"observed_msg_id": msg_id, "stream": stream, "event_type": event_type},
            "timestamp": now_iso,
        }

        try:
            from api.core.writer.safe_writer import SafeWriter

            writer = SafeWriter(AsyncSessionFactory)
            await writer.write_notification(notification["msg_id"], "notifications", notification)
        except Exception:
            log_structured("warning", "notification_persist_failed", stream=stream, exc_info=True)

        await self.bus.publish("notifications", notification)
        log_structured("debug", "notification_forwarded", stream=stream, severity=severity)

    def _classify_severity(self, stream: str, data: dict[str, Any]) -> str:
        if explicit := data.get("severity"):
            return str(explicit)
        grade = str(data.get("grade") or "")
        if grade == "F":
            return "CRITICAL"
        if grade == "D":
            return "URGENT"
        return _STREAM_SEVERITY.get(stream, "INFO")
