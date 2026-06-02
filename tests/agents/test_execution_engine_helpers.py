"""Tests for the pure utility functions in decision_utils and the engine's thin wrappers.

Pure functions (parse_decision_fields, extract_decision_scores, compute_execution_score,
check_execution_gate) are tested without any async or mocking — just inputs and outputs.

The engine wrapper methods (_parse_and_validate, _check_pre_execution_gates) are tested
to verify they call the right pure functions and emit the expected side effects
(logging + heartbeats).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import EXECUTION_DECISION_THRESHOLD
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.decision_utils import (
    ParsedDecision,
    check_execution_gate,
    compute_execution_score,
    extract_decision_scores,
    parse_decision_fields,
)
from api.services.execution.execution_engine import ExecutionEngine

# ---------------------------------------------------------------------------
# Minimal engine for wrapper-method tests only
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    broker = MagicMock(spec=PaperBroker)
    broker.place_order = AsyncMock()
    broker.get_position = AsyncMock(return_value={})
    return ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)


# ============================================================================
# extract_decision_scores — pure function, no fixtures needed
# ============================================================================


def test_extract_scores_from_composite_score():
    sc, rs = extract_decision_scores({"composite_score": "0.8"})
    assert sc == pytest.approx(0.8)
    assert rs == pytest.approx(0.8)  # reasoning_score falls back to signal_confidence


def test_extract_scores_from_signal_confidence():
    sc, rs = extract_decision_scores({"signal_confidence": "0.7"})
    assert sc == pytest.approx(0.7)
    assert rs == pytest.approx(0.7)


def test_extract_scores_reasoning_score_overrides_fallback():
    sc, rs = extract_decision_scores({"signal_confidence": "0.7", "reasoning_score": "0.6"})
    assert sc == pytest.approx(0.7)
    assert rs == pytest.approx(0.6)


def test_extract_scores_defaults_when_all_absent():
    sc, rs = extract_decision_scores({})
    assert sc == pytest.approx(0.5)
    assert rs == pytest.approx(0.5)


def test_extract_scores_empty_string_means_absent():
    """EventBus serialises None → '' which must fall through to the default."""
    sc, rs = extract_decision_scores({"signal_confidence": ""})
    assert sc == pytest.approx(0.5)
    assert rs == pytest.approx(0.5)


def test_extract_scores_zero_string_stays_zero():
    """Redis stores '0.0'; must stay 0.0, not be promoted to the 0.5 default."""
    sc, rs = extract_decision_scores({"composite_score": "0.0"})
    assert sc == pytest.approx(0.0)
    assert rs == pytest.approx(0.0)


def test_extract_scores_python_float_zero_stays_zero():
    """Python float 0.0 is falsy; must stay 0.0, not be promoted to 0.5."""
    sc, rs = extract_decision_scores({"signal_confidence": 0.0})
    assert sc == pytest.approx(0.0)
    assert rs == pytest.approx(0.0)


def test_extract_scores_malformed_string_falls_through():
    """'n/a' (or any non-numeric) must fall through gracefully, not raise ValueError."""
    sc, rs = extract_decision_scores({"signal_confidence": "n/a", "composite_score": "0.7"})
    assert sc == pytest.approx(0.7)  # falls through to composite_score
    assert rs == pytest.approx(0.7)


def test_extract_scores_all_malformed_defaults_to_half():
    """All fields malformed → default 0.5, no exception raised."""
    sc, rs = extract_decision_scores({"signal_confidence": "n/a", "composite_score": "bad"})
    assert sc == pytest.approx(0.5)
    assert rs == pytest.approx(0.5)


def test_extract_scores_signal_confidence_takes_priority_over_composite():
    sc, _ = extract_decision_scores({"signal_confidence": "0.9", "composite_score": "0.6"})
    assert sc == pytest.approx(0.9)


# ============================================================================
# compute_execution_score — pure function
# ============================================================================


def test_compute_score_momentum_tier_passes_gate():
    """0.55 confidence → score > 0.55 with default historical_perf=0.6."""
    score = compute_execution_score(0.55, 0.55)
    assert score > EXECUTION_DECISION_THRESHOLD


def test_compute_score_low_confidence_below_gate():
    score = compute_execution_score(0.2, 0.2)
    assert score < EXECUTION_DECISION_THRESHOLD


def test_compute_score_strong_confidence_passes():
    score = compute_execution_score(0.8, 0.8)
    assert score > EXECUTION_DECISION_THRESHOLD


def test_compute_score_weights_sum_to_one():
    """With equal inputs the weights (0.5+0.3+0.2=1.0) mean score == input."""
    score = compute_execution_score(1.0, 1.0, historical_perf=1.0)
    assert score == pytest.approx(1.0)


def test_compute_score_historical_perf_matters():
    low = compute_execution_score(0.55, 0.55, historical_perf=0.0)
    high = compute_execution_score(0.55, 0.55, historical_perf=1.0)
    assert high > low


# ============================================================================
# parse_decision_fields — pure function
# ============================================================================


def _valid():
    return {
        "symbol": "BTC/USD",
        "action": "buy",
        "qty": 1.0,
        "price": 50000.0,
        "strategy_id": "strat-1",
        "trace_id": "trace-1",
    }


def test_parse_valid_returns_named_tuple():
    parsed, err = parse_decision_fields(_valid())
    assert err is None
    assert isinstance(parsed, ParsedDecision)
    assert parsed.side == "buy"
    assert parsed.symbol == "BTC/USD"
    assert parsed.qty == pytest.approx(1.0)
    assert parsed.price == pytest.approx(50000.0)


def test_parse_uses_action_field():
    parsed, _ = parse_decision_fields({**_valid(), "action": "sell"})
    assert parsed.side == "sell"


def test_parse_falls_back_to_side_field():
    payload = {k: v for k, v in _valid().items() if k != "action"}
    payload["side"] = "sell"
    parsed, _ = parse_decision_fields(payload)
    assert parsed.side == "sell"


def test_parse_normalises_side_to_lowercase():
    parsed, _ = parse_decision_fields({**_valid(), "action": "BUY"})
    assert parsed.side == "buy"


def test_parse_missing_symbol_returns_error():
    payload = {k: v for k, v in _valid().items() if k != "symbol"}
    parsed, err = parse_decision_fields(payload)
    assert parsed is None
    assert "missing_fields" in err


def test_parse_missing_qty_returns_error():
    payload = {k: v for k, v in _valid().items() if k != "qty"}
    parsed, err = parse_decision_fields(payload)
    assert parsed is None
    assert err is not None


def test_parse_missing_action_and_side_returns_error():
    payload = {k: v for k, v in _valid().items() if k != "action"}
    parsed, err = parse_decision_fields(payload)
    assert parsed is None
    assert err is not None


def test_parse_non_numeric_qty_returns_error():
    parsed, err = parse_decision_fields({**_valid(), "qty": "not-a-number"})
    assert parsed is None
    assert "invalid_fields" in err


def test_parse_negative_qty_returns_error():
    parsed, err = parse_decision_fields({**_valid(), "qty": -1.0})
    assert parsed is None
    assert "non_positive" in err


def test_parse_zero_qty_returns_error():
    parsed, err = parse_decision_fields({**_valid(), "qty": 0.0})
    assert parsed is None
    assert err is not None


def test_parse_zero_price_returns_error():
    parsed, err = parse_decision_fields({**_valid(), "price": 0.0})
    assert parsed is None
    assert err is not None


def test_parse_generates_strategy_id_when_absent():
    payload = {k: v for k, v in _valid().items() if k != "strategy_id"}
    parsed, _ = parse_decision_fields(payload)
    assert parsed is not None
    assert parsed.strategy_id  # UUID generated


def test_parse_generates_trace_id_when_absent():
    payload = {k: v for k, v in _valid().items() if k != "trace_id"}
    parsed, _ = parse_decision_fields(payload)
    assert parsed is not None
    assert parsed.trace_id  # UUID generated


# ============================================================================
# check_execution_gate — pure function
# ============================================================================


def test_gate_hold_is_blocked():
    assert check_execution_gate("hold", "BTC/USD", 0.9, 0.55, True) is not None


def test_gate_reject_is_blocked():
    assert check_execution_gate("reject", "BTC/USD", 0.9, 0.55, True) is not None


def test_gate_flat_is_blocked():
    assert check_execution_gate("flat", "BTC/USD", 0.9, 0.55, True) is not None


def test_gate_hold_reason_prefix():
    reason = check_execution_gate("hold", "BTC/USD", 0.9, 0.55, True)
    assert reason.startswith("hold:")


def test_gate_score_below_threshold_blocked():
    reason = check_execution_gate("buy", "BTC/USD", 0.3, 0.55, True)
    assert reason is not None
    assert "gated:score" in reason


def test_gate_score_at_threshold_passes():
    # final_score == threshold (0.55 exactly) should pass
    reason = check_execution_gate("buy", "BTC/USD", 0.55, 0.55, True)
    assert reason is None


def test_gate_score_above_threshold_passes():
    reason = check_execution_gate("buy", "BTC/USD", 0.8, 0.55, True)
    assert reason is None


def test_gate_market_closed_blocks_when_flagged():
    reason = check_execution_gate("buy", "AAPL", 0.8, 0.55, market_open=False)
    assert reason == "blocked:market_closed"


def test_gate_market_open_passes():
    reason = check_execution_gate("buy", "AAPL", 0.8, 0.55, market_open=True)
    assert reason is None


def test_gate_all_pass_returns_none():
    reason = check_execution_gate("buy", "BTC/USD", 0.8, 0.55, True)
    assert reason is None


# ============================================================================
# Engine wrapper: _parse_and_validate (adds logging + heartbeat)
# ============================================================================


@pytest.mark.asyncio
async def test_engine_wrapper_returns_parsed_on_valid_input(engine):
    result = await engine._parse_and_validate(_valid())
    assert isinstance(result, ParsedDecision)


@pytest.mark.asyncio
async def test_engine_wrapper_returns_none_and_logs_on_missing_field(engine):
    payload = {k: v for k, v in _valid().items() if k != "symbol"}
    result = await engine._parse_and_validate(payload)
    assert result is None


# ============================================================================
# Engine wrapper: _check_pre_execution_gates (adds logging + heartbeat)
# ============================================================================


@pytest.mark.asyncio
async def test_engine_gate_hold_returns_reason(engine):
    reason = await engine._check_pre_execution_gates("hold", "BTC/USD", 0.9, 0.9, "t1")
    assert reason is not None
    assert "hold" in reason


@pytest.mark.asyncio
async def test_engine_gate_low_score_returns_reason(engine):
    reason = await engine._check_pre_execution_gates("buy", "BTC/USD", 0.2, 0.2, "t1")
    assert reason is not None
    assert "gated:score" in reason


@pytest.mark.asyncio
async def test_engine_gate_all_clear_returns_none(engine):
    reason = await engine._check_pre_execution_gates("buy", "BTC/USD", 0.8, 0.8, "t1")
    assert reason is None


# ============================================================================
# Execution-phase tool telemetry — risk cage / VWAP / bracket go live in the
# tool registry so the governance panel stops showing them as permanent priors.
# ============================================================================


@pytest.mark.asyncio
async def test_risk_cage_tool_recorded_on_every_gate_evaluation(engine):
    """The deterministic risk cage records one telemetry sample per evaluated
    trade regardless of whether a gate fires."""
    from api.constants import TOOL_RISK_CAGE  # noqa: PLC0415
    from api.services.tool_registry import get_tool_registry  # noqa: PLC0415

    before = get_tool_registry().get(TOOL_RISK_CAGE).call_count
    await engine._check_pre_execution_gates("buy", "BTC/USD", 0.8, 0.8, "t1")  # clears
    await engine._check_pre_execution_gates("buy", "BTC/USD", 0.2, 0.2, "t2")  # gated
    cage = get_tool_registry().get(TOOL_RISK_CAGE)
    assert cage.call_count == before + 2
    assert cage.success_count >= before + 2  # cage executes successfully either way


def test_vwap_tool_recorded_only_when_a_slicing_plan_is_built(engine):
    from api.constants import LARGE_ORDER_THRESHOLD, TOOL_VWAP_EXECUTION  # noqa: PLC0415
    from api.services.tool_registry import get_tool_registry  # noqa: PLC0415

    before = get_tool_registry().get(TOOL_VWAP_EXECUTION).call_count
    # Small order: no VWAP slicing, so no tool call.
    assert engine._build_vwap_plan(LARGE_ORDER_THRESHOLD) is None
    assert get_tool_registry().get(TOOL_VWAP_EXECUTION).call_count == before
    # Large order: a slicing plan is produced and the tool is recorded.
    plan = engine._build_vwap_plan(LARGE_ORDER_THRESHOLD * 10)
    assert plan is not None
    assert get_tool_registry().get(TOOL_VWAP_EXECUTION).call_count == before + 1


def test_vwap_execution_tool_seeds_neutral_alpha():
    """Execution mechanics are graded on reliability, not directional alpha — the
    VWAP prior must be neutral so a live call never displays fake earned edge."""
    from api.constants import TOOL_VWAP_EXECUTION  # noqa: PLC0415
    from api.services.tool_registry import default_tools  # noqa: PLC0415

    vwap = next(t for t in default_tools() if t.name == TOOL_VWAP_EXECUTION)
    assert vwap.alpha_score == 0.0
