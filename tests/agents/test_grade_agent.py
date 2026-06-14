"""Tests for GradeAgent — real performance scoring logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.constants import (
    STREAM_AGENT_GRADES,
    STREAM_NOTIFICATIONS,
    FieldName,
    Severity,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.grade_analytics import DIRECTION_DROP, build_self_correction
from api.services.agents.pipeline_agents import GradeAgent
from api.services.agents.scoring import normalize_ic as _normalize_ic
from api.services.agents.scoring import score_to_grade as _score_to_grade
from api.services.agents.scoring import spearman_correlation as _spearman_correlation

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
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_accumulates_fills_from_trade_performance(grade_agent):
    """Each trade_performance event increments _fills and populates _pnl_buffer."""
    await grade_agent.process("trade_performance", "id-1", {"pnl": 10.0})
    await grade_agent.process("trade_performance", "id-2", {"pnl": -5.0})
    await grade_agent.process("trade_performance", "id-3", {"pnl": 20.0})

    assert grade_agent._fills == 3
    assert list(grade_agent._pnl_buffer) == [10.0, -5.0, 20.0]


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_paired_close_events_graded_once(grade_agent):
    """A round-trip close arrives on BOTH trade_performance and trade_completed
    (same trace_id, same realized PnL). It must grade once — otherwise the
    durable agent PnL store and every fill counter double-counts each trade."""
    from api.constants import PNL_GRADED_AGENTS
    from api.services.agent_pnl_store import set_agent_pnl_store

    recorded: list[tuple[str, float]] = []

    class _CaptureStore:
        async def record_trade(self, agent_name: str, pnl: float) -> None:
            recorded.append((agent_name, pnl))

    close = {"pnl": 42.0, "trace_id": "trace-close-1"}
    set_agent_pnl_store(_CaptureStore())
    try:
        await grade_agent.process("trade_performance", "id-1", close)
        await grade_agent.process("trade_completed", "id-2", dict(close))
    finally:
        set_agent_pnl_store(None)

    assert grade_agent._fills == 1
    assert list(grade_agent._pnl_buffer) == [42.0]
    # One attribution per graded agent — not two.
    assert len(recorded) == len(PNL_GRADED_AGENTS)


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_opening_fill_does_not_consume_decision_tool_cache(grade_agent):
    """An opening fill (pnl None) must NOT pop the cached decision tools —
    popping before validating PnL destroyed entry-tool attribution and logged
    a spurious error per open."""
    from api.constants import FieldName

    grade_agent._trace_tools["trace-open-1"] = ["tool_a"]
    grade_agent._attribute_pnl_to_tools({FieldName.TRACE_ID: "trace-open-1", FieldName.PNL: None})
    assert "trace-open-1" in grade_agent._trace_tools

    # The bus serializes None to "" — same outcome required.
    grade_agent._attribute_pnl_to_tools({FieldName.TRACE_ID: "trace-open-1", FieldName.PNL: ""})
    assert "trace-open-1" in grade_agent._trace_tools


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_accumulates_confidence_from_executions(grade_agent):
    """Each executions event populates _confidence_buffer from the confidence field."""
    await grade_agent.process("executions", "id-1", {"confidence": 0.9})
    await grade_agent.process("executions", "id-2", {"confidence": 0.6})

    assert list(grade_agent._confidence_buffer) == [0.9, 0.6]


# ---------------------------------------------------------------------------
# Grade trigger tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
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
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
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

    accuracy = grade_agent._win_rate(lookback_n=5)
    assert accuracy == pytest.approx(3 / 5)


def test_compute_accuracy_empty_buffer(grade_agent):
    """Empty buffer returns neutral default of 0.5."""
    accuracy = grade_agent._win_rate(lookback_n=20)
    assert accuracy == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Consecutive low-grade tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_consecutive_low_grades_tracked(grade_agent):
    """Three D-grade actions should increment _consecutive_low_grades to 3."""
    grade_agent._fills = 25  # above GRADE_ACTION_MIN_FILLS so actions are live
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
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_consecutive_low_grades_reset_on_good_grade(grade_agent):
    """A grade of B or better resets the consecutive low-grade counter."""
    grade_agent._fills = 25  # above GRADE_ACTION_MIN_FILLS so actions are live
    grade_payload = {"score_pct": 38.0, "metrics": {"accuracy": 0.4, "ic": -0.1}}
    await grade_agent._take_grade_action("D", grade_payload)
    await grade_agent._take_grade_action("D", grade_payload)

    assert grade_agent._consecutive_low_grades == 2

    # Now a 'B' grade should reset the counter
    good_payload = {"score_pct": 72.0, "metrics": {"accuracy": 0.7, "ic": 0.2}}
    await grade_agent._take_grade_action("B", good_payload)

    assert grade_agent._consecutive_low_grades == 0


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_grade_f_does_not_pause_on_insufficient_sample(grade_agent, mock_bus):
    """SAFETY: a Grade F on too few fills must NOT emit a retirement (pause)
    proposal — a handful of noisy trades cannot hard-pause the system."""
    grade_agent._fills = 3  # below GRADE_ACTION_MIN_FILLS (20)
    payload = {"score_pct": 18.0, "metrics": {"accuracy": 0.2, "ic": -0.3}}
    await grade_agent._take_grade_action("F", payload)

    proposal_publishes = [
        c for c in mock_bus.publish.call_args_list if c.args and c.args[0] == "proposals"
    ]
    assert proposal_publishes == []  # no retirement/destructive proposal
    assert grade_agent._consecutive_low_grades == 0  # noisy grade not counted


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_grade_f_pauses_with_sufficient_sample(grade_agent, mock_bus):
    """With enough graded fills, a Grade F does emit the retirement proposal."""
    grade_agent._fills = 25  # above GRADE_ACTION_MIN_FILLS
    payload = {"score_pct": 18.0, "metrics": {"accuracy": 0.2, "ic": -0.3}}
    await grade_agent._take_grade_action("F", payload)

    proposal_publishes = [
        c for c in mock_bus.publish.call_args_list if c.args and c.args[0] == "proposals"
    ]
    assert len(proposal_publishes) == 1
    assert proposal_publishes[0].args[1]["proposal_type"] == "agent_retirement"


# ---------------------------------------------------------------------------
# Self-correction analytics wiring (anomaly detection + trajectory)
# ---------------------------------------------------------------------------


def _dim(accuracy=0.8, ic=0.6, cost=0.5, latency=0.8):
    return {
        FieldName.ACCURACY: accuracy,
        FieldName.IC_NORMALIZED: ic,
        FieldName.COST_NORMALIZED: cost,
        FieldName.LATENCY_SCORE: latency,
    }


def test_self_correction_grows_history_and_excludes_current_grade(grade_agent):
    """Each cycle is folded into history and judged against only the prior ones."""
    for score in [0.80, 0.81, 0.79, 0.80, 0.82, 0.80]:
        diagnostic = grade_agent._self_correction(score, _dim())
        # While building the stable baseline nothing should fire.
        assert diagnostic[FieldName.ANOMALY_DETECTED] is False

    assert len(grade_agent._grade_score_history) == 6

    # A sharp drop, attributed to accuracy, is flagged against the prior baseline.
    drop = grade_agent._self_correction(0.30, _dim(accuracy=0.2))
    assert drop[FieldName.ANOMALY_DETECTED] is True
    assert drop[FieldName.DIRECTION] == DIRECTION_DROP
    assert drop[FieldName.ATTRIBUTION][0][FieldName.DIMENSION] == FieldName.ACCURACY
    assert len(grade_agent._grade_score_history) == 7


@pytest.mark.asyncio
async def test_emit_alert_publishes_notification_on_drop(grade_agent, mock_bus):
    baseline = [0.80, 0.81, 0.79, 0.80, 0.82, 0.80]
    diagnostic = build_self_correction(
        baseline, 0.30, [_dim()] * len(baseline), _dim(accuracy=0.2), [*baseline, 0.30]
    )
    await grade_agent._emit_self_correction_alert(diagnostic, "trace-xyz")

    notif_calls = [
        call
        for call in mock_bus.publish.call_args_list
        if call.args and call.args[0] == STREAM_NOTIFICATIONS
    ]
    assert len(notif_calls) == 1
    published = notif_calls[0].args[1]
    assert published[FieldName.NOTIFICATION_TYPE] == "grade_self_correction"
    assert published[FieldName.SEVERITY] == Severity.WARNING
    assert FieldName.SELF_CORRECTION in published[FieldName.PAYLOAD]


@pytest.mark.asyncio
async def test_emit_alert_is_noop_when_healthy(grade_agent, mock_bus):
    stable = [0.80] * 6
    diagnostic = build_self_correction(
        stable, 0.81, [_dim()] * len(stable), _dim(), [*stable, 0.81]
    )
    await grade_agent._emit_self_correction_alert(diagnostic, "trace-xyz")

    notif_calls = [
        call
        for call in mock_bus.publish.call_args_list
        if call.args and call.args[0] == STREAM_NOTIFICATIONS
    ]
    assert notif_calls == []


@pytest.mark.asyncio
@patch("api.redis_client.get_redis", new_callable=AsyncMock)
@patch("api.services.agents.grade_agent._write_heartbeat", new_callable=AsyncMock)
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_grade_payload_embeds_self_correction(_hb, _redis, grade_agent, mock_bus):
    """The published agent_grades payload carries the self-correction diagnostic."""
    for _ in range(10):
        grade_agent._pnl_buffer.append(1.0)
        grade_agent._confidence_buffer.append(0.7)

    await grade_agent._compute_and_publish_grade()

    grade_calls = [
        call
        for call in mock_bus.publish.call_args_list
        if call.args and call.args[0] == STREAM_AGENT_GRADES
    ]
    assert grade_calls, "expected an agent_grades publish"
    payload = grade_calls[-1].args[1]
    assert FieldName.SELF_CORRECTION in payload
    diagnostic = payload[FieldName.SELF_CORRECTION]
    assert FieldName.TRAJECTORY in diagnostic
    assert FieldName.ATTRIBUTION in diagnostic


@pytest.mark.asyncio
async def test_self_correction_alert_is_edge_triggered(grade_agent, mock_bus):
    """Alert fires once on entering drop/decay, stays quiet until recovery."""
    baseline = [0.80, 0.81, 0.79, 0.80, 0.82, 0.80]
    drop = build_self_correction(
        baseline, 0.30, [_dim()] * len(baseline), _dim(accuracy=0.2), [*baseline, 0.30]
    )
    healthy = build_self_correction([0.80] * 6, 0.81, [_dim()] * 6, _dim(), [0.80] * 6 + [0.81])

    def notif_count():
        return sum(
            1
            for call in mock_bus.publish.call_args_list
            if call.args and call.args[0] == STREAM_NOTIFICATIONS
        )

    await grade_agent._emit_self_correction_alert(drop, "t1")
    assert notif_count() == 1  # entered drop → one alert
    await grade_agent._emit_self_correction_alert(drop, "t2")
    assert notif_count() == 1  # still in drop → no re-page
    await grade_agent._emit_self_correction_alert(healthy, "t3")
    assert notif_count() == 1  # recovered → latch resets, no alert
    await grade_agent._emit_self_correction_alert(drop, "t4")
    assert notif_count() == 2  # new episode after recovery → fires again


# ---------------------------------------------------------------------------
# Tool-governance proposal emission (closes the "it's not automating" loop)
# ---------------------------------------------------------------------------


def _suggestion(tool, action, severity="warning", reason="r"):
    from api.services.tool_registry import ToolSuggestion

    return ToolSuggestion(tool=tool, action=action, severity=severity, reason=reason)


@pytest.mark.asyncio
async def test_tool_governance_emits_proposal_for_actionable_suggestions(grade_agent, mock_bus):
    """Actionable tool suggestions (disable/review) are published as a proposal
    + notification — the registry's advice now reaches the operator as an
    approval-gated proposal, not just a passive panel."""
    from api.constants import STREAM_PROPOSALS, ProposalType

    suggestions = [
        _suggestion("get_ic_weights", "disable", reason="negative alpha"),
        _suggestion("top_tool", "prioritize", severity="info", reason="highest alpha"),
    ]
    with patch(
        "api.services.agents.grade_agent.get_tool_registry",
        return_value=MagicMock(suggest_tool_changes=MagicMock(return_value=suggestions)),
    ):
        await grade_agent._emit_tool_governance("trace-tg")

    proposal_calls = [
        c for c in mock_bus.publish.call_args_list if c.args and c.args[0] == STREAM_PROPOSALS
    ]
    assert len(proposal_calls) == 1
    payload = proposal_calls[0].args[1]
    assert payload[FieldName.PROPOSAL_TYPE] == ProposalType.TOOL_GOVERNANCE
    assert payload[FieldName.REQUIRES_APPROVAL] is True
    # The full suggestion list (incl. the prioritize hint) rides along.
    assert len(payload[FieldName.CONTENT][FieldName.SUGGESTIONS]) == 2
    # Per-tool attribution (how each tool is performing) rides along too.
    assert FieldName.ATTRIBUTION in payload[FieldName.CONTENT]


@pytest.mark.asyncio
async def test_tool_governance_noop_when_only_informational(grade_agent, mock_bus):
    """A 'prioritize'-only set is informational — no proposal is emitted."""
    from api.constants import STREAM_PROPOSALS

    with patch(
        "api.services.agents.grade_agent.get_tool_registry",
        return_value=MagicMock(
            suggest_tool_changes=MagicMock(return_value=[_suggestion("t", "prioritize", "info")])
        ),
    ):
        await grade_agent._emit_tool_governance("trace-tg")

    assert [
        c for c in mock_bus.publish.call_args_list if c.args and c.args[0] == STREAM_PROPOSALS
    ] == []


@pytest.mark.asyncio
async def test_tool_governance_is_edge_triggered(grade_agent, mock_bus):
    """An unchanged suggestion set is not re-proposed every cycle."""
    from api.constants import STREAM_PROPOSALS

    suggestions = [_suggestion("dead_tool", "disable")]
    registry = MagicMock(suggest_tool_changes=MagicMock(return_value=suggestions))
    with patch("api.services.agents.grade_agent.get_tool_registry", return_value=registry):
        await grade_agent._emit_tool_governance("trace-1")
        await grade_agent._emit_tool_governance("trace-2")  # same set — skipped

    proposal_calls = [
        c for c in mock_bus.publish.call_args_list if c.args and c.args[0] == STREAM_PROPOSALS
    ]
    assert len(proposal_calls) == 1


# ---------------------------------------------------------------------------
# Tool grading — realized trade PnL attributed back to the decision's tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trade_pnl_attributed_to_decision_tools(grade_agent):
    """A decision records which tools it used; when that trade closes, the
    realized PnL is folded into those tools' alpha — outcome-driven tool grading,
    not a decision-time-only signal."""
    from api.constants import STREAM_DECISIONS, STREAM_TRADE_COMPLETED, ToolPhase
    from api.services.tool_registry import ToolMetadata, ToolRegistry, set_tool_registry

    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="get_ic_weights", phase=ToolPhase.MEMORY, description="d", alpha_score=0.0
        )
    )
    set_tool_registry(registry)
    try:
        # 1) decision for trace-T used get_ic_weights
        await grade_agent.process(
            STREAM_DECISIONS,
            "1-0",
            {
                FieldName.TRACE_ID: "trace-T",
                FieldName.TOOLS_USED: [{FieldName.NAME: "get_ic_weights"}],
            },
        )
        # 2) that trade closes with a positive realized PnL
        await grade_agent.process(
            STREAM_TRADE_COMPLETED,
            "2-0",
            {FieldName.TRACE_ID: "trace-T", FieldName.PNL: 12.5},
        )

        tool = registry.get("get_ic_weights")
        assert tool.alpha_score > 0.0  # PnL was attributed
        # trace consumed — a duplicate trade event must not double-attribute
        assert "trace-T" not in grade_agent._trace_tools
    finally:
        set_tool_registry(None)


@pytest.mark.asyncio
async def test_trade_without_known_decision_tools_is_noop(grade_agent):
    """A trade whose trace was never seen on the decisions stream attributes
    nothing — no crash, no phantom grading."""
    from api.constants import STREAM_TRADE_COMPLETED, ToolPhase
    from api.services.tool_registry import ToolMetadata, ToolRegistry, set_tool_registry

    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="get_ic_weights", phase=ToolPhase.MEMORY, description="d", alpha_score=0.33
        )
    )
    set_tool_registry(registry)
    try:
        await grade_agent.process(
            STREAM_TRADE_COMPLETED, "3-0", {FieldName.TRACE_ID: "unknown", FieldName.PNL: 9.0}
        )
        assert registry.get("get_ic_weights").alpha_score == 0.33  # unchanged
    finally:
        set_tool_registry(None)


async def test_grade_proposals_carry_measured_backtest_evidence(grade_agent):
    """Every grade proposal must carry a MEASURED ReplayHarness verdict from the
    recent trade buffer — proposals are backtest-backed, not blind guesses."""
    from api.constants import FieldName

    # Seed the eval buffer with a few scored trades (mix of win/loss).
    grade_agent._eval_buffer.extend(
        [
            {FieldName.PNL: 12.0, FieldName.SIDE: "buy"},
            {FieldName.PNL: -4.0, FieldName.SIDE: "sell"},
            {FieldName.PNL: 8.0, FieldName.SIDE: "buy"},
        ]
    )
    evidence = grade_agent._recent_backtest_evidence()
    # The measured block has the gate metrics and reflects the seeded trades.
    assert evidence[FieldName.TRADE_COUNT] == 3
    assert evidence[FieldName.TOTAL_PNL] == pytest.approx(16.0)
    assert "win_rate" in evidence
    assert "false_positive_rate" in evidence


@pytest.mark.asyncio
async def test_attributes_realized_pnl_to_trading_agents(grade_agent):
    """A closed trade's realized PnL is recorded against each trading agent in
    the durable PnL store, so agent_performance can grade them on it."""
    from api.constants import PNL_GRADED_AGENTS, FieldName
    from api.services.agent_pnl_store import set_agent_pnl_store

    recorded: list[tuple[str, float]] = []

    class _CaptureStore:
        async def record_trade(self, agent_name: str, pnl: float) -> None:
            recorded.append((agent_name, pnl))

    set_agent_pnl_store(_CaptureStore())
    try:
        await grade_agent._attribute_pnl_to_agents({FieldName.PNL: 42.0})
    finally:
        set_agent_pnl_store(None)

    assert {name for name, _ in recorded} == set(PNL_GRADED_AGENTS)
    assert all(pnl == 42.0 for _, pnl in recorded)


@pytest.mark.asyncio
async def test_pnl_attribution_noop_without_store(grade_agent):
    """No store installed → attribution is a quiet no-op (never raises)."""
    from api.constants import FieldName
    from api.services.agent_pnl_store import set_agent_pnl_store

    set_agent_pnl_store(None)
    await grade_agent._attribute_pnl_to_agents({FieldName.PNL: 10.0})  # must not raise


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_grade_metrics_carry_fills_graded(grade_agent, monkeypatch):
    """Regression: write_grade_to_db reads FILLS_GRADED from the METRICS dict,
    but the payload only carried it at the top level — every stored grade
    record said fills_graded=None."""
    from api.runtime_state import get_runtime_store

    monkeypatch.setattr(
        "api.services.agents.grade_agent.write_agent_log", AsyncMock(), raising=True
    )
    grade_agent._fills = 5
    grade_agent._pnl_buffer.extend([1.0, -2.0, 3.0])
    await grade_agent._compute_and_publish_grade()

    grades = get_runtime_store().grade_history
    assert grades, "expected a grade record in memory mode"
    assert grades[-1][FieldName.FILLS_GRADED] == 5


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_entry_decision_tools_credited_on_round_trip_close(grade_agent):
    """Regression: a close carries only the CLOSING decision's trace, so the
    BUY-side tools never received PnL attribution — tool alpha graded only the
    exit half of every trade. The entry decision's tools are promoted to the
    symbol slot when its order FILLS, and credited when the round trip closes."""
    from api.constants import (
        STREAM_DECISIONS,
        STREAM_EXECUTIONS,
        STREAM_TRADE_COMPLETED,
        ToolPhase,
    )
    from api.services.tool_registry import ToolMetadata, ToolRegistry, set_tool_registry

    registry = ToolRegistry()
    for name in ("entry_tool", "exit_tool"):
        registry.register(
            ToolMetadata(name=name, phase=ToolPhase.MEMORY, description="d", alpha_score=0.0)
        )
    set_tool_registry(registry)
    try:
        # 1) BUY decision (trace-ENTRY) consulted entry_tool …
        await grade_agent.process(
            STREAM_DECISIONS,
            "1-0",
            {
                FieldName.TRACE_ID: "trace-ENTRY",
                FieldName.SYMBOL: "BTC/USD",
                FieldName.TOOLS_USED: [{FieldName.NAME: "entry_tool"}],
            },
        )
        # 2) … and its order actually FILLED (promotes tools to the symbol slot).
        await grade_agent.process(
            STREAM_EXECUTIONS,
            "2-0",
            {
                FieldName.TRACE_ID: "trace-ENTRY",
                FieldName.SYMBOL: "BTC/USD",
                FieldName.SIDE: "buy",
                FieldName.CONFIDENCE: 0.8,
            },
        )
        # 3) SELL decision (trace-EXIT) consulted exit_tool, then the close fires
        #    carrying ONLY the exit trace.
        await grade_agent.process(
            STREAM_DECISIONS,
            "3-0",
            {
                FieldName.TRACE_ID: "trace-EXIT",
                FieldName.SYMBOL: "BTC/USD",
                FieldName.TOOLS_USED: [{FieldName.NAME: "exit_tool"}],
            },
        )
        await grade_agent.process(
            STREAM_TRADE_COMPLETED,
            "4-0",
            {FieldName.TRACE_ID: "trace-EXIT", FieldName.SYMBOL: "BTC/USD", FieldName.PNL: 10.0},
        )

        assert registry.get("exit_tool").alpha_score > 0.0
        assert registry.get("entry_tool").alpha_score > 0.0  # the previously-lost half
        # Both caches consumed — a redelivered close can't double-credit.
        assert "BTC/USD" not in grade_agent._entry_tools
        assert "trace-EXIT" not in grade_agent._trace_tools
    finally:
        set_tool_registry(None)


@pytest.mark.asyncio
@patch("api.services.agents.grade_agent.AsyncSessionFactory", _MockSessionFactory())
async def test_gated_decision_never_pollutes_entry_attribution(grade_agent):
    """A BUY decision that never fills must NOT leave tools in the symbol slot —
    only executed entries earn attribution rights."""
    from api.constants import STREAM_DECISIONS

    await grade_agent.process(
        STREAM_DECISIONS,
        "1-0",
        {
            FieldName.TRACE_ID: "trace-GATED",
            FieldName.SYMBOL: "ETH/USD",
            FieldName.TOOLS_USED: [{FieldName.NAME: "some_tool"}],
        },
    )
    assert "ETH/USD" not in grade_agent._entry_tools
