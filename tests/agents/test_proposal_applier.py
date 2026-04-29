"""Tests for ProposalApplier — closes the learning loop.

Each proposal type maps to a specific Redis control-plane key. These tests
verify the mapping is correct and that ExecutionEngine + ReasoningAgent
will see the values that ProposalApplier writes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import (
    AGENT_REASONING,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    SIGNAL_WEIGHT_REDUCTION_FACTOR,
    SIGNAL_WEIGHT_SCALE_MIN,
    FieldName,
    ProposalType,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.proposal_applier import ProposalApplier

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal in-memory Redis substitute that captures set() calls."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = dict(initial or {})
        self._ttl: dict[str, int] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = str(value)
        if ex is not None:
            self._ttl[key] = ex
        self.set_calls.append((key, str(value), ex))
        return True


def _make_applier(redis: _FakeRedis) -> ProposalApplier:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return ProposalApplier(bus=bus, dlq=dlq, redis_client=redis)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_signal_weight_reduction_multiplies_scale(monkeypatch):
    """Grade C proposal multiplies the scale by SIGNAL_WEIGHT_REDUCTION_FACTOR."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis({REDIS_KEY_SIGNAL_WEIGHT_SCALE: "1.0"})
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.SIGNAL_WEIGHT_REDUCTION,
        FieldName.CONTENT: {FieldName.ACTION: "reduce_signal_weight"},
    }
    await applier.process("proposals", "1-0", proposal)

    new_scale = float(await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE))
    assert new_scale == pytest.approx(SIGNAL_WEIGHT_REDUCTION_FACTOR, rel=1e-6)


async def test_signal_weight_reduction_floors_at_minimum(monkeypatch):
    """Repeated reductions never drop below SIGNAL_WEIGHT_SCALE_MIN."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis({REDIS_KEY_SIGNAL_WEIGHT_SCALE: "0.06"})
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.SIGNAL_WEIGHT_REDUCTION,
        FieldName.CONTENT: {FieldName.ACTION: "reduce_signal_weight"},
    }
    await applier.process("proposals", "1-0", proposal)
    new_scale = float(await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE))
    assert new_scale == pytest.approx(SIGNAL_WEIGHT_SCALE_MIN, abs=1e-6)


async def test_agent_suspension_sets_redis_key(monkeypatch):
    """Grade D suspension writes learning:agent_suspended:{name} with TTL."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.AGENT_SUSPENSION,
        FieldName.CONTENT: {
            FieldName.ACTION: "suspend_from_live_stream",
            FieldName.AGENT_NAME: AGENT_REASONING,
        },
    }
    await applier.process("proposals", "1-0", proposal)

    key = REDIS_KEY_AGENT_SUSPENDED.format(name=AGENT_REASONING)
    # Mirrors the kill-switch contract — value is "1" while suspended.
    assert await redis.get(key) == "1"
    # Verify a TTL was supplied so the suspension auto-expires
    assert any(call[0] == key and call[2] is not None for call in redis.set_calls)


async def test_agent_retirement_pauses_trading(monkeypatch):
    """Grade F retirement sets learning:trading_paused = '1' with reason."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.AGENT_RETIREMENT,
        FieldName.CONTENT: {
            FieldName.ACTION: "retire_immediately",
            FieldName.REASON: "Grade F: 12% score",
        },
    }
    await applier.process("proposals", "1-0", proposal)

    assert await redis.get(REDIS_KEY_TRADING_PAUSED) == "1"
    assert (await redis.get(REDIS_KEY_TRADING_PAUSED_REASON)) == "Grade F: 12% score"


async def test_unknown_proposal_type_is_logged_not_applied(monkeypatch):
    """parameter_change / code_change need human review — no Redis writes."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
        FieldName.CONTENT: {FieldName.ACTION: "tighten_stop_loss"},
    }
    await applier.process("proposals", "1-0", proposal)

    # No control-plane key should have been written
    assert await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE) is None
    assert await redis.get(REDIS_KEY_TRADING_PAUSED) is None


async def test_apply_writes_agent_log_with_applied_at(monkeypatch):
    """Each applied proposal generates an agent_logs row with applied_at."""
    write_log_mock = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log_mock)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.AGENT_RETIREMENT,
        FieldName.CONTENT: {
            FieldName.ACTION: "retire_immediately",
            FieldName.REASON: "test",
        },
        FieldName.TRACE_ID: "trace-xyz",
    }
    await applier.process("proposals", "1-0", proposal)

    assert write_log_mock.await_count == 1
    args, _ = write_log_mock.call_args
    trace_id, log_type, payload = args
    assert trace_id == "trace-xyz"
    assert payload[FieldName.APPLIED] is True
    assert FieldName.APPLIED_AT in payload
