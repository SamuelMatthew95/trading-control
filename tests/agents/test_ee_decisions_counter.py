"""Tests for ExecutionEngine._decisions_evaluated counter.

Verifies that the counter increments once at the top of process() for every
decision received — HOLD, gated, and executed BUY/SELL — and that the current
value is forwarded to write_heartbeat as event_count.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.constants import FieldName
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.redis = AsyncMock()
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


def _make_dlq() -> DLQManager:
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    dlq.should_dlq = AsyncMock(return_value=False)
    dlq.redis = AsyncMock()
    return dlq


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # kill switch OFF, trading not paused
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    return redis


def _make_engine() -> ExecutionEngine:
    broker = MagicMock(spec=PaperBroker)
    broker.place_order = AsyncMock()
    broker.get_position = AsyncMock(return_value={})
    return ExecutionEngine(
        bus=_make_bus(),
        dlq=_make_dlq(),
        redis_client=_make_redis(),
        broker=broker,
    )


def _hold_decision() -> dict:
    """Minimal valid decision with action=hold — hits the NO_ORDER_ACTIONS gate."""
    return {
        FieldName.ACTION: "hold",
        FieldName.SYMBOL: "BTC/USD",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 50000.0,
        FieldName.SIGNAL_CONFIDENCE: 0.8,
        FieldName.REASONING_SCORE: 0.8,
        FieldName.COMPOSITE_SCORE: 0.8,
        FieldName.TRACE_ID: "trace-hold-001",
        FieldName.MSG_ID: "msg-001",
    }


def _low_score_buy() -> dict:
    """BUY decision with signal_confidence=0.1 so final score is below the 0.55 threshold."""
    return {
        FieldName.ACTION: "buy",
        FieldName.SYMBOL: "BTC/USD",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 50000.0,
        FieldName.SIGNAL_CONFIDENCE: 0.1,
        FieldName.REASONING_SCORE: 0.1,
        FieldName.COMPOSITE_SCORE: 0.1,
        FieldName.TRACE_ID: "trace-gate-001",
        FieldName.MSG_ID: "msg-002",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_decisions_evaluated_increments_on_hold():
    """Counter increments when process() receives a HOLD action."""
    engine = _make_engine()
    assert engine._decisions_evaluated == 0

    with patch(
        "api.services.execution.execution_engine._write_heartbeat",
        new_callable=AsyncMock,
    ):
        await engine.process(_hold_decision())

    assert engine._decisions_evaluated == 1


async def test_decisions_evaluated_increments_on_gated_decision():
    """Counter increments when a BUY decision is gated by a low composite score."""
    engine = _make_engine()

    with patch(
        "api.services.execution.execution_engine._write_heartbeat",
        new_callable=AsyncMock,
    ):
        await engine.process(_low_score_buy())

    assert engine._decisions_evaluated == 1


async def test_decisions_evaluated_counts_multiple_calls():
    """Counter accumulates across three consecutive process() calls."""
    engine = _make_engine()

    with patch(
        "api.services.execution.execution_engine._write_heartbeat",
        new_callable=AsyncMock,
    ):
        await engine.process(_hold_decision())
        await engine.process(_hold_decision())
        await engine.process(_hold_decision())

    assert engine._decisions_evaluated == 3


async def test_decisions_evaluated_passed_to_heartbeat():
    """write_heartbeat receives _decisions_evaluated as the event_count argument."""
    engine = _make_engine()

    with patch(
        "api.services.execution.execution_engine._write_heartbeat",
        new_callable=AsyncMock,
    ) as mock_hb:
        await engine.process(_hold_decision())

    assert mock_hb.called, "write_heartbeat should have been called at least once"

    # _write_idle_heartbeat passes self._decisions_evaluated as the 4th positional arg:
    # _write_heartbeat(redis, agent_name, status_string, event_count, ...)
    found = False
    for call in mock_hb.call_args_list:
        args, kwargs = call
        if len(args) >= 4 and args[3] == 1:
            found = True
            break
        if kwargs.get("event_count") == 1:
            found = True
            break

    assert found, (
        f"Expected write_heartbeat called with event_count=1; actual calls: {mock_hb.call_args_list}"
    )
