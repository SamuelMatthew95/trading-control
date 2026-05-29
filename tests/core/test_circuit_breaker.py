"""Tests for the circuit breaker — pure trip decision + fail-closed action."""

from __future__ import annotations

import pytest

from api.constants import (
    CIRCUIT_BREAKER_MAX_CONSECUTIVE_FAILURES,
    CIRCUIT_BREAKER_MAX_DRAWDOWN_PCT,
    REDIS_KEY_KILL_SWITCH,
    StrategyStatus,
)
from api.services.circuit_breaker import BreakerInputs, CircuitBreaker, evaluate
from api.services.strategy_registry import StrategyRegistry

_TO_LIVE = (
    StrategyStatus.BACKTESTED,
    StrategyStatus.SHADOW,
    StrategyStatus.CANARY,
    StrategyStatus.LIVE,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, **kwargs) -> None:
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)


def test_evaluate_healthy_does_not_trip():
    assert evaluate(BreakerInputs()).tripped is False


def test_evaluate_trips_on_drawdown():
    decision = evaluate(BreakerInputs(drawdown_pct=CIRCUIT_BREAKER_MAX_DRAWDOWN_PCT + 0.01))
    assert decision.tripped is True
    assert any("drawdown" in r for r in decision.reasons)


def test_evaluate_trips_on_consecutive_failures():
    decision = evaluate(
        BreakerInputs(consecutive_failures=CIRCUIT_BREAKER_MAX_CONSECUTIVE_FAILURES)
    )
    assert decision.tripped is True


@pytest.mark.asyncio
async def test_trip_sets_kill_switch_and_rolls_back():
    reg = StrategyRegistry()
    v1 = reg.register({"a": 1})
    for stage in _TO_LIVE:
        reg.transition(v1.version_id, stage)
    v2 = reg.register({"a": 2})
    for stage in _TO_LIVE:
        reg.transition(v2.version_id, stage)

    redis = _FakeRedis()
    breaker = CircuitBreaker(redis, registry=reg)
    decision = await breaker.check(BreakerInputs(drawdown_pct=0.99))

    assert decision.tripped is True
    assert redis.store[REDIS_KEY_KILL_SWITCH] == "1"
    assert reg.current_live().version_id == v1.version_id  # rolled back to previous live
