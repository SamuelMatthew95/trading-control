"""Pipeline agents with real scoring, IC, reflection, and proposal logic."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.config import settings
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_state import AgentStateRegistry

# ---------------------------------------------------------------------------
# Grade thresholds and weights (from config with fallback defaults)
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS = [
    ("A+", 0.90),
    ("A", 0.80),
    ("B", 0.65),
    ("C", 0.50),
    ("D", 0.35),
    ("F", 0.0),
]

_GRADE_SEVERITY = {
    "A+": None,
    "A": None,
    "B": "INFO",
    "C": "WARNING",
    "D": "URGENT",
    "F": "CRITICAL",
}

# Reflection LLM system prompt
_REFLECTION_SYSTEM_PROMPT = (
    "You are a trading performance analyst. Analyze the provided trade data and return ONLY "
    "valid JSON with these exact keys: winning_factors (list of strings), losing_factors "
    "(list of strings), hypotheses (list of objects with keys: description, confidence 0-1, "
    "type which must be 'parameter' or 'rule' or 'regime'), regime_edge (object with keys: "
    "current_regime and recommendation), time_of_day_patterns (object with keys: best_hours "
    "as list of ints, worst_hours as list of ints), summary (one-line string). "
    "Return ONLY the JSON object, no markdown fences."
)

_FALLBACK_REFLECTION = {
    "winning_factors": ["composite_score"],
    "losing_factors": [],
    "hypotheses": [],
    "regime_edge": {"current_regime": "unknown", "recommendation": "continue monitoring"},
    "time_of_day_patterns": {"best_hours": [], "worst_hours": []},
    "summary": "Insufficient data for analysis.",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _spearman_correlation(xs: list[float], ys: list[float]) -> float:
    """Compute Spearman rank correlation without external dependencies."""
    n = len(xs)
    if n < 3:
        return 0.0

    def _rank(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda kv: kv[1])
        ranks = [0.0] * n
        for rank_pos, (orig_idx, _) in enumerate(indexed):
            ranks[orig_idx] = float(rank_pos + 1)
        return ranks

    rank_x = _rank(xs)
    rank_y = _rank(ys)
    d_sq_sum = sum((rx - ry) ** 2 for rx, ry in zip(rank_x, rank_y, strict=False))
    denom = n * (n**2 - 1)
    return 1.0 - (6.0 * d_sq_sum / denom) if denom else 0.0


def _score_to_grade(score: float) -> str:
    for letter, threshold in _GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"


def _normalize_ic(raw_ic: float) -> float:
    """Map Spearman [-1, 1] to [0, 1]."""
    return (raw_ic + 1.0) / 2.0


def _normalize_cost_eff(pnl_per_dollar: float) -> float:
    """Map pnl/cost ratio to [0, 1]. 0 cost → 0.5 (neutral), +10 → 1.0, -10 → 0.0."""
    return min(max((pnl_per_dollar + 10.0) / 20.0, 0.0), 1.0)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class MultiStreamAgent:
    """Consumes multiple Redis streams and calls process() for each message."""

    _state_name: str = ""  # Override in subclass to enable state tracking

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        *,
        streams: list[str],
        consumer: str,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        self.bus = bus
        self.dlq = dlq
        self.streams = streams
        self.consumer = consumer
        self.agent_state = agent_state
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"agent:{self.consumer}")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _run(self) -> None:
        while self._running:
            for stream in self.streams:
                messages = await self.bus.consume(
                    stream,
                    group=DEFAULT_GROUP,
                    consumer=self.consumer,
                    count=20,
                    block_ms=100,
                )
                for redis_id, data in messages:
                    try:
                        await self.process(stream, redis_id, data)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                        # Update agent state on every processed message
                        if self.agent_state and self._state_name:
                            self.agent_state.record_event(
                                self._state_name, task=f"{stream}:{data.get('type', 'event')}"
                            )
                    except Exception as exc:  # noqa: BLE001
                        log_structured(
                            "error",
                            "pipeline_agent_process_failed",
                            agent=self.consumer,
                            stream=stream,
                            exc_info=True,
                        )
                        await self.dlq.push(stream, redis_id, data, error=str(exc), retries=1)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
            await asyncio.sleep(0.05)  # Agent processing throttle - allowed


# ---------------------------------------------------------------------------
# GradeAgent — real performance scoring
# ---------------------------------------------------------------------------


class GradeAgent(MultiStreamAgent):
    """Grades agent performance across 4 weighted dimensions every N fills."""

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
        # Rolling buffers (in-memory) for fast metric computation
        self._pnl_buffer: deque[float] = deque(maxlen=100)
        self._confidence_buffer: deque[float] = deque(maxlen=100)
        # Track consecutive D-or-below grades for auto-retirement
        self._consecutive_low_grades = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "trade_performance":
            pnl = float(data.get("pnl") or 0.0)
            self._pnl_buffer.append(pnl)
            self._fills += 1

        if stream == "executions":
            # Capture confidence from trace_id → agent_runs correlation
            confidence = float(data.get("confidence") or 0.5)
            self._confidence_buffer.append(confidence)

        trigger = max(int(settings.GRADE_EVERY_N_FILLS), 1)
        if self._fills == 0 or self._fills % trigger != 0:
            return

        await self._compute_and_publish_grade()

    async def _compute_and_publish_grade(self) -> None:
        trace_id = f"grade_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        lookback_n = int(settings.GRADE_LOOKBACK_N)

        try:
            accuracy = self._compute_accuracy(lookback_n)
            ic = await self._compute_ic(lookback_n)
            cost_eff = await self._compute_cost_efficiency(lookback_n)
            latency = await self._compute_latency_score()
        except Exception:
            log_structured("error", "grade_metric_computation_failed", exc_info=True)
            return

        ic_norm = _normalize_ic(ic)
        cost_norm = _normalize_cost_eff(cost_eff)

        score = (
            accuracy * float(settings.GRADE_WEIGHT_ACCURACY)
            + ic_norm * float(settings.GRADE_WEIGHT_IC)
            + cost_norm * float(settings.GRADE_WEIGHT_COST)
            + latency * float(settings.GRADE_WEIGHT_LATENCY)
        )
        score = round(min(max(score, 0.0), 1.0), 4)
        grade = _score_to_grade(score)

        grade_payload = {
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

        await self.bus.publish("agent_grades", grade_payload)
        log_structured(
            "info",
            "grade_computed",
            grade=grade,
            score=score,
            fills=self._fills,
            accuracy=accuracy,
            ic=ic,
        )

        # Write to agent_logs for audit trail (uses old schema that reasoning_agent also uses)
        await self._write_grade_log(trace_id, grade_payload)

        # Automatic actions based on grade
        await self._take_grade_action(grade, grade_payload)

    def _compute_accuracy(self, lookback_n: int) -> float:
        """Win rate of last N fills."""
        recent = list(self._pnl_buffer)[-lookback_n:]
        if not recent:
            return 0.5  # Neutral default when no data
        wins = sum(1 for pnl in recent if pnl > 0)
        return wins / len(recent)

    async def _compute_ic(self, lookback_n: int) -> float:
        """Spearman correlation between agent confidence and realized returns.

        Tries to join agent_runs.confidence with trade_performance.pnl via
        ordering. Falls back to buffer correlation when DB join unavailable.
        """
        # Try DB join via trace_id through orders table
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
                    confidences = [float(r[0]) for r in rows if r[0] is not None]
                    pnls = [float(r[1]) for r in rows if r[1] is not None]
                    if len(confidences) >= 3:
                        return _spearman_correlation(confidences, pnls)
        except Exception:
            pass  # Fall through to buffer-based approximation

        # Approximate: correlate in-memory confidence buffer with pnl buffer
        confs = list(self._confidence_buffer)[-lookback_n:]
        pnls = list(self._pnl_buffer)[-lookback_n:]
        paired = list(zip(confs, pnls, strict=False))
        if len(paired) < 3:
            return 0.0
        xs, ys = zip(*paired, strict=False)
        return _spearman_correlation(list(xs), list(ys))

    async def _compute_cost_efficiency(self, lookback_n: int) -> float:
        """Total PnL / total LLM cost. Returns PnL-per-dollar."""
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT COALESCE(SUM(cost_usd), 0) AS total_cost
                        FROM (
                            SELECT cost_usd FROM agent_runs
                            ORDER BY created_at DESC
                            LIMIT :n
                        ) sub
                    """),
                    {"n": lookback_n},
                )
                total_cost = float(result.scalar() or 0.0)
        except Exception:
            total_cost = 0.0

        total_pnl = sum(list(self._pnl_buffer)[-lookback_n:])
        if total_cost < 0.0001:
            # Free LLM (Groq) — cost efficiency is purely PnL-based
            return total_pnl * 0.1  # scale: $1 PnL → 0.1 efficiency units
        return total_pnl / total_cost

    async def _compute_latency_score(self) -> float:
        """1 - (p95_latency_ms / timeout_ms). Higher is better."""
        timeout_ms = float(settings.LLM_TIMEOUT_SECONDS) * 1000.0
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
                        FROM agent_runs
                        WHERE latency_ms > 0
                        AND created_at > NOW() - INTERVAL '7 days'
                    """)
                )
                p95 = result.scalar()
                if p95 is None:
                    return 0.8  # Default when no data: assume good latency
                return max(0.0, 1.0 - (float(p95) / timeout_ms))
        except Exception:
            return 0.8

    async def _write_grade_log(self, trace_id: str, payload: dict[str, Any]) -> None:
        """Persist grade to agent_logs and agent_grades tables."""
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text("""
                        INSERT INTO agent_logs (trace_id, log_type, payload)
                        VALUES (:trace_id, 'grade', CAST(:payload AS JSONB))
                    """),
                    {"trace_id": trace_id, "payload": json.dumps(payload, default=str)},
                )
                await session.execute(
                    text("""
                        INSERT INTO agent_grades
                            (grade_type, score, metrics, trace_id, schema_version, source)
                        VALUES ('pipeline', :score, CAST(:metrics AS JSONB),
                                :trace_id, 'v3', 'grade_agent')
                    """),
                    {
                        "score": payload.get("score_pct", 0.0),
                        "metrics": json.dumps(payload.get("metrics", {}), default=str),
                        "trace_id": trace_id,
                    },
                )
                await session.commit()
        except Exception:
            log_structured("warning", "grade_log_write_failed", exc_info=True)

    async def _take_grade_action(self, grade: str, payload: dict[str, Any]) -> None:
        """Execute automatic consequences based on grade threshold."""
        severity = _GRADE_SEVERITY.get(grade)
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
            # B or better — reset consecutive low grade counter
            self._consecutive_low_grades = 0


# ---------------------------------------------------------------------------
# ICUpdater — real Spearman factor reweighting
# ---------------------------------------------------------------------------


class ICUpdater(MultiStreamAgent):
    """Reweights alpha factors based on Spearman IC against realized returns."""

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
        # Rolling buffer: (composite_score, pnl) pairs for IC computation
        self._score_pnl_buffer: deque[tuple[float, float]] = deque(maxlen=200)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._fills += 1

        # Accumulate (composite_score, pnl) pairs from trade_performance events.
        # composite_score comes from the signal that drove this trade (stored in
        # the event as pnl_percent proxy — we'll enrich this when agent_runs join works).
        pnl = float(data.get("pnl") or 0.0)
        # The trace_id lets us look up the originating signal's composite_score
        composite_score = await self._fetch_signal_composite(data.get("trace_id"))
        self._score_pnl_buffer.append((composite_score, pnl))

        trigger = max(int(settings.IC_UPDATE_EVERY_N_FILLS), 1)
        if self._fills % trigger != 0:
            return

        await self._recompute_and_publish()

    async def _fetch_signal_composite(self, trace_id: str | None) -> float:
        """Look up the composite_score from agent_runs for this trace_id."""
        if not trace_id:
            return 0.5
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT (signal_data::jsonb->>'composite_score')::float
                        FROM agent_runs
                        WHERE trace_id = :trace_id
                        LIMIT 1
                    """),
                    {"trace_id": trace_id},
                )
                val = result.scalar()
                return float(val) if val is not None else 0.5
        except Exception:
            return 0.5

    async def _recompute_and_publish(self) -> None:
        """Compute Spearman IC per factor, zero out weak factors, normalize weights."""
        lookback_n = min(len(self._score_pnl_buffer), 100)
        recent = list(self._score_pnl_buffer)[-lookback_n:]

        if len(recent) < 3:
            log_structured("info", "ic_updater_insufficient_data", fills=self._fills)
            return

        scores = [pair[0] for pair in recent]
        pnls = [pair[1] for pair in recent]

        # Compute IC for "composite_score" factor
        composite_ic = _spearman_correlation(scores, pnls)

        # Compute IC for a "momentum" factor: proxy = sign(score - 0.5)
        momentum_signals = [1.0 if s > 0.5 else -1.0 for s in scores]
        momentum_ic = _spearman_correlation(momentum_signals, pnls)

        raw_factors: dict[str, float] = {
            "composite_score": composite_ic,
            "momentum": momentum_ic,
        }

        threshold = float(settings.IC_ZERO_THRESHOLD)

        # Zero out factors below IC threshold
        active: dict[str, float] = {
            factor: max(ic, 0.0) for factor, ic in raw_factors.items() if abs(ic) > threshold
        }

        # Normalize remaining weights to sum to 1.0
        total = sum(active.values())
        if total <= 0:
            weights: dict[str, float] = {"composite_score": 1.0}
        else:
            weights = {k: round(v / total, 6) for k, v in active.items()}

        # Write weights to Redis with 25-hour TTL
        await self.redis.set("alpha:ic_weights", json.dumps(weights), ex=90000)

        log_structured(
            "info",
            "ic_weights_updated",
            weights=weights,
            composite_ic=composite_ic,
            momentum_ic=momentum_ic,
            fills=self._fills,
        )

        # Write to factor_ic_history table and stream
        now_iso = datetime.now(timezone.utc).isoformat()
        for factor, ic_val in raw_factors.items():
            history_payload = {
                "msg_id": str(uuid.uuid4()),
                "source": "ic_updater",
                "type": "ic_update",
                "factor_name": factor,
                "ic_score": round(ic_val, 6),
                "weight": weights.get(factor, 0.0),
                "fills": self._fills,
                "timestamp": now_iso,
            }
            await self.bus.publish("factor_ic_history", history_payload)
            await self._persist_factor_ic(factor, ic_val, now_iso)

        # Publish summary to notifications
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

    async def _persist_factor_ic(self, factor: str, ic_score: float, computed_at: str) -> None:
        """Persist IC score to factor_ic_history table."""
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text("""
                        INSERT INTO factor_ic_history (factor_name, ic_score, computed_at)
                        VALUES (:factor_name, :ic_score, :computed_at)
                    """),
                    {
                        "factor_name": factor,
                        "ic_score": ic_score,
                        "computed_at": computed_at,
                    },
                )
                await session.commit()
        except Exception:
            log_structured("warning", "factor_ic_persist_failed", factor=factor, exc_info=True)


# ---------------------------------------------------------------------------
# ReflectionAgent — real LLM-based pattern analysis
# ---------------------------------------------------------------------------


class ReflectionAgent(MultiStreamAgent):
    """Finds patterns in recent fills and generates improvement hypotheses via LLM."""

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
        # Rolling context windows passed to the LLM
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

        # Only reflect when we have minimum data
        if len(self._recent_fills) < 3:
            return

        await self._run_reflection()

    async def _run_reflection(self) -> None:
        trace_id = f"reflection_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

        # Check token budget before calling LLM
        today = datetime.now(timezone.utc).date().isoformat()
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
            redis = None  # proceed without budget check

        prompt = self._build_reflection_prompt()
        reflection_data: dict[str, Any] = {}

        try:
            from api.services.llm_router import call_llm_with_system

            raw_text, tokens_used, cost_usd = await call_llm_with_system(
                prompt, _REFLECTION_SYSTEM_PROMPT, trace_id
            )
            reflection_data = self._parse_reflection_response(raw_text)

            # Track token usage
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
                "warning",
                "reflection_llm_failed_using_fallback",
                exc_info=True,
                trace_id=trace_id,
            )
            reflection_data = dict(_FALLBACK_REFLECTION)
            reflection_data["summary"] = f"LLM unavailable after {self._fills} fills."

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

        # Persist to agent_logs
        await self._persist_reflection_log(trace_id, reflection_payload)

        # Notify summary
        summary = reflection_data.get("summary", "Reflection completed.")
        await self.bus.publish(
            "notifications",
            {
                "msg_id": str(uuid.uuid4()),
                "source": "reflection_agent",
                "type": "notification",
                "severity": "INFO",
                "notification_type": "reflection",
                "message": summary,
                "hypothesis_count": len(reflection_data.get("hypotheses", [])),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _build_reflection_prompt(self) -> str:
        recent_fills = list(self._recent_fills)[-20:]
        recent_grades = list(self._recent_grades)[-5:]
        recent_ic = list(self._recent_ic)[-5:]

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
                "recent_grades": recent_grades,
                "recent_ic_changes": recent_ic,
            },
            default=str,
        )

    def _parse_reflection_response(self, raw_text: str) -> dict[str, Any]:
        """Parse LLM JSON response, fall back to defaults on parse error."""
        text = raw_text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text[3:]
            if "\n" in text:
                first, rest = text.split("\n", 1)
                if first.strip() in {"json", "JSON", ""}:
                    text = rest
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].strip()
        try:
            parsed = json.loads(text)
            # Validate required keys present
            for key in ("winning_factors", "losing_factors", "hypotheses", "summary"):
                if key not in parsed:
                    parsed[key] = _FALLBACK_REFLECTION.get(key, [])
            return parsed
        except json.JSONDecodeError:
            log_structured("warning", "reflection_json_parse_failed", raw=text[:200])
            return dict(_FALLBACK_REFLECTION)

    async def _persist_reflection_log(self, trace_id: str, payload: dict[str, Any]) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text("""
                        INSERT INTO agent_logs (trace_id, log_type, payload)
                        VALUES (:trace_id, 'reflection', CAST(:payload AS JSONB))
                    """),
                    {"trace_id": trace_id, "payload": json.dumps(payload, default=str)},
                )
                await session.commit()
        except Exception:
            log_structured("warning", "reflection_log_persist_failed", exc_info=True)


# ---------------------------------------------------------------------------
# StrategyProposer — turn reflection hypotheses into concrete proposals
# ---------------------------------------------------------------------------


class StrategyProposer(MultiStreamAgent):
    """Converts reflection hypotheses into typed proposals requiring approval."""

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

        # Filter to only strong hypotheses
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
            hyp_type = str(hypothesis.get("type") or "parameter").lower()
            description = str(hypothesis.get("description") or "")
            confidence = float(hypothesis.get("confidence") or 0)

            if hyp_type == "parameter":
                # Parameter change — no code deploy needed
                proposal = {
                    "msg_id": str(uuid.uuid4()),
                    "source": "strategy_proposer",
                    "type": "proposal",
                    "proposal_type": "parameter_change",
                    "requires_approval": True,
                    "content": {
                        "description": description,
                        "confidence": confidence,
                        "hypothesis_type": hyp_type,
                        "implementation": "db_update",
                        "note": "Update config parameter via DB — no deploy required.",
                    },
                    "reflection_trace_id": data.get("trace_id"),
                    "timestamp": now_iso,
                }
            elif hyp_type == "rule":
                # Rule change — requires PR
                proposal = {
                    "msg_id": str(uuid.uuid4()),
                    "source": "strategy_proposer",
                    "type": "proposal",
                    "proposal_type": "code_change",
                    "requires_approval": True,
                    "content": {
                        "description": description,
                        "confidence": confidence,
                        "hypothesis_type": hyp_type,
                        "implementation": "github_pr",
                        "note": "Rule change requires PR review and deploy.",
                    },
                    "reflection_trace_id": data.get("trace_id"),
                    "timestamp": now_iso,
                }
                # Signal that a PR should be opened
                await self.bus.publish(
                    "github_prs",
                    {
                        "msg_id": str(uuid.uuid4()),
                        "source": "strategy_proposer",
                        "type": "pr_request",
                        "title": f"Strategy rule proposal: {description[:80]}",
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
            else:
                # Regime-level proposal
                proposal = {
                    "msg_id": str(uuid.uuid4()),
                    "source": "strategy_proposer",
                    "type": "proposal",
                    "proposal_type": "regime_adjustment",
                    "requires_approval": True,
                    "content": {
                        "description": description,
                        "confidence": confidence,
                        "hypothesis_type": hyp_type,
                        "regime_context": data.get("regime_edge", {}),
                    },
                    "reflection_trace_id": data.get("trace_id"),
                    "timestamp": now_iso,
                }

            await self.bus.publish("proposals", proposal)
            await self._persist_proposal(proposal)
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
                        f"(confidence={confidence:.0%}): {description[:100]}"
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

    async def _persist_proposal(self, proposal: dict[str, Any]) -> None:
        """Persist proposal to agent_logs for dashboard query and audit trail."""
        trace_id = (
            proposal.get("reflection_trace_id") or proposal.get("msg_id") or str(uuid.uuid4())
        )
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    text("""
                        INSERT INTO agent_logs (trace_id, log_type, payload)
                        VALUES (:trace_id, 'proposal', CAST(:payload AS JSONB))
                    """),
                    {"trace_id": trace_id, "payload": json.dumps(proposal, default=str)},
                )
                await session.commit()
        except Exception:
            log_structured("warning", "proposal_persist_failed", exc_info=True)


# ---------------------------------------------------------------------------
# NotificationAgent — classify and route all system events
# ---------------------------------------------------------------------------


class NotificationAgent(MultiStreamAgent):
    """Observes all output streams, deduplicates, and persists notifications."""

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
        # Deduplication: track (stream, event_type) → last_seen timestamp
        self._dedup_window_secs = 60

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "notifications":
            return  # Don't re-process our own notifications

        event_type = str(data.get("type") or data.get("notification_type") or stream)
        dedup_key = f"notif:dedup:{stream}:{event_type}"

        # Deduplication: skip if same event type seen within window
        already_seen = await self.redis.exists(dedup_key)
        if already_seen:
            return
        await self.redis.setex(dedup_key, self._dedup_window_secs, "1")

        msg_id = str(data.get("msg_id") or redis_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Determine severity from stream
        severity = self._classify_severity(stream, data)

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

        # Persist notification to DB
        try:
            from api.core.writer.safe_writer import SafeWriter

            writer = SafeWriter(AsyncSessionFactory)
            await writer.write_notification(notification["msg_id"], "notifications", notification)
        except Exception:
            log_structured("warning", "notification_persist_failed", stream=stream, exc_info=True)

        await self.bus.publish("notifications", notification)
        log_structured("debug", "notification_forwarded", stream=stream, severity=severity)

    def _classify_severity(self, stream: str, data: dict[str, Any]) -> str:
        """Map stream + event content to notification severity."""
        # Inherit severity if already set on the event
        if explicit := data.get("severity"):
            return str(explicit)

        grade = str(data.get("grade") or "")
        if grade == "F":
            return "CRITICAL"
        if grade == "D":
            return "URGENT"

        severity_map = {
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
        return severity_map.get(stream, "INFO")
