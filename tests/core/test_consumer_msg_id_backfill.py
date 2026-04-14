"""Tests that BaseStreamConsumer backfills msg_id from the Redis stream ID
rather than raising when a producer omits the field (e.g. the old price_poller).

Also covers the strategy_id fallback in ReasoningAgent and the relaxed required-
field check in ExecutionEngine.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager

# ---------------------------------------------------------------------------
# Minimal concrete consumer for testing
# ---------------------------------------------------------------------------


class _EchoConsumer(BaseStreamConsumer):
    """Concrete consumer that records every processed payload."""

    def __init__(self, bus, dlq):
        super().__init__(bus, dlq, stream="market_events", group=DEFAULT_GROUP, consumer="test")
        self.processed: list[dict[str, Any]] = []

    async def process(self, data: dict[str, Any]) -> None:
        self.processed.append(dict(data))


def _make_bus_dlq():
    bus = AsyncMock(spec=EventBus)
    bus.acknowledge = AsyncMock()
    dlq = AsyncMock(spec=DLQManager)
    dlq.should_dlq = AsyncMock(return_value=False)
    dlq.redis = AsyncMock()
    dlq.redis.get = AsyncMock(return_value=None)
    return bus, dlq


# ---------------------------------------------------------------------------
# msg_id backfill tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_backfills_msg_id_from_redis_id():
    """When msg_id is absent, it must be injected from the Redis stream ID."""
    bus, dlq = _make_bus_dlq()
    consumer = _EchoConsumer(bus, dlq)

    redis_id = "1700000000000-0"
    data_without_msg_id = {"payload": '{"symbol":"BTC/USD","price":60000}', "schema_version": "v3"}

    await consumer._handle_message(redis_id, data_without_msg_id)

    assert len(consumer.processed) == 1
    assert consumer.processed[0]["msg_id"] == redis_id


@pytest.mark.asyncio
async def test_handle_message_does_not_override_existing_msg_id():
    """An existing msg_id must not be overwritten by the redis stream ID."""
    bus, dlq = _make_bus_dlq()
    consumer = _EchoConsumer(bus, dlq)

    original_msg_id = str(uuid.uuid4())
    redis_id = "1700000000000-0"
    data = {"msg_id": original_msg_id, "schema_version": "v3", "payload": "{}"}

    await consumer._handle_message(redis_id, data)

    assert consumer.processed[0]["msg_id"] == original_msg_id


@pytest.mark.asyncio
async def test_handle_message_backfill_does_not_mutate_original_dict():
    """The backfill must not mutate the caller's dict (uses dict copy)."""
    bus, dlq = _make_bus_dlq()
    consumer = _EchoConsumer(bus, dlq)

    original: dict[str, Any] = {"schema_version": "v3"}
    await consumer._handle_message("1-0", original)

    assert "msg_id" not in original  # original dict unchanged


@pytest.mark.asyncio
async def test_handle_message_invalid_schema_version_goes_to_dlq():
    """Messages with an unrecognised schema_version must be DLQ'd, not processed."""
    bus, dlq = _make_bus_dlq()
    dlq.push = AsyncMock()
    consumer = _EchoConsumer(bus, dlq)

    await consumer._handle_message("1-0", {"msg_id": "m1", "schema_version": "v99"})

    dlq.push.assert_called_once()
    assert consumer.processed == []  # never reached process()


# ---------------------------------------------------------------------------
# ExecutionEngine strategy_id fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_engine_generates_strategy_id_when_absent():
    """ExecutionEngine must not drop orders when strategy_id is missing."""
    from api.services.execution.execution_engine import ExecutionEngine

    captured_strategy_id: list[str] = []

    class _FakeBroker:
        async def get_position(self, _symbol):
            return {}

        async def place_order(self, _symbol, _side, _qty, _price):
            return {
                "status": "filled",
                "broker_order_id": "fake-broker-id",
                "fill_price": 60000.0,
            }

    class _FakeSession:
        def begin(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, stmt, params=None):
            if params and "strategy_id" in params:
                captured_strategy_id.append(params["strategy_id"])
            result = MagicMock()
            result.mappings.return_value.first.return_value = None
            result.scalar_one.return_value = str(uuid.uuid4())
            return result

        async def flush(self):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    class _FakeSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *_):
            pass

    bus = AsyncMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.acknowledge = AsyncMock()
    dlq = AsyncMock(spec=DLQManager)

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)  # kill_switch not active
    redis_mock.set = AsyncMock(return_value=True)  # lock acquired
    redis_mock.delete = AsyncMock()

    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis_mock, broker=_FakeBroker())

    order_data = {
        "msg_id": str(uuid.uuid4()),
        # strategy_id intentionally absent
        "symbol": "BTC/USD",
        "side": "buy",
        "qty": "0.01",
        "price": "60000",
        "timestamp": "2026-01-01T00:00:00Z",
        "trace_id": str(uuid.uuid4()),
        "schema_version": "v3",
        # Provide a score that clears the weighted execution gate (>= 0.55)
        "signal_confidence": 0.7,
        "reasoning_score": 0.7,
    }

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory", _FakeSessionFactory()
    ):
        with patch("api.services.agents.db_helpers.AsyncSessionFactory", _FakeSessionFactory()):
            try:
                await engine.process(order_data)
            except Exception:
                pass  # DB errors from fake session are fine; we only care about strategy_id

    # Must have captured at least one strategy_id (from the INSERT into orders)
    assert captured_strategy_id, "ExecutionEngine must generate a strategy_id even when absent"
    # Must be a valid UUID string
    parsed = uuid.UUID(captured_strategy_id[0])
    assert parsed.version == 4


# ---------------------------------------------------------------------------
# ReasoningAgent strategy_id fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_agent_publishes_order_with_strategy_id_fallback():
    """ReasoningAgent must always include a non-empty strategy_id in the order event."""
    from api.services.agents.reasoning_agent import ReasoningAgent

    class _FakeSession:
        def begin(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, _stmt, _params=None):
            result = MagicMock()
            result.first.return_value = None
            result.scalar.return_value = None
            result.scalar_one.return_value = str(uuid.uuid4())
            return result

        async def flush(self):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    class _FakeSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *_):
            pass

    published_orders: list[tuple[str, dict]] = []

    async def _capture_publish(stream, payload):
        published_orders.append((stream, payload))

    bus = AsyncMock(spec=EventBus)
    bus.publish = AsyncMock(side_effect=_capture_publish)
    bus.redis = AsyncMock()
    bus.redis.get = AsyncMock(return_value=None)
    bus.redis.incrby = AsyncMock(return_value=0)
    bus.redis.incrbyfloat = AsyncMock(return_value=0.0)

    dlq = AsyncMock(spec=DLQManager)

    agent = ReasoningAgent(bus=bus, dlq=dlq, redis_client=bus.redis)

    # Simulate LLM returning a "buy" decision
    llm_response = {
        "action": "buy",
        "confidence": 0.85,
        "primary_edge": "test",
        "risk_factors": [],
        "size_pct": 0.05,
        "stop_atr_x": 1.5,
        "rr_ratio": 2.0,
        "latency_ms": 10,
        "cost_usd": 0.001,
        "trace_id": str(uuid.uuid4()),
    }

    signal_data = {
        "msg_id": str(uuid.uuid4()),
        "symbol": "BTC/USD",
        "price": 60000.0,
        "pct": 3.5,
        # strategy_id intentionally absent — agent must generate one
    }

    with patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _FakeSessionFactory()):
        with patch(
            "api.services.agents.reasoning_agent.embed_text", AsyncMock(return_value=[0.1] * 10)
        ):
            with patch(
                "api.services.agents.reasoning_agent.search_vector_memory",
                AsyncMock(return_value=[]),
            ):
                with patch(
                    "api.services.agents.reasoning_agent.call_llm",
                    AsyncMock(return_value=(llm_response, 100, 0.001)),
                ):
                    with patch(
                        "api.services.agents.db_helpers.AsyncSessionFactory", _FakeSessionFactory()
                    ):
                        await agent.process(signal_data)

    # ReasoningAgent now publishes advisory decisions to "decisions" (not "orders")
    decision_events = [(s, p) for s, p in published_orders if s == "decisions"]
    assert decision_events, "ReasoningAgent must publish a decision for a 'buy' advisory"
    _stream, decision = decision_events[0]
    assert decision.get("strategy_id"), "Decision must have a non-empty strategy_id"
    # Must be a valid UUID
    parsed = uuid.UUID(str(decision["strategy_id"]))
    assert parsed.version == 4
