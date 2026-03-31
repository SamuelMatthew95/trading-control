"""Tests for ICUpdater — Spearman factor reweighting logic."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import ICUpdater

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared mock infrastructure
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
async def fake_redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def ic_updater(mock_bus, mock_dlq, agent_state, fake_redis):
    return ICUpdater(mock_bus, mock_dlq, fake_redis, agent_state=agent_state)


# ---------------------------------------------------------------------------
# Buffer accumulation tests
# ---------------------------------------------------------------------------


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_accumulates_score_pnl_buffer(ic_updater):
    """Each trade_performance event adds a (score, pnl) pair to the buffer."""
    await ic_updater.process("trade_performance", "id-1", {"pnl": 5.0, "trace_id": None})
    await ic_updater.process("trade_performance", "id-2", {"pnl": -3.0, "trace_id": None})

    assert ic_updater._fills == 2
    assert len(ic_updater._score_pnl_buffer) == 2


# ---------------------------------------------------------------------------
# Trigger threshold tests
# ---------------------------------------------------------------------------


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_insufficient_data_skips_recompute(ic_updater):
    """With fewer than IC_UPDATE_EVERY_N_FILLS fills, _recompute_and_publish is not called."""
    # Default IC_UPDATE_EVERY_N_FILLS = 10; send only 9 fills
    with patch.object(
        ic_updater, "_recompute_and_publish", new_callable=AsyncMock
    ) as mock_recompute:
        for i in range(9):
            await ic_updater.process(
                "trade_performance", f"id-{i}", {"pnl": float(i), "trace_id": None}
            )

        mock_recompute.assert_not_called()


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_spearman_ic_computed(ic_updater):
    """At exactly IC_UPDATE_EVERY_N_FILLS fills, _recompute_and_publish is called once."""
    with patch.object(
        ic_updater, "_recompute_and_publish", new_callable=AsyncMock
    ) as mock_recompute:
        for i in range(10):
            await ic_updater.process(
                "trade_performance", f"id-{i}", {"pnl": float(i), "trace_id": None}
            )

        mock_recompute.assert_called_once()


# ---------------------------------------------------------------------------
# IC computation behaviour tests (against real _recompute_and_publish)
# ---------------------------------------------------------------------------


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_factor_below_threshold_zeroed(ic_updater, fake_redis):
    """Factors whose abs(IC) <= IC_ZERO_THRESHOLD receive a weight of 0.0.

    When all factors fall below the threshold the code falls back to
    {"composite_score": 1.0}.  We force that path by mocking
    _spearman_correlation to return 0.0 (below the default IC_ZERO_THRESHOLD
    of 0.05) for every call.
    """
    for i in range(10):
        ic_updater._score_pnl_buffer.append((float(i) / 10, float(i)))

    with patch(
        "api.services.agents.pipeline_agents._spearman_correlation",
        return_value=0.0,
    ):
        await ic_updater._recompute_and_publish()

    raw = await fake_redis.get("alpha:ic_weights")
    assert raw is not None
    weights = json.loads(raw)

    # Both factors zeroed → fallback to {"composite_score": 1.0}
    assert weights == {"composite_score": 1.0}


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_weights_normalize_to_one(ic_updater, fake_redis):
    """When multiple factors have IC above threshold, their weights sum to 1.0."""
    # Create pairs that yield a clear positive correlation for composite_score
    # scores=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    # pnls follow the same direction → strong positive IC
    for i in range(10):
        ic_updater._score_pnl_buffer.append((float(i + 1) / 10, float(i + 1)))

    await ic_updater._recompute_and_publish()

    raw = await fake_redis.get("alpha:ic_weights")
    assert raw is not None
    weights = json.loads(raw)

    total = sum(weights.values())
    assert total == pytest.approx(1.0, abs=1e-5)


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_redis_set_called(ic_updater, fake_redis):
    """After trigger, the "alpha:ic_weights" key must be written to Redis."""
    for i in range(10):
        ic_updater._score_pnl_buffer.append((float(i + 1) / 10, float(i + 1)))

    await ic_updater._recompute_and_publish()

    stored = await fake_redis.get("alpha:ic_weights")
    assert stored is not None, "Expected 'alpha:ic_weights' to be set in Redis"


@patch("api.services.agents.pipeline_agents.AsyncSessionFactory", _MockSessionFactory())
async def test_publishes_to_factor_ic_history(ic_updater, mock_bus, fake_redis):
    """After recompute, bus.publish must be called with 'factor_ic_history' stream."""
    for i in range(10):
        ic_updater._score_pnl_buffer.append((float(i + 1) / 10, float(i + 1)))

    await ic_updater._recompute_and_publish()

    published_streams = [call[0][0] for call in mock_bus.publish.call_args_list]
    assert "factor_ic_history" in published_streams
