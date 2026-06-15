"""Regression tests for ExecutionEngine._compute_final_score() gate formula.

The fix: historical_perf default was changed from 0.5 to 0.6.
Old default caused MOMENTUM signals (confidence=0.55) to score 0.54 and be
gated. New default gives 0.56 > 0.55 so they execute.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import EXECUTION_DECISION_THRESHOLD, SIGNAL_CONFIDENCE_MIN_GATE
from api.services.execution.decision_utils import check_confidence_gate
from api.services.execution.execution_engine import ExecutionEngine

# Signal composite-score tiers produced by classify_signal (score/100).
_LOW_TIER = 0.30
_MOMENTUM_TIER = 0.55
_STRONG_TIER = 0.80

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
    """Old historical_perf=0.5 scored MOMENTUM at 0.54 — below the ORIGINAL 0.55
    gate, which is why the default was raised to 0.6 (a +0.02 lift to 0.56).

    The live execution threshold was later lowered to 0.50 (issue #322:
    too-high gate delayed entries), so this proof pins the historical arithmetic
    that motivated the historical_perf default against the original 0.55 gate
    rather than the now-overridden live constant.
    """
    original_gate = 0.55
    score = engine._compute_final_score(0.55, 0.55, historical_perf=0.5)
    assert abs(score - 0.54) < 0.001
    assert score < original_gate


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


# ---------------------------------------------------------------------------
# Confidence gate must agree with the execution-score gate (the alignment fix)
# ---------------------------------------------------------------------------


def test_confidence_gate_allows_momentum_tier():
    """REGRESSION: a MOMENTUM-tier signal (0.55) must NOT be blocked by the
    confidence gate. At 0.65 it was, which silently nullified the deliberately
    tuned execution-score gate (which lets MOMENTUM clear 0.55) — so no momentum
    trade could ever execute."""
    assert check_confidence_gate(_MOMENTUM_TIER, "buy") is None
    assert check_confidence_gate(_STRONG_TIER, "buy") is None


def test_confidence_gate_blocks_low_tier():
    """LOW/noise (0.30) is still correctly blocked pre-execution."""
    assert check_confidence_gate(_LOW_TIER, "buy") is not None


def test_confidence_gate_consistent_with_execution_score_gate(engine):
    """The two gates must agree: the MOMENTUM tier the confidence gate admits must
    also clear the execution-score gate (with reasoning agreeing), and the LOW tier
    both reject. Guards against re-raising the gate above the MOMENTUM tier."""
    assert SIGNAL_CONFIDENCE_MIN_GATE <= _MOMENTUM_TIER
    # MOMENTUM passes confidence gate AND can clear the execution-score gate.
    assert check_confidence_gate(_MOMENTUM_TIER, "buy") is None
    assert (
        engine._compute_final_score(_MOMENTUM_TIER, _MOMENTUM_TIER) > EXECUTION_DECISION_THRESHOLD
    )
    # LOW fails both gates.
    assert check_confidence_gate(_LOW_TIER, "buy") is not None
    assert engine._compute_final_score(_LOW_TIER, _LOW_TIER) < EXECUTION_DECISION_THRESHOLD


def test_confidence_gate_bypassed_for_advisory_actions():
    """hold/reject/flat never trade, so the gate must not apply to them."""
    assert check_confidence_gate(_LOW_TIER, "hold") is None
