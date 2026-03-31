"""Tests for ReflectionAgent — rolling fill accumulation, LLM reflection, fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import settings
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.pipeline_agents import ReflectionAgent

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


class _MockAsyncSession:
    def __init__(self):
        self._result = MagicMock()
        self._result.first.return_value = None
        self._result.mappings.return_value.first.return_value = None
        self._result.scalar.return_value = None
        self._result.all.return_value = []

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
def agent(mock_bus, mock_dlq):
    return ReflectionAgent(bus=mock_bus, dlq=mock_dlq)


def _trade_performance_event(pnl=100.0, symbol="BTC/USD"):
    return {
        "type": "trade_performance",
        "symbol": symbol,
        "side": "buy",
        "pnl": pnl,
        "pnl_percent": 0.5,
        "fill_price": 50000.0,
        "filled_at": "2024-01-01T12:00:00+00:00",
        "trace_id": "trace-tp-001",
    }


def _agent_grades_event(grade="B", score=0.70):
    return {
        "type": "agent_grade",
        "grade": grade,
        "score": score,
        "metrics": {"accuracy": 0.6, "ic": 0.1},
        "timestamp": "2024-01-01T12:00:00+00:00",
    }


def _factor_ic_event(factor="composite_score", ic=0.15):
    return {
        "type": "ic_update",
        "factor_name": factor,
        "ic_score": ic,
        "weight": 0.8,
        "timestamp": "2024-01-01T12:00:00+00:00",
    }


def _valid_reflection_json():
    return """{
        "winning_factors": ["composite_score", "momentum"],
        "losing_factors": ["high_volatility"],
        "hypotheses": [{"description": "test", "confidence": 0.8, "type": "parameter"}],
        "regime_edge": {"current_regime": "risk_on", "recommendation": "maintain"},
        "time_of_day_patterns": {"best_hours": [10, 14], "worst_hours": [16]},
        "summary": "Momentum strategy performing well."
    }"""


# Helper: mock Redis with budget well below max
def _budget_redis(used=0):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=str(used).encode())
    redis.incrby = AsyncMock()
    redis.incrbyfloat = AsyncMock()
    return redis


# ---------------------------------------------------------------------------
# Stream accumulation tests
# ---------------------------------------------------------------------------


async def test_accumulates_fills_from_trade_performance(agent):
    """trade_performance events increment _fills and populate _recent_fills."""
    await agent.process("trade_performance", "msg-1", _trade_performance_event(pnl=50.0))
    await agent.process("trade_performance", "msg-2", _trade_performance_event(pnl=-20.0))

    assert agent._fills == 2
    assert len(agent._recent_fills) == 2
    fills_pnl = [f["pnl"] for f in list(agent._recent_fills)]
    assert 50.0 in fills_pnl
    assert -20.0 in fills_pnl


async def test_accumulates_grades_from_agent_grades(agent):
    """agent_grades events populate _recent_grades."""
    await agent.process("agent_grades", "msg-1", _agent_grades_event("A", 0.85))
    await agent.process("agent_grades", "msg-2", _agent_grades_event("C", 0.52))

    assert len(agent._recent_grades) == 2
    grades = [g["grade"] for g in list(agent._recent_grades)]
    assert "A" in grades
    assert "C" in grades


async def test_accumulates_ic_from_factor_ic_history(agent):
    """factor_ic_history events populate _recent_ic."""
    await agent.process("factor_ic_history", "msg-1", _factor_ic_event("composite_score", 0.20))
    await agent.process("factor_ic_history", "msg-2", _factor_ic_event("momentum", 0.05))

    assert len(agent._recent_ic) == 2
    factors = [ic["factor"] for ic in list(agent._recent_ic)]
    assert "composite_score" in factors
    assert "momentum" in factors


# ---------------------------------------------------------------------------
# Trigger threshold tests
# ---------------------------------------------------------------------------


async def test_no_reflection_before_threshold(agent, mock_bus):
    """Sending fewer fills than REFLECT_EVERY_N_FILLS does not trigger reflection."""
    trigger = max(int(settings.REFLECT_EVERY_N_FILLS), 1)

    with patch.object(agent, "_run_reflection", AsyncMock()) as mock_reflect:
        for i in range(trigger - 1):
            await agent.process("trade_performance", f"msg-{i}", _trade_performance_event())

        mock_reflect.assert_not_called()


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_reflection_triggers_at_threshold(agent, mock_bus):
    """Sending exactly REFLECT_EVERY_N_FILLS fills with enough data triggers reflection."""
    trigger = max(int(settings.REFLECT_EVERY_N_FILLS), 1)

    # Pre-load _recent_fills so the min-data check passes (needs >= 3)
    for _ in range(5):
        agent._recent_fills.append(_trade_performance_event(pnl=100.0))

    with patch.object(agent, "_run_reflection", AsyncMock()) as mock_reflect:
        for i in range(trigger):
            await agent.process("trade_performance", f"msg-{i}", _trade_performance_event())

        mock_reflect.assert_called_once()


async def test_reflection_skipped_when_insufficient_data(agent, mock_bus):
    """Even at trigger fill count, reflection is skipped if _recent_fills has < 3 items."""
    trigger = max(int(settings.REFLECT_EVERY_N_FILLS), 1)

    with patch.object(agent, "_run_reflection", AsyncMock()) as mock_reflect:
        # Send exactly trigger fills but _recent_fills will only have that many entries
        # The agent checks len(_recent_fills) < 3 before running reflection
        # Force _recent_fills to be empty after filling
        for i in range(trigger):
            await agent.process("trade_performance", f"msg-{i}", _trade_performance_event())
            # Clear the deque to simulate insufficient data at reflection time
            agent._recent_fills.clear()

        # With _recent_fills always cleared, reflection should never fire
        mock_reflect.assert_not_called()


# ---------------------------------------------------------------------------
# LLM / fallback tests
# ---------------------------------------------------------------------------


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_fallback_reflection_used_on_llm_failure(agent, mock_bus):
    """When call_llm_with_system raises, reflection still publishes using fallback data."""
    # Pre-load sufficient fills
    for _ in range(5):
        agent._recent_fills.append(_trade_performance_event(pnl=50.0))
    agent._fills = max(int(settings.REFLECT_EVERY_N_FILLS), 1)

    mock_redis = _budget_redis(used=0)

    with (
        patch(
            "api.services.agents.pipeline_agents.AsyncSessionFactory",
            _MockSessionFactory(),
        ),
        patch("api.redis_client.get_redis", AsyncMock(return_value=mock_redis)),
        patch(
            "api.services.agents.pipeline_agents.ReflectionAgent._run_reflection",
            new=ReflectionAgent._run_reflection,  # use real method
        ),
        patch(
            "api.services.llm_router.call_llm_with_system",
            AsyncMock(side_effect=RuntimeError("LLM unavailable")),
        ),
    ):
        await agent._run_reflection()

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "reflection_outputs" in published_streams

    reflection_call = next(
        c for c in mock_bus.publish.call_args_list if c.args[0] == "reflection_outputs"
    )
    payload = reflection_call.args[1]
    # Fallback populates winning_factors and an empty hypotheses list
    assert "winning_factors" in payload
    assert payload["hypotheses"] == []


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_publishes_reflection_output(agent, mock_bus):
    """When LLM returns valid JSON, reflection_outputs stream is published."""
    for _ in range(5):
        agent._recent_fills.append(_trade_performance_event(pnl=80.0))
    agent._fills = max(int(settings.REFLECT_EVERY_N_FILLS), 1)

    mock_redis = _budget_redis(used=0)

    with (
        patch(
            "api.services.agents.pipeline_agents.AsyncSessionFactory",
            _MockSessionFactory(),
        ),
        patch("api.redis_client.get_redis", AsyncMock(return_value=mock_redis)),
        patch(
            "api.services.llm_router.call_llm_with_system",
            AsyncMock(return_value=(_valid_reflection_json(), 300, 0.001)),
        ),
    ):
        await agent._run_reflection()

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "reflection_outputs" in published_streams

    reflection_call = next(
        c for c in mock_bus.publish.call_args_list if c.args[0] == "reflection_outputs"
    )
    payload = reflection_call.args[1]
    assert payload["type"] == "reflection_output"
    assert payload["source"] == "reflection_agent"
    assert "winning_factors" in payload
    assert "hypotheses" in payload
    assert "summary" in payload


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_budget_check_skips_reflection(agent, mock_bus):
    """When token budget is exhausted, _run_reflection publishes a warning notification and returns early."""
    for _ in range(5):
        agent._recent_fills.append(_trade_performance_event(pnl=50.0))
    agent._fills = max(int(settings.REFLECT_EVERY_N_FILLS), 1)

    # Redis reports budget fully consumed
    budget_max = settings.ANTHROPIC_DAILY_TOKEN_BUDGET
    mock_redis = _budget_redis(used=budget_max)

    with (
        patch("api.redis_client.get_redis", AsyncMock(return_value=mock_redis)),
        patch(
            "api.services.llm_router.call_llm_with_system",
            AsyncMock(),
        ) as mock_llm,
    ):
        await agent._run_reflection()

    # LLM must not have been called
    mock_llm.assert_not_called()

    # A warning notification should have been published
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "notifications" in published_streams

    notif_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "notifications")
    payload = notif_call.args[1]
    assert payload["severity"] == "WARNING"
    assert "budget" in payload["message"].lower() or "skipped" in payload["message"].lower()


# ---------------------------------------------------------------------------
# Parse reflection response tests
# ---------------------------------------------------------------------------


class TestParseReflectionResponse:
    """Sync tests for the JSON parsing helper — no asyncio needed."""

    @pytest.fixture
    def parser(self):
        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()
        dlq = MagicMock(spec=DLQManager)
        dlq.push = AsyncMock()
        return ReflectionAgent(bus=bus, dlq=dlq)

    def test_valid_json(self, parser):
        """Valid JSON is parsed and all required keys are present."""
        parsed = parser._parse_llm_response(_valid_reflection_json())
        assert parsed["winning_factors"] == ["composite_score", "momentum"]
        assert len(parsed["hypotheses"]) == 1
        assert parsed["summary"] == "Momentum strategy performing well."

    def test_strips_markdown_fences(self, parser):
        """JSON wrapped in markdown code fences is parsed correctly."""
        fenced = "```json\n" + _valid_reflection_json() + "\n```"
        parsed = parser._parse_llm_response(fenced)
        assert "winning_factors" in parsed
        assert parsed["winning_factors"] == ["composite_score", "momentum"]

    def test_falls_back_on_invalid_json(self, parser):
        """Garbage LLM output falls back to _FALLBACK_REFLECTION defaults."""
        parsed = parser._parse_llm_response("not valid json at all @@##")
        assert "winning_factors" in parsed
        assert "hypotheses" in parsed
        assert parsed["hypotheses"] == []
