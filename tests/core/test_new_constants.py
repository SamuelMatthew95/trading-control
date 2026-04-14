"""Tests for all new constants added during string-literal refactoring.

Covers: AgentStatus, SOURCE_*, STREAM_*, PIPELINE_STREAMS, Grade,
HypothesisType, ProposalType.NEW_AGENT, REDIS_KEY_PAPER_ORDER,
AGENT_CHALLENGER, and cross-file consistency checks.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# AgentStatus
# ---------------------------------------------------------------------------


def test_agent_status_values() -> None:
    from api.constants import AgentStatus

    assert AgentStatus.ACTIVE == "ACTIVE"
    assert AgentStatus.STALE == "STALE"
    assert AgentStatus.WAITING == "WAITING"


def test_agent_status_is_str() -> None:
    """AgentStatus members must be plain strings so JSON serialisation works."""
    from api.constants import AgentStatus

    for member in AgentStatus:
        assert isinstance(member, str), f"{member!r} is not a str"


def test_agent_status_uppercase() -> None:
    from api.constants import AgentStatus

    for member in AgentStatus:
        assert member == member.upper(), f"{member!r} must be uppercase"


# ---------------------------------------------------------------------------
# SOURCE_* constants
# ---------------------------------------------------------------------------


def test_source_constants_are_lowercase() -> None:
    """Source identifiers must be lowercase_snake_case to match DB source columns."""
    from api.constants import (
        SOURCE_EXECUTION,
        SOURCE_GRADE,
        SOURCE_IC_UPDATER,
        SOURCE_NOTIFICATION,
        SOURCE_REASONING,
        SOURCE_REFLECTION,
        SOURCE_SIGNAL,
        SOURCE_STRATEGY_PROPOSER,
    )

    sources = [
        SOURCE_SIGNAL,
        SOURCE_REASONING,
        SOURCE_EXECUTION,
        SOURCE_GRADE,
        SOURCE_IC_UPDATER,
        SOURCE_REFLECTION,
        SOURCE_STRATEGY_PROPOSER,
        SOURCE_NOTIFICATION,
    ]
    for src in sources:
        assert src == src.lower(), f"SOURCE constant {src!r} must be lowercase"


def test_source_constant_values() -> None:
    from api.constants import (
        SOURCE_EXECUTION,
        SOURCE_GRADE,
        SOURCE_IC_UPDATER,
        SOURCE_NOTIFICATION,
        SOURCE_REASONING,
        SOURCE_REFLECTION,
        SOURCE_SIGNAL,
        SOURCE_STRATEGY_PROPOSER,
    )

    assert SOURCE_SIGNAL == "signal_generator"
    assert SOURCE_REASONING == "reasoning_agent"
    assert SOURCE_EXECUTION == "execution_engine"
    assert SOURCE_GRADE == "grade_agent"
    assert SOURCE_IC_UPDATER == "ic_updater"
    assert SOURCE_REFLECTION == "reflection_agent"
    assert SOURCE_STRATEGY_PROPOSER == "strategy_proposer"
    assert SOURCE_NOTIFICATION == "notification_agent"


def test_source_constants_all_unique() -> None:
    from api.constants import (
        SOURCE_EXECUTION,
        SOURCE_GRADE,
        SOURCE_IC_UPDATER,
        SOURCE_NOTIFICATION,
        SOURCE_REASONING,
        SOURCE_REFLECTION,
        SOURCE_SIGNAL,
        SOURCE_STRATEGY_PROPOSER,
    )

    sources = [
        SOURCE_SIGNAL,
        SOURCE_REASONING,
        SOURCE_EXECUTION,
        SOURCE_GRADE,
        SOURCE_IC_UPDATER,
        SOURCE_REFLECTION,
        SOURCE_STRATEGY_PROPOSER,
        SOURCE_NOTIFICATION,
    ]
    assert len(sources) == len(set(sources)), "All SOURCE_* constants must be unique"


# ---------------------------------------------------------------------------
# STREAM_* constants
# ---------------------------------------------------------------------------


def test_stream_constants_values() -> None:
    from api.constants import (
        STREAM_AGENT_GRADES,
        STREAM_AGENT_LOGS,
        STREAM_DECISIONS,
        STREAM_EXECUTIONS,
        STREAM_FACTOR_IC_HISTORY,
        STREAM_GITHUB_PRS,
        STREAM_GRADED_DECISIONS,
        STREAM_LEARNING_EVENTS,
        STREAM_MARKET_EVENTS,
        STREAM_MARKET_TICKS,
        STREAM_NOTIFICATIONS,
        STREAM_ORDERS,
        STREAM_PROPOSALS,
        STREAM_REFLECTION_OUTPUTS,
        STREAM_RISK_ALERTS,
        STREAM_SIGNALS,
        STREAM_SYSTEM_METRICS,
        STREAM_TRADE_LIFECYCLE,
        STREAM_TRADE_PERFORMANCE,
    )

    assert STREAM_MARKET_TICKS == "market_ticks"
    assert STREAM_MARKET_EVENTS == "market_events"
    assert STREAM_SIGNALS == "signals"
    assert STREAM_DECISIONS == "decisions"
    assert STREAM_GRADED_DECISIONS == "graded_decisions"
    assert STREAM_ORDERS == "orders"
    assert STREAM_EXECUTIONS == "executions"
    assert STREAM_TRADE_PERFORMANCE == "trade_performance"
    assert STREAM_RISK_ALERTS == "risk_alerts"
    assert STREAM_LEARNING_EVENTS == "learning_events"
    assert STREAM_SYSTEM_METRICS == "system_metrics"
    assert STREAM_AGENT_LOGS == "agent_logs"
    assert STREAM_AGENT_GRADES == "agent_grades"
    assert STREAM_FACTOR_IC_HISTORY == "factor_ic_history"
    assert STREAM_REFLECTION_OUTPUTS == "reflection_outputs"
    assert STREAM_PROPOSALS == "proposals"
    assert STREAM_NOTIFICATIONS == "notifications"
    assert STREAM_GITHUB_PRS == "github_prs"
    assert STREAM_TRADE_LIFECYCLE == "trade_lifecycle"


def test_stream_constants_are_unique() -> None:
    from api.constants import (
        STREAM_AGENT_GRADES,
        STREAM_AGENT_LOGS,
        STREAM_DECISIONS,
        STREAM_EXECUTIONS,
        STREAM_FACTOR_IC_HISTORY,
        STREAM_GITHUB_PRS,
        STREAM_GRADED_DECISIONS,
        STREAM_LEARNING_EVENTS,
        STREAM_MARKET_EVENTS,
        STREAM_MARKET_TICKS,
        STREAM_NOTIFICATIONS,
        STREAM_ORDERS,
        STREAM_PROPOSALS,
        STREAM_REFLECTION_OUTPUTS,
        STREAM_RISK_ALERTS,
        STREAM_SIGNALS,
        STREAM_SYSTEM_METRICS,
        STREAM_TRADE_LIFECYCLE,
        STREAM_TRADE_PERFORMANCE,
    )

    streams = [
        STREAM_MARKET_TICKS,
        STREAM_MARKET_EVENTS,
        STREAM_SIGNALS,
        STREAM_DECISIONS,
        STREAM_GRADED_DECISIONS,
        STREAM_ORDERS,
        STREAM_EXECUTIONS,
        STREAM_TRADE_PERFORMANCE,
        STREAM_RISK_ALERTS,
        STREAM_LEARNING_EVENTS,
        STREAM_SYSTEM_METRICS,
        STREAM_AGENT_LOGS,
        STREAM_AGENT_GRADES,
        STREAM_FACTOR_IC_HISTORY,
        STREAM_REFLECTION_OUTPUTS,
        STREAM_PROPOSALS,
        STREAM_NOTIFICATIONS,
        STREAM_GITHUB_PRS,
        STREAM_TRADE_LIFECYCLE,
    ]
    assert len(streams) == len(set(streams)), "All STREAM_* constants must have unique values"


def test_bus_streams_matches_constants() -> None:
    """bus.STREAMS must contain every STREAM_* constant defined in constants.py."""
    from api.constants import (
        STREAM_AGENT_GRADES,
        STREAM_AGENT_LOGS,
        STREAM_DECISIONS,
        STREAM_EXECUTIONS,
        STREAM_FACTOR_IC_HISTORY,
        STREAM_GITHUB_PRS,
        STREAM_GRADED_DECISIONS,
        STREAM_LEARNING_EVENTS,
        STREAM_MARKET_EVENTS,
        STREAM_MARKET_TICKS,
        STREAM_NOTIFICATIONS,
        STREAM_ORDERS,
        STREAM_PROPOSALS,
        STREAM_REFLECTION_OUTPUTS,
        STREAM_RISK_ALERTS,
        STREAM_SIGNALS,
        STREAM_SYSTEM_METRICS,
        STREAM_TRADE_PERFORMANCE,
    )
    from api.events.bus import STREAMS

    expected = {
        STREAM_MARKET_TICKS,
        STREAM_MARKET_EVENTS,
        STREAM_SIGNALS,
        STREAM_DECISIONS,
        STREAM_GRADED_DECISIONS,
        STREAM_ORDERS,
        STREAM_EXECUTIONS,
        STREAM_TRADE_PERFORMANCE,
        STREAM_RISK_ALERTS,
        STREAM_LEARNING_EVENTS,
        STREAM_SYSTEM_METRICS,
        STREAM_AGENT_LOGS,
        STREAM_AGENT_GRADES,
        STREAM_FACTOR_IC_HISTORY,
        STREAM_REFLECTION_OUTPUTS,
        STREAM_PROPOSALS,
        STREAM_NOTIFICATIONS,
        STREAM_GITHUB_PRS,
    }
    missing = expected - set(STREAMS)
    assert not missing, f"bus.STREAMS is missing: {missing}"


# ---------------------------------------------------------------------------
# PIPELINE_STREAMS
# ---------------------------------------------------------------------------


def test_pipeline_streams_content() -> None:
    from api.constants import (
        PIPELINE_STREAMS,
        STREAM_DECISIONS,
        STREAM_GRADED_DECISIONS,
        STREAM_MARKET_EVENTS,
        STREAM_SIGNALS,
    )

    assert set(PIPELINE_STREAMS) == {
        STREAM_MARKET_EVENTS,
        STREAM_SIGNALS,
        STREAM_DECISIONS,
        STREAM_GRADED_DECISIONS,
    }


def test_pipeline_streams_is_tuple() -> None:
    from api.constants import PIPELINE_STREAMS

    assert isinstance(PIPELINE_STREAMS, tuple)


def test_ws_and_broadcaster_use_same_pipeline_streams() -> None:
    """Both ws.py and websocket_broadcaster.py must alias the same PIPELINE_STREAMS."""
    from api.constants import PIPELINE_STREAMS
    from api.routes.ws import _PIPELINE_STREAMS as ws_streams  # noqa: N811
    from api.services.websocket_broadcaster import (
        _PIPELINE_STREAMS as broadcaster_streams,  # noqa: N811
    )

    assert set(ws_streams) == set(PIPELINE_STREAMS)
    assert set(broadcaster_streams) == set(PIPELINE_STREAMS)


# ---------------------------------------------------------------------------
# Redis key constants
# ---------------------------------------------------------------------------


def test_redis_key_paper_order_format() -> None:
    from api.constants import REDIS_KEY_PAPER_ORDER

    key = REDIS_KEY_PAPER_ORDER.format(broker_order_id="abc-123")
    assert key == "paper:order:abc-123"


def test_redis_key_paper_cash_value() -> None:
    from api.constants import REDIS_KEY_PAPER_CASH

    assert REDIS_KEY_PAPER_CASH == "paper:cash"


def test_redis_key_paper_position_format() -> None:
    from api.constants import REDIS_KEY_PAPER_POSITION

    key = REDIS_KEY_PAPER_POSITION.format(symbol="BTC/USD")
    assert key == "paper:positions:BTC/USD"


# ---------------------------------------------------------------------------
# AGENT_CHALLENGER
# ---------------------------------------------------------------------------


def test_agent_challenger_value() -> None:
    from api.constants import AGENT_CHALLENGER

    assert AGENT_CHALLENGER == "CHALLENGER_AGENT"


def test_challenger_agent_uses_constant() -> None:
    from api.constants import AGENT_CHALLENGER
    from api.services.agents.pipeline_agents import ChallengerAgent

    assert ChallengerAgent._state_name == AGENT_CHALLENGER


# ---------------------------------------------------------------------------
# Grade enum
# ---------------------------------------------------------------------------


def test_grade_enum_values() -> None:
    from api.constants import Grade

    assert Grade.A == "A"
    assert Grade.B == "B"
    assert Grade.C == "C"
    assert Grade.D == "D"
    assert Grade.F == "F"


def test_grade_enum_is_str() -> None:
    from api.constants import Grade

    for member in Grade:
        assert isinstance(member, str)


def test_grade_comparison_with_string() -> None:
    """Grade enum must compare equal to its string value (StrEnum behaviour)."""
    from api.constants import Grade

    assert Grade.C == "C"
    assert Grade.D == "D"
    assert Grade.F == "F"
    assert "B" == Grade.B


# ---------------------------------------------------------------------------
# HypothesisType enum
# ---------------------------------------------------------------------------


def test_hypothesis_type_values() -> None:
    from api.constants import HypothesisType

    assert HypothesisType.PARAMETER == "parameter"
    assert HypothesisType.RULE == "rule"
    assert HypothesisType.NEW_AGENT == "new_agent"


# ---------------------------------------------------------------------------
# ProposalType enum (extended)
# ---------------------------------------------------------------------------


def test_proposal_type_new_agent() -> None:
    from api.constants import ProposalType

    assert ProposalType.NEW_AGENT == "new_agent"


def test_proposal_type_all_values_unique() -> None:
    from api.constants import ProposalType

    values = [m.value for m in ProposalType]
    assert len(values) == len(set(values)), "ProposalType has duplicate values"


# ---------------------------------------------------------------------------
# LLM fallback mode constants
# ---------------------------------------------------------------------------


def test_llm_fallback_mode_constants() -> None:
    from api.constants import (
        LLM_FALLBACK_MODE,
        LLM_FALLBACK_MODE_REJECT_SIGNAL,
        LLM_FALLBACK_MODE_SKIP_REASONING,
        LLM_FALLBACK_MODE_USE_LAST_REFLECTION,
    )

    assert LLM_FALLBACK_MODE_SKIP_REASONING == "skip_reasoning"
    assert LLM_FALLBACK_MODE_REJECT_SIGNAL == "reject_signal"
    assert LLM_FALLBACK_MODE_USE_LAST_REFLECTION == "use_last_reflection"
    # Default must be one of the defined modes
    assert LLM_FALLBACK_MODE in {
        LLM_FALLBACK_MODE_SKIP_REASONING,
        LLM_FALLBACK_MODE_REJECT_SIGNAL,
        LLM_FALLBACK_MODE_USE_LAST_REFLECTION,
    }


# ---------------------------------------------------------------------------
# Paper broker backward-compat class attributes
# ---------------------------------------------------------------------------


def test_paper_broker_class_attrs_match_constants() -> None:
    """PaperBroker class attributes must equal their module-level constants."""
    from api.constants import DEFAULT_PAPER_CASH, REDIS_KEY_PAPER_CASH
    from api.services.execution.brokers.paper import PaperBroker

    assert PaperBroker.CASH_KEY == REDIS_KEY_PAPER_CASH
    assert PaperBroker.DEFAULT_CASH == DEFAULT_PAPER_CASH


# ---------------------------------------------------------------------------
# Severity enum comparisons
# ---------------------------------------------------------------------------


def test_severity_enum_is_str() -> None:
    from api.constants import Severity

    for member in Severity:
        assert isinstance(member, str)
        assert member == member.upper()


def test_severity_values() -> None:
    from api.constants import Severity

    assert Severity.INFO == "INFO"
    assert Severity.WARNING == "WARNING"
    assert Severity.URGENT == "URGENT"
    assert Severity.CRITICAL == "CRITICAL"


# ---------------------------------------------------------------------------
# Broadcaster stream offsets use constants
# ---------------------------------------------------------------------------


def test_broadcaster_stream_offsets_use_constants() -> None:
    """WebSocketBroadcaster._stream_offsets keys must equal STREAM_* constants.

    STREAM_ORDERS is intentionally absent: advisory decisions go to STREAM_DECISIONS
    (internal), and only actual fills on STREAM_EXECUTIONS reach the UI.
    """
    from api.constants import (
        STREAM_AGENT_LOGS,
        STREAM_EXECUTIONS,
        STREAM_LEARNING_EVENTS,
        STREAM_RISK_ALERTS,
        STREAM_SIGNALS,
    )
    from api.services.websocket_broadcaster import WebSocketBroadcaster

    broadcaster = WebSocketBroadcaster()
    keys = set(broadcaster._stream_offsets.keys())
    expected = {
        STREAM_SIGNALS,
        STREAM_EXECUTIONS,
        STREAM_RISK_ALERTS,
        STREAM_LEARNING_EVENTS,
        STREAM_AGENT_LOGS,
    }
    assert keys == expected


# ---------------------------------------------------------------------------
# Reasoning agent uses constants for LLM fallback mode comparisons
# ---------------------------------------------------------------------------


def test_reasoning_agent_fallback_uses_constants() -> None:
    """Verify reasoning_agent.py imports and uses LLM_FALLBACK_MODE_* constants."""
    import inspect

    import api.services.agents.reasoning_agent as mod

    src = inspect.getsource(mod)
    # Must NOT contain bare string comparisons for fallback modes
    assert '"reject_signal"' not in src, (
        "reasoning_agent.py must use LLM_FALLBACK_MODE_REJECT_SIGNAL constant"
    )
    assert '"use_last_reflection"' not in src, (
        "reasoning_agent.py must use LLM_FALLBACK_MODE_USE_LAST_REFLECTION constant"
    )


# ---------------------------------------------------------------------------
# signal_generator.py uses STREAM_* constants
# ---------------------------------------------------------------------------


def test_signal_generator_uses_stream_constants() -> None:
    import inspect

    import api.services.signal_generator as mod

    src = inspect.getsource(mod)
    assert 'stream="market_events"' not in src
    assert 'stream="signals"' not in src
    assert '"signals"' not in src or "STREAM_SIGNALS" in src


# ---------------------------------------------------------------------------
# execution_engine.py uses STREAM_ORDERS constant
# ---------------------------------------------------------------------------


def test_execution_engine_uses_stream_orders_constant() -> None:
    import inspect

    import api.services.execution.execution_engine as mod

    src = inspect.getsource(mod)
    assert 'stream="orders"' not in src, (
        "execution_engine.py must use STREAM_ORDERS constant, not bare 'orders' string"
    )
