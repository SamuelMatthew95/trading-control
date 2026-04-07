"""Verify that agent name constants are consistent across the codebase.

These tests catch the class of bug where an agent writes its heartbeat to
Redis under one name (e.g. SIGNAL_AGENT) but the dashboard reads a different
name (e.g. SignalGenerator), causing agent statuses to always show "offline".
"""

from api.constants import (
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_NOTIFICATION,
    AGENT_REASONING,
    AGENT_REFLECTION,
    AGENT_SIGNAL,
    AGENT_STRATEGY_PROPOSER,
    ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
)


def test_all_agent_names_contains_every_constant() -> None:
    """ALL_AGENT_NAMES must list every individual agent constant."""
    expected = {
        AGENT_SIGNAL,
        AGENT_REASONING,
        AGENT_EXECUTION,
        AGENT_GRADE,
        AGENT_IC_UPDATER,
        AGENT_REFLECTION,
        AGENT_STRATEGY_PROPOSER,
        AGENT_NOTIFICATION,
    }
    assert set(ALL_AGENT_NAMES) == expected, (
        f"ALL_AGENT_NAMES is missing agents: {expected - set(ALL_AGENT_NAMES)}"
    )


def test_all_agent_names_no_duplicates() -> None:
    assert len(ALL_AGENT_NAMES) == len(set(ALL_AGENT_NAMES))


def test_redis_key_pattern_formats_correctly() -> None:
    key = REDIS_AGENT_STATUS_KEY.format(name=AGENT_SIGNAL)
    assert key == "agent:status:SIGNAL_AGENT"


def test_signal_generator_uses_constant() -> None:
    """signal_generator.py must derive AGENT_NAME from the constant."""
    from api.services.signal_generator import AGENT_NAME

    assert AGENT_NAME == AGENT_SIGNAL, (
        f"signal_generator.AGENT_NAME={AGENT_NAME!r} must equal AGENT_SIGNAL={AGENT_SIGNAL!r}"
    )


def test_execution_engine_uses_constant() -> None:
    from api.services.execution.execution_engine import _STATE_NAME

    assert _STATE_NAME == AGENT_EXECUTION


def test_pipeline_agents_use_constants() -> None:
    from api.services.agents.pipeline_agents import (
        GradeAgent,
        ICUpdater,
        NotificationAgent,
        ReflectionAgent,
        StrategyProposer,
    )

    assert GradeAgent._state_name == AGENT_GRADE
    assert ICUpdater._state_name == AGENT_IC_UPDATER
    assert ReflectionAgent._state_name == AGENT_REFLECTION
    assert StrategyProposer._state_name == AGENT_STRATEGY_PROPOSER
    assert NotificationAgent._state_name == AGENT_NOTIFICATION


def test_websocket_broadcaster_uses_all_agent_names() -> None:
    from api.services.websocket_broadcaster import _AGENT_NAMES

    assert set(_AGENT_NAMES) == set(ALL_AGENT_NAMES)


def test_agent_state_uses_all_agent_names() -> None:
    from api.services.agent_state import AGENT_NAMES

    assert set(AGENT_NAMES) == set(ALL_AGENT_NAMES)


def test_dashboard_state_reads_correct_redis_keys() -> None:
    """The keys the dashboard builds must match what agents write."""
    dashboard_keys = {REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES}
    agent_keys = {f"agent:status:{n}" for n in ALL_AGENT_NAMES}
    assert dashboard_keys == agent_keys
