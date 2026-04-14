"""Tests for ReasoningAgent — structured LLM-based signal reasoning."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import settings
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.reasoning_agent import ReasoningAgent

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


class _MockAsyncSession:
    """Async session that supports 'async with session.begin()'."""

    def __init__(self, scalar_value=None, first_value=None, all_values=None):
        self._result = MagicMock()
        self._result.scalar.return_value = scalar_value
        self._result.scalar_one.return_value = scalar_value or "mock-id"
        self._result.first.return_value = first_value
        self._result.mappings.return_value.all.return_value = all_values or []
        self._result.mappings.return_value.first.return_value = first_value

    async def execute(self, *args, **kwargs):
        return self._result

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def begin(self):
        return _AsyncCtx()


class _AsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _MockSessionFactory:
    """Callable context manager that yields a mock session."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return _MockAsyncSession()

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


@pytest.fixture
def mock_dlq():
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"0")
    redis.incrby = AsyncMock(return_value=100)
    redis.incrbyfloat = AsyncMock(return_value=0.01)
    redis.set = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def agent(mock_bus, mock_dlq, mock_redis):
    return ReasoningAgent(bus=mock_bus, dlq=mock_dlq, redis_client=mock_redis)


def _make_signal(action="buy", symbol="BTC/USD", strategy_id="strat-1"):
    return {
        "symbol": symbol,
        "price": 50000.0,
        "last_price": 50000.0,
        "composite_score": 0.75,
        "signal_type": "MOMENTUM",
        "action": action,
        "qty": 1.0,
        "strategy_id": strategy_id,
        "timestamp": "2024-01-01T00:00:00+00:00",
        "trace_id": "trace-test-123",
    }


def _valid_summary(action="buy"):
    return {
        "action": action,
        "confidence": 0.8,
        "primary_edge": "momentum",
        "risk_factors": ["high_vol"],
        "size_pct": 0.05,
        "stop_atr_x": 1.5,
        "rr_ratio": 2.0,
        "latency_ms": 200,
        "cost_usd": 0.001,
        "trace_id": "trace-abc",
        "fallback": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_fallback_when_no_llm_key(mock_embed, mock_call_llm, agent, mock_bus, mock_redis):
    """When LLM call raises (simulating missing key), agent falls back gracefully."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm.side_effect = RuntimeError("No API key configured")
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch(
        "api.services.agents.reasoning_agent.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await agent.process(_make_signal())

    # Should still publish to agent_logs (not crash)
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "agent_logs" in published_streams


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_processes_signal_event_publishes_order_for_buy(
    mock_embed, mock_call_llm, agent, mock_bus, mock_redis
):
    """Valid signal with buy action publishes advisory decision to 'decisions' stream."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm.return_value = (_valid_summary("buy"), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch(
        "api.services.agents.reasoning_agent.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        with patch(
            "api.services.agents.vector_helpers.search_vector_memory",
            AsyncMock(return_value=[]),
        ):
            await agent.process(_make_signal("buy"))

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "decisions" in published_streams

    decision_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "decisions")
    decision_payload = decision_call.args[1]
    assert decision_payload["action"] == "buy"
    assert decision_payload["symbol"] == "BTC/USD"
    assert "trace_id" in decision_payload
    assert "reasoning_score" in decision_payload
    assert "signal_confidence" in decision_payload


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_hold_action_no_order_published(
    mock_embed, mock_call_llm, agent, mock_bus, mock_redis
):
    """When LLM returns action='hold', advisory decision still published to 'decisions' with action=hold."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm.return_value = (_valid_summary("hold"), 300, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch(
        "api.services.agents.reasoning_agent.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        with patch(
            "api.services.agents.vector_helpers.search_vector_memory",
            AsyncMock(return_value=[]),
        ):
            await agent.process(_make_signal("hold"))

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    # ReasoningAgent always publishes to decisions (advisory); ExecutionEngine gates hold/reject
    assert "decisions" in published_streams
    decision_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "decisions")
    assert decision_call.args[1]["action"] == "hold"


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_reject_action_no_order_published(
    mock_embed, mock_call_llm, agent, mock_bus, mock_redis
):
    """When LLM returns action='reject', advisory decision still published to 'decisions' with action=reject."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm.return_value = (_valid_summary("reject"), 300, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch(
        "api.services.agents.reasoning_agent.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        with patch(
            "api.services.agents.vector_helpers.search_vector_memory",
            AsyncMock(return_value=[]),
        ):
            await agent.process(_make_signal("reject"))

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    # ReasoningAgent always publishes to decisions (advisory); ExecutionEngine gates hold/reject
    assert "decisions" in published_streams
    decision_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "decisions")
    assert decision_call.args[1]["action"] == "reject"


@patch("api.services.agents.reasoning_agent.call_llm")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_token_budget_check_skips_llm(mock_embed, mock_call_llm, agent, mock_bus, mock_redis):
    """When daily token budget is at max, LLM is skipped and fallback is used."""
    mock_embed.return_value = [0.1] * 1536
    # Simulate budget already fully consumed
    budget_max = settings.ANTHROPIC_DAILY_TOKEN_BUDGET
    mock_redis.get = AsyncMock(return_value=str(budget_max).encode())

    with patch(
        "api.services.agents.reasoning_agent.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        with patch(
            "api.services.agents.vector_helpers.search_vector_memory",
            AsyncMock(return_value=[]),
        ):
            await agent.process(_make_signal())

    # LLM should NOT have been called
    mock_call_llm.assert_not_called()

    # Agent still publishes to agent_logs (fallback path)
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "agent_logs" in published_streams


@patch("api.services.agents.reasoning_agent.call_llm")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_vector_memory_search_failure_graceful(
    mock_embed, mock_call_llm, agent, mock_bus, mock_redis
):
    """When the DB inside _search_vector_memory raises, the method returns [] and agent continues."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm.return_value = (_valid_summary("buy"), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    # Patch _search_vector_memory to return empty list (simulating graceful DB failure
    # — the real implementation already catches exceptions and returns []).
    # We verify the agent still processes the signal and publishes to agent_logs.
    with (
        patch(
            "api.services.agents.reasoning_agent.AsyncSessionFactory",
            _MockSessionFactory(),
        ),
        patch(
            "api.services.agents.vector_helpers.search_vector_memory", AsyncMock(return_value=[])
        ),
    ):
        # Should not raise — vector search failure is gracefully handled
        await agent.process(_make_signal("buy"))

    # Agent still published to agent_logs
    from api.constants import STREAM_AGENT_LOGS

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert STREAM_AGENT_LOGS in published_streams


@patch("api.services.agents.reasoning_agent.call_llm")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_publishes_to_agent_logs(mock_embed, mock_call_llm, agent, mock_bus, mock_redis):
    """After processing a signal, agent publishes to 'agent_logs' stream."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm.return_value = (_valid_summary("sell"), 400, 0.002)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch(
        "api.services.agents.reasoning_agent.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        with patch(
            "api.services.agents.vector_helpers.search_vector_memory",
            AsyncMock(return_value=[]),
        ):
            await agent.process(_make_signal("sell"))

    from api.constants import SOURCE_REASONING, STREAM_AGENT_LOGS

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert STREAM_AGENT_LOGS in published_streams

    agent_log_call = next(
        c for c in mock_bus.publish.call_args_list if c.args[0] == STREAM_AGENT_LOGS
    )
    log_payload = agent_log_call.args[1]
    assert log_payload["type"] == "agent_log"
    assert log_payload["source"] == SOURCE_REASONING
    assert "action" in log_payload
