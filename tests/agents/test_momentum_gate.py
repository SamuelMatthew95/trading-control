"""Regression tests for ExecutionEngine._compute_final_score() gate formula.

The fix: historical_perf default was changed from 0.5 to 0.6.
Old default caused MOMENTUM signals (confidence=0.55) to score 0.54 and be
gated. New default gives 0.56 > 0.55 so they execute.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import AGENT_EXECUTION, EXECUTION_DECISION_THRESHOLD
from api.services.execution.execution_engine import ExecutionEngine

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixture — minimal ExecutionEngine instance (no DB, no Redis needed)
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> ExecutionEngine:
    bus = MagicMock()
    bus.redis = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.publish = AsyncMock()

    dlq = MagicMock()
    dlq.push = AsyncMock()
    dlq.should_dlq = AsyncMock(return_value=False)
    dlq.redis = AsyncMock()

    redis_client = AsyncMock()
    broker = MagicMock()

    return ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis_client, broker=broker)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_compute_final_score_momentum_executes_with_new_default(engine):
    """MOMENTUM tier (confidence=0.55) now clears the gate with historical_perf=0.6 default."""
    score = engine._compute_final_score(0.55, 0.55)
    assert score > EXECUTION_DECISION_THRESHOLD
    assert abs(score - 0.56) < 0.001


def test_compute_final_score_momentum_would_have_failed_old_default(engine):
    """Old historical_perf=0.5 caused MOMENTUM signals to be gated — regression proof."""
    score = engine._compute_final_score(0.55, 0.55, historical_perf=0.5)
    assert score < EXECUTION_DECISION_THRESHOLD


def test_compute_final_score_strong_momentum_always_executes(engine):
    """STRONG_MOMENTUM tier (confidence=0.8) clears the gate comfortably."""
    score = engine._compute_final_score(0.8, 0.8)
    assert score > EXECUTION_DECISION_THRESHOLD


def test_compute_final_score_low_confidence_gated(engine):
    """Very weak signal is correctly blocked by the gate."""
    score = engine._compute_final_score(0.2, 0.2)
    assert score < EXECUTION_DECISION_THRESHOLD


def test_compute_final_score_historical_perf_override(engine):
    """Exact arithmetic: 0.55*0.50 + 0.55*0.30 + 0.60*0.20 = 0.56."""
    expected = 0.55 * 0.50 + 0.55 * 0.30 + 0.60 * 0.20
    score = engine._compute_final_score(0.55, 0.55)
    assert abs(score - expected) < 1e-9
    assert abs(score - 0.56) < 0.001
