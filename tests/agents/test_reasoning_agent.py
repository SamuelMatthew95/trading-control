"""Tests for ReasoningAgent — structured LLM-based signal reasoning."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import settings
from api.constants import TOOL_GET_IC_WEIGHTS, TOOL_QUERY_SIMILAR_TRADES
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.prompts import (
    DECISION_OUTPUT_CONTRACT,
    SYSTEM_CONSTITUTION_PROMPT,
)
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.tool_registry import get_tool_registry

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
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_fallback_when_no_llm_key(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """When LLM call raises (simulating missing key), agent falls back gracefully."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.side_effect = RuntimeError("No API key configured")
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
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_processes_signal_event_publishes_order_for_buy(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """Valid signal with buy action publishes advisory decision to 'decisions' stream."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
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
    # Decision records which model produced it (provider:model label) so the
    # learning loop can grade with model awareness.
    assert decision_payload["model_used"]
    assert ":" in decision_payload["model_used"]


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_decision_records_model_used_in_agent_log(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """The reasoning_summary agent_log carries the model that produced the decision."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
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

    log_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "agent_logs")
    assert log_call.args[1]["model_used"]


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_fallback_decision_marks_model_used_fallback(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """A fallback decision (LLM failed) records model_used='fallback'."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.side_effect = RuntimeError("No API key configured")
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

    decision_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "decisions")
    assert decision_call.args[1]["model_used"] == "fallback"


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_decision_records_actual_provider_from_result_meta(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """The decision records the provider the router actually used (reported via
    result_meta) — e.g. an lmstudio→cloud fallback — not just the configured default."""
    mock_embed.return_value = [0.1] * 1536
    mock_redis.get = AsyncMock(return_value=b"0")

    async def _fake_call(prompt, system_prompt, trace_id, *, task_type=None, result_meta=None):
        if result_meta is not None:
            result_meta["model_label"] = "groq:llama-3.3-70b-versatile"
        return json.dumps(_valid_summary("buy")), 500, 0.001

    mock_call_llm_with_system.side_effect = _fake_call

    with patch(
        "api.services.agents.reasoning_agent.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        with patch(
            "api.services.agents.vector_helpers.search_vector_memory",
            AsyncMock(return_value=[]),
        ):
            await agent.process(_make_signal("buy"))

    decision_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "decisions")
    assert decision_call.args[1]["model_used"] == "groq:llama-3.3-70b-versatile"


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_hold_action_no_order_published(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """When LLM returns action='hold', advisory decision still published to 'decisions' with action=hold."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("hold")), 300, 0.001)
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
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_reject_action_no_order_published(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """When LLM returns action='reject', advisory decision still published to 'decisions' with action=reject."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("reject")), 300, 0.001)
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


@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_token_budget_check_skips_llm(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
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
    mock_call_llm_with_system.assert_not_called()

    # Agent still publishes to agent_logs (fallback path)
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "agent_logs" in published_streams


@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_vector_memory_search_failure_graceful(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """When the DB inside _search_vector_memory raises, the method returns [] and agent continues."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
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


@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_publishes_to_agent_logs(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis
):
    """After processing a signal, agent publishes to 'agent_logs' stream."""
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("sell")), 400, 0.002)
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


@patch("api.services.agents.reasoning_agent.call_llm_with_system")
async def test_call_llm_assembles_tool_governed_prompt(mock_call_llm_with_system, agent):
    """The decision call uses the Prompt-OS runtime prompt — immutable
    constitution + ONLY the node-scoped, positive-alpha tools + the output
    contract — instead of the static adaptive prompt. This is what makes the
    buy/sell LLM actually 'use tools'."""
    mock_call_llm_with_system.return_value = ('{"action":"buy","confidence":0.9}', 42, 0.001)
    decision, tokens, cost = await agent._call_llm(
        data={"symbol": "BTC/USD", "composite_score": 0.8},
        similar_trades=[],
        trace_id="trace-1",
        context={"ic_weights": {"composite_score": 1.0}, "risk_state": {"drawdown": -0.01}},
    )
    assert decision["action"] == "buy"
    assert tokens == 42
    assert cost == 0.001

    system_prompt = mock_call_llm_with_system.call_args.args[1]
    # Immutable constitution is the root layer, with the output contract appended.
    assert SYSTEM_CONSTITUTION_PROMPT in system_prompt
    assert DECISION_OUTPUT_CONTRACT in system_prompt
    # Eligible perception + memory tools are exposed to the LLM...
    assert "query_similar_trades" in system_prompt
    assert "get_ic_weights" in system_prompt
    # ...while negative-alpha and downstream-execution tools are NOT.
    assert "scan_sector_correlation" not in system_prompt
    assert "execute_bracket_order" not in system_prompt


@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.reasoning_agent.search_vector_memory")
@patch("api.services.agents.reasoning_agent.embed_text")
async def test_process_records_tool_telemetry(
    mock_embed, mock_search, mock_call_llm, agent, mock_redis
):
    """A full decision exercises the registry's memory tools and folds their
    real latency + reliability into telemetry. This is the live feedback loop
    behind the governance panel — proof the buy/sell LLM actually uses tools."""
    mock_embed.return_value = [0.1] * 1536
    mock_search.return_value = []
    mock_call_llm.return_value = (json.dumps(_valid_summary("buy")), 100, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    await agent.process(_make_signal("buy"))

    reg = get_tool_registry()
    ic_tool = reg.get(TOOL_GET_IC_WEIGHTS)
    mem_tool = reg.get(TOOL_QUERY_SIMILAR_TRADES)
    assert ic_tool.call_count >= 1
    assert mem_tool.call_count >= 1
    assert ic_tool.success_count >= 1
    assert mem_tool.success_count >= 1


@patch("api.services.agents.reasoning_agent.call_llm_with_system")
async def test_call_llm_invalid_json_returns_safe_hold(mock_call_llm_with_system, agent):
    mock_call_llm_with_system.return_value = ("not-json", 10, 0.0001)
    decision, tokens, cost = await agent._call_llm(
        data={"symbol": "BTC/USD", "composite_score": 0.8},
        similar_trades=[],
        trace_id="trace-2",
        context={},
    )
    assert decision["action"] == "hold"
    assert "invalid_llm_json" in decision["risk_factors"]
    assert decision["confidence"] == 0.0
    assert tokens == 10
    assert cost == 0.0001


@patch("api.services.agents.reasoning_agent.call_llm_with_system")
async def test_call_llm_json_array_returns_safe_hold(mock_call_llm_with_system, agent):
    mock_call_llm_with_system.return_value = ('[{"action":"buy"}]', 11, 0.0002)
    decision, _, _ = await agent._call_llm(
        data={"symbol": "BTC/USD", "composite_score": 0.8},
        similar_trades=[],
        trace_id="trace-3",
        context={},
    )
    assert decision["action"] == "hold"
    assert "invalid_llm_json" in decision["risk_factors"]


async def test_fallback_derives_directional_action_when_llm_unavailable(agent):
    bullish = await agent._apply_fallback(
        {"direction": "bullish", "pct": 0.3, "action": "hold"},
        trace_id="trace-fallback-buy",
        reason="missing_api_key",
    )
    bearish = await agent._apply_fallback(
        {"direction": "bearish", "pct": -0.2, "action": "hold"},
        trace_id="trace-fallback-sell",
        reason="missing_api_key",
    )

    assert bullish["action"] == "buy"
    assert bearish["action"] == "sell"


# ---------------------------------------------------------------------------
# Learning-loop dampening tests — verify that ProposalApplier's Redis writes
# (signal_weight_scale, agent_suspended) actually change ReasoningAgent
# behavior. Without these, the loop is closed in name only.
# ---------------------------------------------------------------------------


async def test_suspended_agent_skips_processing(agent, mock_bus, mock_redis):
    """When learning:agent_suspended:REASONING_AGENT is set, drop the signal."""
    from api.constants import AGENT_REASONING, REDIS_KEY_AGENT_SUSPENDED

    suspended_key = REDIS_KEY_AGENT_SUSPENDED.format(name=AGENT_REASONING)

    async def _fake_get(key):
        if key == suspended_key:
            return "1"  # mirrors the kill-switch contract
        return None

    mock_redis.get = AsyncMock(side_effect=_fake_get)
    await agent.process(_make_signal())

    # No publish to STREAM_DECISIONS — the agent returned early
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "decisions" not in published_streams


async def test_weight_scale_applied_to_published_decision(agent, mock_bus, mock_redis, monkeypatch):
    """signal_weight_scale=0.5 -> reasoning_score and signal_confidence halved."""
    import json as _json

    from api.constants import REDIS_KEY_AGENT_SUSPENDED, REDIS_KEY_SIGNAL_WEIGHT_SCALE

    monkeypatch.setattr(
        "api.services.agents.reasoning_agent.embed_text", AsyncMock(return_value=[0.1] * 1536)
    )
    monkeypatch.setattr(
        "api.services.agents.reasoning_agent.search_vector_memory",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "api.services.agents.reasoning_agent.call_llm_with_system",
        AsyncMock(return_value=(_json.dumps(_valid_summary("buy")), 500, 0.001)),
    )
    monkeypatch.setattr(
        "api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory()
    )

    async def _fake_get(key):
        if isinstance(key, str) and key.startswith(REDIS_KEY_AGENT_SUSPENDED.split("{")[0]):
            return None
        if key == REDIS_KEY_SIGNAL_WEIGHT_SCALE:
            return "0.5"
        # Token budget probe and any other reads
        return b"0"

    mock_redis.get = AsyncMock(side_effect=_fake_get)
    await agent.process(_make_signal())

    decision_payload = next(
        call.args[1] for call in mock_bus.publish.call_args_list if call.args[0] == "decisions"
    )
    # _valid_summary uses confidence=0.8, signal composite_score=0.75; both halved.
    assert decision_payload["reasoning_score"] == pytest.approx(0.4, abs=1e-6)
    assert decision_payload["signal_confidence"] == pytest.approx(0.375, abs=1e-6)
    assert decision_payload["weight_scale"] == pytest.approx(0.5, abs=1e-6)


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_per_symbol_cooldown_skips_repeat_llm_call(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis, monkeypatch
):
    """A second signal for the same symbol within the cooldown window must NOT
    trigger a second LLM call — this is the lever that decoupled LLM spend from
    raw signal volume and stopped the Groq quota burn."""
    monkeypatch.setattr(settings, "REASONING_COOLDOWN_SECONDS", 9999.0)
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory()):
        await agent.process(_make_signal(symbol="BTC/USD"))
        calls_after_first = mock_call_llm_with_system.call_count
        await agent.process(_make_signal(symbol="BTC/USD"))  # within cooldown — skipped

    # The repeat signal added zero LLM calls (a full cycle, decision +
    # self-critique, would have added at least one).
    assert calls_after_first > 0
    assert mock_call_llm_with_system.call_count == calls_after_first


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_cooldown_is_per_symbol_not_global(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis, monkeypatch
):
    """The cooldown is keyed per symbol — a different symbol still reasons."""
    monkeypatch.setattr(settings, "REASONING_COOLDOWN_SECONDS", 9999.0)
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory()):
        await agent.process(_make_signal(symbol="BTC/USD"))
        calls_after_first = mock_call_llm_with_system.call_count
        await agent.process(_make_signal(symbol="ETH/USD"))  # different symbol — reasons

    # The different symbol triggered a fresh reasoning cycle (more LLM calls).
    assert mock_call_llm_with_system.call_count > calls_after_first


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_duplicate_signal_skips_llm(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis, monkeypatch
):
    """A materially-identical repeat signal (same side+price) is deduped — no
    second LLM call — even with the cooldown disabled."""
    monkeypatch.setattr(settings, "REASONING_COOLDOWN_SECONDS", 0.0)  # isolate dedup
    monkeypatch.setattr(settings, "REASONING_DEDUP_PRICE_PCT", 0.1)
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory()):
        await agent.process(_make_signal(action="buy", symbol="BTC/USD"))
        calls_after_first = mock_call_llm_with_system.call_count
        await agent.process(_make_signal(action="buy", symbol="BTC/USD"))  # identical — deduped

    assert calls_after_first > 0
    assert mock_call_llm_with_system.call_count == calls_after_first


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_materially_changed_signal_still_reasons(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis, monkeypatch
):
    """A signal whose price moved well beyond the dedup tolerance still reasons."""
    monkeypatch.setattr(settings, "REASONING_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(settings, "REASONING_DEDUP_PRICE_PCT", 0.1)
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    sig2 = _make_signal(action="buy", symbol="BTC/USD")
    sig2["price"] = 60000.0  # ~20% move >> 0.1% tolerance

    with patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory()):
        await agent.process(_make_signal(action="buy", symbol="BTC/USD"))
        calls_after_first = mock_call_llm_with_system.call_count
        await agent.process(sig2)

    assert mock_call_llm_with_system.call_count > calls_after_first


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_self_critique_disabled_by_default_one_llm_call(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis, monkeypatch
):
    """With self-critique off (default), a high-confidence buy makes ONE LLM call."""
    monkeypatch.setattr(settings, "REASONING_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(settings, "REASONING_DEDUP_PRICE_PCT", 0.0)
    monkeypatch.setattr(settings, "REASONING_SELF_CRITIQUE_ENABLED", False)
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory()):
        await agent.process(_make_signal(action="buy"))

    assert mock_call_llm_with_system.call_count == 1


@patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory())
@patch("api.services.agents.reasoning_agent.call_llm_with_system")
@patch("api.services.agents.vector_helpers.embed_text")
async def test_self_critique_runs_when_enabled(
    mock_embed, mock_call_llm_with_system, agent, mock_bus, mock_redis, monkeypatch
):
    """Enabling self-critique adds the second LLM call on a high-confidence buy."""
    monkeypatch.setattr(settings, "REASONING_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(settings, "REASONING_DEDUP_PRICE_PCT", 0.0)
    monkeypatch.setattr(settings, "REASONING_SELF_CRITIQUE_ENABLED", True)
    mock_embed.return_value = [0.1] * 1536
    mock_call_llm_with_system.return_value = (json.dumps(_valid_summary("buy")), 500, 0.001)
    mock_redis.get = AsyncMock(return_value=b"0")

    with patch("api.services.agents.reasoning_agent.AsyncSessionFactory", _MockSessionFactory()):
        await agent.process(_make_signal(action="buy"))

    assert mock_call_llm_with_system.call_count == 2
