"""Circuit breaker for the live strategy — emergency, fail-closed rollback.

Pure trip-decision logic (``evaluate``) plus a thin action that, when tripped,
flips the existing kill switch and rolls the strategy registry back to the
previous live version. No new infrastructure — it reuses
``REDIS_KEY_KILL_SWITCH`` and ``StrategyRegistry.rollback()``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis

from api.constants import (
    CIRCUIT_BREAKER_MAX_CONSECUTIVE_FAILURES,
    CIRCUIT_BREAKER_MAX_DIVERGENCE,
    CIRCUIT_BREAKER_MAX_DRAWDOWN_PCT,
    CIRCUIT_BREAKER_MAX_LATENCY_MS,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_KILL_SWITCH_UPDATED_AT,
)
from api.observability import log_structured
from api.services.strategy_registry import StrategyRegistry, get_strategy_registry


@dataclass(frozen=True)
class BreakerInputs:
    """Live health signals evaluated each cycle."""

    drawdown_pct: float = 0.0
    consecutive_failures: int = 0
    divergence_score: float = 0.0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class TripDecision:
    """Whether the breaker should trip, and the reasons why."""

    tripped: bool
    reasons: tuple[str, ...] = ()


def evaluate(inputs: BreakerInputs) -> TripDecision:
    """Pure decision — no IO. Trips if ANY safety threshold is breached."""
    reasons: list[str] = []
    if inputs.drawdown_pct >= CIRCUIT_BREAKER_MAX_DRAWDOWN_PCT:
        reasons.append(
            f"drawdown {inputs.drawdown_pct:.0%} >= {CIRCUIT_BREAKER_MAX_DRAWDOWN_PCT:.0%}"
        )
    if inputs.consecutive_failures >= CIRCUIT_BREAKER_MAX_CONSECUTIVE_FAILURES:
        reasons.append(
            f"{inputs.consecutive_failures} consecutive failures "
            f">= {CIRCUIT_BREAKER_MAX_CONSECUTIVE_FAILURES}"
        )
    if inputs.divergence_score >= CIRCUIT_BREAKER_MAX_DIVERGENCE:
        reasons.append(
            f"divergence {inputs.divergence_score:.2f} >= {CIRCUIT_BREAKER_MAX_DIVERGENCE}"
        )
    if inputs.latency_ms >= CIRCUIT_BREAKER_MAX_LATENCY_MS:
        reasons.append(
            f"latency {inputs.latency_ms:.0f}ms >= {CIRCUIT_BREAKER_MAX_LATENCY_MS:.0f}ms"
        )
    return TripDecision(tripped=bool(reasons), reasons=tuple(reasons))


class CircuitBreaker:
    """Evaluates live health and, on a trip, fails closed: kill switch + rollback."""

    def __init__(self, redis: Redis, registry: StrategyRegistry | None = None) -> None:
        self.redis = redis
        self.registry = registry or get_strategy_registry()

    async def check(self, inputs: BreakerInputs) -> TripDecision:
        """Evaluate inputs and trip if needed. Returns the decision."""
        decision = evaluate(inputs)
        if decision.tripped:
            await self.trip(decision)
        return decision

    async def trip(self, decision: TripDecision) -> None:
        """Fail closed: set the kill switch and roll back the live strategy."""
        await self.redis.set(REDIS_KEY_KILL_SWITCH, "1")
        await self.redis.set(REDIS_KEY_KILL_SWITCH_UPDATED_AT, str(time.time()))
        restored = self.registry.rollback()
        log_structured(
            "error",
            "circuit_breaker_tripped",
            reasons=list(decision.reasons),
            rolled_back_to=restored.version_id if restored else None,
        )
