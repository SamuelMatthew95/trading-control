"""Tests for GradeAgent — real performance scoring logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import (
    GradeAgent,
    _normalize_ic,
    _score_to_grade,
    _spearman_correlation,
)

# Applied per-function for async tests; sync helper tests do not carry this mark.


# ---------------------------------------------------------------------------
# Shared mock infrastructure (mirrors tests/core/test_signal_pipeline.py)
# ---------------------------------------------------------------------------


class _MockAsyncSession:
    def __init__(self):
        self._result = MagicMock()
        self._result.first.return_value = None
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
def agent_state():
    return AgentStateRegistry()


@pytest.fixture
def grade_agent(mock_bus, mock_dlq, agent_state):
    return GradeAgent(mock_bus, mock_dlq, agent_state=agent_state)


# ---------------------------------------------------------------------------
# Buffer accumulation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_accumulates_fills_from_trade_performance(grade_agent):
    """Each trade_performance event increments _fills and populates _pnl_buffer."""
    await grade_agent.process("trade_performance", "id-1", {"pnl": 10.0})
    await grade_agent.process("trade_performance", "id-2", {"pnl": -5.0})
    await grade_agent.process("trade_performance", "id-3", {"pnl": 20.0})

    assert grade_agent._fills == 3
    assert list(grade_agent._pnl_buffer) == [10.0, -5.0, 20.0]


@pytest.mark.asyncio
@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_accumulates_confidence_from_executions(grade_agent):
    """Each executions event populates _confidence_buffer from the confidence field."""
    await grade_agent.process("executions", "id-1", {"confidence": 0.9})
    await grade_agent.process("executions", "id-2", {"confidence": 0.6})

    assert list(grade_agent._confidence_buffer) == [0.9, 0.6]


# ---------------------------------------------------------------------------
# Grade trigger tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_no_grade_before_trigger(grade_agent, mock_bus):
    """Fewer than GRADE_EVERY_N_FILLS fills should not trigger _compute_and_publish_grade."""
    # Default GRADE_EVERY_N_FILLS = 5; send 4 fills — should not trigger
    for i in range(4):
        await grade_agent.process("trade_performance", f"id-{i}", {"pnl": float(i)})

    assert grade_agent._fills == 4
    # bus.publish should not have been called with agent_grades at this point
    for call in mock_bus.publish.call_args_list:
        stream = call[0][0]
        assert stream != "agent_grades", "Grade published before trigger threshold"


@pytest.mark.asyncio
@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_grade_triggers_at_n_fills(grade_agent):
    """Exactly GRADE_EVERY_N_FILLS fills should call _compute_and_publish_grade once."""
    with patch.object(
        grade_agent, "_compute_and_publish_grade", new_callable=AsyncMock
    ) as mock_compute:
        for i in range(5):
            await grade_agent.process("trade_performance", f"id-{i}", {"pnl": float(i)})

        mock_compute.assert_called_once()


# ---------------------------------------------------------------------------
# Pure helper function tests — no DB, no mocking needed
# ---------------------------------------------------------------------------


def test_spearman_correlation_positive():
    """Perfect positive rank correlation returns 1.0."""
    result = _spearman_correlation([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert result == pytest.approx(1.0, abs=1e-9)


def test_spearman_correlation_negative():
    """Perfect negative rank correlation returns -1.0."""
    result = _spearman_correlation([1, 2, 3, 4, 5], [10, 8, 6, 4, 2])
    assert result == pytest.approx(-1.0, abs=1e-9)


def test_normalize_ic_zero():
    """IC of 0.0 maps to 0.5 (neutral midpoint)."""
    assert _normalize_ic(0.0) == pytest.approx(0.5)


def test_normalize_ic_one():
    """IC of 1.0 maps to 1.0 (maximum)."""
    assert _normalize_ic(1.0) == pytest.approx(1.0)


def test_normalize_ic_negative_one():
    """IC of -1.0 maps to 0.0 (minimum)."""
    assert _normalize_ic(-1.0) == pytest.approx(0.0)


def test_score_to_grade_thresholds():
    """Grade letter boundaries match documented thresholds."""
    assert _score_to_grade(0.95) == "A+"
    assert _score_to_grade(0.90) == "A+"  # boundary inclusive
    assert _score_to_grade(0.85) == "A"
    assert _score_to_grade(0.80) == "A"  # boundary inclusive
    assert _score_to_grade(0.70) == "B"
    assert _score_to_grade(0.65) == "B"  # boundary inclusive
    assert _score_to_grade(0.55) == "C"
    assert _score_to_grade(0.50) == "C"  # boundary inclusive
    assert _score_to_grade(0.40) == "D"
    assert _score_to_grade(0.35) == "D"  # boundary inclusive
    assert _score_to_grade(0.10) == "F"
    assert _score_to_grade(0.0) == "F"  # boundary inclusive


# ---------------------------------------------------------------------------
# _compute_accuracy unit test
# ---------------------------------------------------------------------------


def test_compute_accuracy(grade_agent):
    """Win rate reflects proportion of positive PnL entries in the buffer."""
    # Manually populate the pnl buffer: 3 wins, 2 losses
    for pnl in [10.0, -5.0, 20.0, -3.0, 15.0]:
        grade_agent._pnl_buffer.append(pnl)

    accuracy = grade_agent._compute_accuracy(lookback_n=5)
    assert accuracy == pytest.approx(3 / 5)


def test_compute_accuracy_empty_buffer(grade_agent):
    """Empty buffer returns neutral default of 0.5."""
    accuracy = grade_agent._compute_accuracy(lookback_n=20)
    assert accuracy == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Consecutive low-grade tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_consecutive_low_grades_tracked(grade_agent):
    """Three D-grade actions should increment _consecutive_low_grades to 3."""
    grade_payload_d = {
        "score_pct": 38.0,
        "metrics": {"accuracy": 0.4, "ic": -0.1},
    }
    # Directly invoke _take_grade_action three times with grade 'D'
    await grade_agent._take_grade_action("D", grade_payload_d)
    await grade_agent._take_grade_action("D", grade_payload_d)
    await grade_agent._take_grade_action("D", grade_payload_d)

    assert grade_agent._consecutive_low_grades == 3


@pytest.mark.asyncio
@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_consecutive_low_grades_reset_on_good_grade(grade_agent):
    """A grade of B or better resets the consecutive low-grade counter."""
    grade_payload = {"score_pct": 38.0, "metrics": {"accuracy": 0.4, "ic": -0.1}}
    await grade_agent._take_grade_action("D", grade_payload)
    await grade_agent._take_grade_action("D", grade_payload)

    assert grade_agent._consecutive_low_grades == 2

    # Now a 'B' grade should reset the counter
    good_payload = {"score_pct": 72.0, "metrics": {"accuracy": 0.7, "ic": 0.2}}
    await grade_agent._take_grade_action("B", good_payload)

    assert grade_agent._consecutive_low_grades == 0
