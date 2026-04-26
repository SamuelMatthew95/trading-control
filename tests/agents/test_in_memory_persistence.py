"""Tests for in-memory persistence paths across all agents and db_helpers.

Covers the memory-mode code paths that were previously untested:
  - db_helpers functions with is_db_available() == False
  - signal_generator._begin_run() and _persist_signal_complete() memory paths
  - reasoning_agent._persist_run() and _persist_vector() memory paths
  - InMemoryStore.DEFAULT_AGENTS keys matching constants
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import (
    AGENT_CHALLENGER,
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_NOTIFICATION,
    AGENT_REASONING,
    AGENT_REFLECTION,
    AGENT_SIGNAL,
    AGENT_STRATEGY_PROPOSER,
    ALL_AGENT_NAMES,
    LogType,
)
from api.in_memory_store import DEFAULT_AGENTS, InMemoryStore
from api.runtime_state import set_db_available, set_runtime_store

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_store() -> InMemoryStore:
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)
    return store


# ---------------------------------------------------------------------------
# InMemoryStore.DEFAULT_AGENTS — key consistency
# ---------------------------------------------------------------------------


def test_default_agents_keys_match_all_agent_names():
    """DEFAULT_AGENTS must use the same names as ALL_AGENT_NAMES so heartbeats don't create ghost keys."""
    assert set(DEFAULT_AGENTS.keys()) == set(ALL_AGENT_NAMES), (
        f"DEFAULT_AGENTS keys {set(DEFAULT_AGENTS.keys())} != ALL_AGENT_NAMES {set(ALL_AGENT_NAMES)}"
    )


def test_default_agents_uses_screaming_snake_case():
    """All DEFAULT_AGENTS keys must be SCREAMING_SNAKE_CASE constants, not lowercase."""
    for key in DEFAULT_AGENTS:
        assert key == key.upper() or "_" in key, (
            f"DEFAULT_AGENTS key {key!r} looks like a lowercase name; use the constant from constants.py"
        )


def test_default_agents_includes_all_seven_agents():
    expected = {
        AGENT_SIGNAL,
        AGENT_REASONING,
        AGENT_EXECUTION,
        AGENT_GRADE,
        AGENT_IC_UPDATER,
        AGENT_REFLECTION,
        AGENT_STRATEGY_PROPOSER,
        AGENT_NOTIFICATION,
        AGENT_CHALLENGER,
    }
    assert set(DEFAULT_AGENTS.keys()) == expected


def test_in_memory_store_upsert_updates_correct_key():
    """write_heartbeat calls upsert_agent(AGENT_SIGNAL, ...) — key must match DEFAULT_AGENTS entry."""
    store = InMemoryStore()
    store.upsert_agent(AGENT_SIGNAL, {"status": "ACTIVE", "last_seen": 1000})
    # Should update the existing AGENT_SIGNAL key, not create a ghost "signal_generator" key
    assert store.agents[AGENT_SIGNAL]["status"] == "ACTIVE"
    assert "signal_generator" not in store.agents


def test_dashboard_fallback_snapshot_agent_statuses_use_correct_names():
    """Agent statuses in the fallback snapshot must carry SCREAMING_SNAKE_CASE names."""
    store = InMemoryStore()
    store.upsert_agent(AGENT_SIGNAL, {"status": "ACTIVE", "last_seen": 9999})
    snapshot = store.dashboard_fallback_snapshot()
    names = {a["name"] for a in snapshot["agent_statuses"]}
    assert AGENT_SIGNAL in names
    assert "signal_generator" not in names


def test_dashboard_fallback_snapshot_agent_statuses_keep_heartbeat_fields():
    """In-memory snapshot should preserve heartbeat details so dashboard rows show meaningful values."""
    store = InMemoryStore()
    store.upsert_agent(
        AGENT_SIGNAL,
        {
            "status": "ACTIVE",
            "last_seen": 1_700_000_000,
            "last_seen_at": "2026-01-02T03:04:05Z",
            "last_event": "processed_signal",
            "event_count": 42,
        },
    )

    snapshot = store.dashboard_fallback_snapshot()
    row = next(agent for agent in snapshot["agent_statuses"] if agent["name"] == AGENT_SIGNAL)

    assert row["status"] == "ACTIVE"
    assert row["last_seen"] == 1_700_000_000
    assert row["last_seen_at"] == "2026-01-02T03:04:05Z"
    assert row["last_event"] == "processed_signal"
    assert row["event_count"] == 42
    assert row["source"] == "in_memory"


def test_dashboard_fallback_snapshot_surfaces_trade_feed_and_agent_logs():
    """The snapshot must include trade_feed + agent_logs so memory-mode dashboards
    don't render the Trade Feed / Agent Thought Stream as empty."""
    store = InMemoryStore()
    store.upsert_trade_fill(
        {
            "id": "tr-1",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 1.0,
            "entry_price": 190.0,
            "execution_trace_id": "tr-1",
            "status": "filled",
        }
    )
    store.add_agent_log(
        {
            "id": "log-1",
            "agent_name": "REASONING_AGENT",
            "message": "bullish call",
            "trace_id": "tr-1",
        }
    )
    store.add_grade({"trace_id": "tr-1", "grade": "A", "score": 90.0})
    store.add_event({"log_type": LogType.PROPOSAL, "trace_id": "tr-1", "payload": {}})

    snapshot = store.dashboard_fallback_snapshot()

    assert "trade_feed" in snapshot
    assert len(snapshot["trade_feed"]) == 1
    assert snapshot["trade_feed"][0]["symbol"] == "AAPL"

    assert "agent_logs" in snapshot
    assert len(snapshot["agent_logs"]) == 1
    assert snapshot["agent_logs"][0]["message"] == "bullish call"

    assert "learning_events" in snapshot
    assert len(snapshot["learning_events"]) == 1
    assert snapshot["learning_events"][0]["grade"] == "A"

    assert "proposals" in snapshot
    assert len(snapshot["proposals"]) == 1


def test_upsert_trade_fill_dedupes_on_execution_trace_id():
    """Second upsert with the same execution_trace_id merges non-None fields into the
    existing row; list length stays at 1."""
    store = InMemoryStore()
    store.upsert_trade_fill(
        {
            "id": "dup-1",
            "execution_trace_id": "dup-1",
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.1,
            "entry_price": 50000.0,
            "status": "filled",
        }
    )
    store.upsert_trade_fill(
        {
            "execution_trace_id": "dup-1",
            "grade": "B",
            "grade_score": 0.8,
            "status": "graded",
        }
    )

    assert len(store.trade_feed) == 1
    row = store.trade_feed[0]
    assert row["grade"] == "B"
    assert row["status"] == "graded"
    # Original fields preserved
    assert row["qty"] == pytest.approx(0.1)
    assert row["entry_price"] == pytest.approx(50000.0)


# ---------------------------------------------------------------------------
# db_helpers — memory-mode paths
# ---------------------------------------------------------------------------


async def test_write_agent_log_grade_type_goes_to_grade_history():
    """GRADE log_type must write to InMemoryStore.grade_history, not event_history."""
    store = _fresh_store()

    from api.services.agents.db_helpers import write_agent_log

    await write_agent_log(
        "trace-001",
        LogType.GRADE,
        {
            "grade": "B",
            "score": 0.72,
            "score_pct": 72.0,
            "metrics": {"accuracy": 0.7},
            "fills_graded": 5,
        },
    )

    assert len(store.grade_history) == 1
    assert store.grade_history[0]["trace_id"] == "trace-001"
    assert store.grade_history[0]["grade"] == "B"
    assert store.grade_history[0]["score"] == 0.72
    assert len(store.event_history) == 0  # must NOT write to event_history


async def test_write_agent_log_non_grade_goes_to_event_history():
    """Non-GRADE log types (REFLECTION, PROPOSAL, etc.) must write to event_history."""
    store = _fresh_store()

    from api.services.agents.db_helpers import write_agent_log

    await write_agent_log(
        "trace-002",
        LogType.REFLECTION,
        {"summary": "some reflection"},
        agent_run_id="run-1",
    )

    assert len(store.event_history) == 1
    assert store.event_history[0]["trace_id"] == "trace-002"
    assert store.event_history[0]["log_type"] == LogType.REFLECTION
    assert len(store.grade_history) == 0  # must NOT write to grade_history


async def test_write_grade_to_db_memory_mode():
    """write_grade_to_db in memory mode populates grade_history with correct fields."""
    store = _fresh_store()

    from api.services.agents.db_helpers import write_grade_to_db

    await write_grade_to_db("trace-003", 85.5, {"fills_graded": 3, "accuracy": 0.8})

    assert len(store.grade_history) == 1
    g = store.grade_history[0]
    assert g["trace_id"] == "trace-003"
    assert g["score"] == 85.5
    assert g["fills_graded"] == 3
    assert "timestamp" in g


async def test_persist_proposal_memory_mode():
    """persist_proposal in memory mode writes a PROPOSAL event to event_history."""
    store = _fresh_store()

    from api.services.agents.db_helpers import persist_proposal

    await persist_proposal(
        {
            "reflection_trace_id": "trace-004",
            "proposal_type": "strategy_change",
            "content": {"action": "reduce_weight"},
        }
    )

    assert len(store.event_history) == 1
    ev = store.event_history[0]
    assert ev["log_type"] == LogType.PROPOSAL
    assert ev["trace_id"] == "trace-004"
    assert ev["payload"]["proposal_type"] == "strategy_change"


async def test_get_last_reflection_memory_mode_returns_empty():
    """get_last_reflection must return {} in memory mode — no DB, no history."""
    _fresh_store()

    from api.services.agents.db_helpers import get_last_reflection

    result = await get_last_reflection()
    assert result == {}


async def test_register_agent_instance_memory_mode_returns_uuid():
    """register_agent_instance returns a UUID string without touching the DB."""
    _fresh_store()

    from api.services.agents.db_helpers import register_agent_instance

    instance_id = await register_agent_instance("signal-consumer", "SIGNAL_AGENT")
    # Must be a non-empty string that looks like a UUID
    assert isinstance(instance_id, str)
    assert len(instance_id) == 36  # UUID4 canonical form
    assert instance_id.count("-") == 4


async def test_register_agent_instance_retries_transient_db_error(monkeypatch):
    """Regression: a single transient DB failure must not leave the agent
    running with an unpersisted instance_id. register_agent_instance retries
    up to 3 times; a flake on attempts 1-2 should still land the row.
    """
    from api.services.agents import db_helpers

    set_db_available(True)
    monkeypatch.setattr("api.services.agents.db_helpers.is_db_available", lambda: True)
    # Speed up the backoff in the test
    monkeypatch.setattr(db_helpers, "_REGISTER_BACKOFF_BASE_S", 0.0)

    attempts = {"count": 0}

    class _FlakySession:
        async def execute(self, *args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("transient db error")
            return MagicMock()

        async def commit(self):
            return None

    class _FlakyFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _FlakySession()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(db_helpers, "AsyncSessionFactory", _FlakyFactory())

    instance_id = await db_helpers.register_agent_instance("flaky", "TEST_POOL")

    assert attempts["count"] == 3, "must have retried twice before succeeding"
    assert len(instance_id) == 36 and instance_id.count("-") == 4


async def test_register_agent_instance_gives_up_after_max_attempts(monkeypatch):
    """If every retry fails, register_agent_instance still returns a UUID
    (agent keeps running) but must log at ERROR level so ops can see that
    lifecycle registration is broken and heartbeats will be orphaned.
    """
    from api.services.agents import db_helpers

    set_db_available(True)
    monkeypatch.setattr("api.services.agents.db_helpers.is_db_available", lambda: True)
    monkeypatch.setattr(db_helpers, "_REGISTER_BACKOFF_BASE_S", 0.0)

    attempts = {"count": 0}

    class _BrokenSession:
        async def execute(self, *args, **kwargs):
            attempts["count"] += 1
            raise RuntimeError("db down")

        async def commit(self):
            return None

    class _BrokenFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _BrokenSession()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(db_helpers, "AsyncSessionFactory", _BrokenFactory())

    error_logs: list[dict] = []

    def _capture(level, event, **kwargs):
        if level == "error":
            error_logs.append({"event": event, **kwargs})

    monkeypatch.setattr(db_helpers, "log_structured", _capture)

    instance_id = await db_helpers.register_agent_instance("doomed", "TEST_POOL")

    assert attempts["count"] == db_helpers._REGISTER_MAX_ATTEMPTS
    assert len(instance_id) == 36  # still returns a UUID so caller keeps running
    assert any(log["event"] == "agent_instance_register_failed" for log in error_logs), (
        "final failure must be logged at ERROR level (not warning)"
    )


# ---------------------------------------------------------------------------
# signal_generator — _begin_run() memory path
# ---------------------------------------------------------------------------


async def test_signal_generator_begin_run_memory_mode_adds_agent_run(monkeypatch):
    """_begin_run in memory mode: should_proceed=True, db_run_id=None, agent_run stored."""
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.signal_generator import SignalGenerator

    store = _fresh_store()
    bus = MagicMock(spec=EventBus)
    bus.redis = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    sg = SignalGenerator(bus, dlq)

    should_proceed, db_run_id = await sg._begin_run(
        run_id="run-abc",
        trace_id="trace-xyz",
        payload={"symbol": "BTC/USD", "price": 50000.0},
        agent_pool_id=None,
        msg_id="msg-001",
    )

    assert should_proceed is True
    assert db_run_id is None
    assert len(store.agent_runs) == 1
    run = store.agent_runs[0]
    assert run["run_id"] == "run-abc"
    assert run["trace_id"] == "trace-xyz"
    assert run["status"] == "running"
    assert run["source"] == "signal_generator"


async def test_signal_generator_begin_run_db_mode_skips_duplicate(monkeypatch):
    """_begin_run in DB mode: returns (False, None) when msg_id is a duplicate."""
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.signal_generator import SignalGenerator

    store = _fresh_store()
    set_db_available(True)

    bus = MagicMock(spec=EventBus)
    bus.redis = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    sg = SignalGenerator(bus, dlq)

    monkeypatch.setattr("api.services.signal_generator.is_db_available", lambda: True)

    # Patch _is_duplicate to say it IS a duplicate
    async def _fake_is_dup(msg_id):
        return True

    sg._is_duplicate = _fake_is_dup

    should_proceed, db_run_id = await sg._begin_run(
        run_id="run-dup",
        trace_id="trace-dup",
        payload={},
        agent_pool_id=None,
        msg_id="msg-dup",
    )

    assert should_proceed is False
    assert db_run_id is None
    # memory store must NOT have been written to
    assert len(store.agent_runs) == 0
    set_db_available(False)


# ---------------------------------------------------------------------------
# signal_generator — _persist_signal_complete() memory path
# ---------------------------------------------------------------------------


async def test_signal_generator_persist_signal_complete_memory_mode(monkeypatch):
    """_persist_signal_complete in memory mode writes event + grade + run update + log."""
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.signal_generator import SignalGenerator

    store = _fresh_store()
    # Pre-populate agent run so the run.update() logic can find it
    store.add_agent_run({"run_id": "run-mem", "status": "running", "trace_id": "trace-mem"})

    bus = MagicMock(spec=EventBus)
    bus.redis = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    sg = SignalGenerator(bus, dlq)

    signal_payload = {
        "type": "STRONG_MOMENTUM",
        "symbol": "ETH/USD",
        "price": 3000.0,
        "pct": 4.0,
        "direction": "bullish",
        "strength": "HIGH",
        "trace_id": "trace-mem",
        "ts": 1000,
        "source": "SIGNAL_AGENT",
        "msg_id": "msg-mem",
    }

    await sg._persist_signal_complete(
        run_id="run-mem",
        db_run_id=None,
        trace_id="trace-mem",
        signal_payload=signal_payload,
        agent_pool_id=None,
        msg_id="msg-mem",
        score=80.0,
        elapsed_ms=42,
    )

    # 1. signal event written
    signal_events = [e for e in store.event_history if e.get("event_type") == "signal.generated"]
    assert len(signal_events) == 1
    assert signal_events[0]["entity_id"] == "trace-mem"

    # 2. grade written
    assert len(store.grade_history) == 1
    assert store.grade_history[0]["score"] == 80.0
    assert store.grade_history[0]["trace_id"] == "trace-mem"

    # 3. run updated to completed
    run = next(r for r in store.agent_runs if r["run_id"] == "run-mem")
    assert run["status"] == "completed"
    assert run["execution_time_ms"] == 42

    # 4. agent log event written
    log_events = [e for e in store.event_history if e.get("log_type") == "SIGNAL_GENERATED"]
    assert len(log_events) == 1
    assert log_events[0]["trace_id"] == "trace-mem"


# ---------------------------------------------------------------------------
# reasoning_agent — _persist_run() memory path
# ---------------------------------------------------------------------------


async def test_reasoning_agent_persist_run_memory_mode():
    """_persist_run in memory mode: returns run_id, writes to agent_runs store."""
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.agents.reasoning_agent import ReasoningAgent

    store = _fresh_store()
    bus = MagicMock(spec=EventBus)
    bus.redis = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    redis = AsyncMock()
    agent = ReasoningAgent(bus=bus, dlq=dlq, redis_client=redis)

    data = {"symbol": "BTC/USD", "price": 50000.0}
    summary = {
        "action": "buy",
        "confidence": 0.8,
        "primary_edge": "momentum",
        "risk_factors": [],
        "size_pct": 0.05,
        "stop_atr_x": 1.5,
        "rr_ratio": 2.0,
        "latency_ms": 100,
        "cost_usd": 0.001,
        "trace_id": "trace-reason",
    }

    run_id = await agent._persist_run(
        data, summary, "trace-reason", False, "2026-04-13", 100, 0.001
    )

    assert run_id.startswith("mem-")
    assert "trace-reason" in run_id
    assert len(store.agent_runs) == 1
    assert store.agent_runs[0]["action"] == "buy"
    assert store.agent_runs[0]["confidence"] == 0.8
    assert store.agent_runs[0]["fallback"] is False


# ---------------------------------------------------------------------------
# reasoning_agent — _persist_vector() memory path
# ---------------------------------------------------------------------------


async def test_reasoning_agent_persist_vector_memory_mode():
    """_persist_vector in memory mode: writes to vector_memory store."""
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.agents.reasoning_agent import ReasoningAgent

    store = _fresh_store()
    bus = MagicMock(spec=EventBus)
    bus.redis = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    redis = AsyncMock()
    agent = ReasoningAgent(bus=bus, dlq=dlq, redis_client=redis)

    embedding = [0.1] * 1536
    summary = {"action": "buy", "confidence": 0.8, "trace_id": "trace-vec"}

    await agent._persist_vector("signal summary text", embedding, summary)

    assert len(store.vector_memory) == 1
    vm = store.vector_memory[0]
    assert vm["content"] == "signal summary text"
    assert vm["embedding"] == embedding
    assert vm["metadata"]["trace_id"] == "trace-vec"
    assert vm["outcome"]["action"] == "buy"


# ---------------------------------------------------------------------------
# reasoning_agent — _build_signal_summary uses "type" field
# ---------------------------------------------------------------------------


def test_reasoning_agent_build_signal_summary_reads_type_field():
    """_build_signal_summary must read 'type' (not 'signal_type') from signal payload."""
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.agents.reasoning_agent import ReasoningAgent

    bus = MagicMock(spec=EventBus)
    dlq = MagicMock(spec=DLQManager)
    redis = AsyncMock()
    agent = ReasoningAgent(bus=bus, dlq=dlq, redis_client=redis)

    # Signal payload from SignalGenerator uses "type", not "signal_type"
    data = {
        "symbol": "BTC/USD",
        "price": 50000.0,
        "type": "STRONG_MOMENTUM",
        "composite_score": 0.85,
    }

    summary = agent._build_signal_summary(data)
    parsed = json.loads(summary)

    assert parsed["signal_type"] == "STRONG_MOMENTUM", (
        f"signal_type should be 'STRONG_MOMENTUM', got {parsed['signal_type']!r}"
    )


def test_reasoning_agent_build_signal_summary_prefers_signal_type_key():
    """If both 'signal_type' and 'type' are present, 'signal_type' takes precedence."""
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.agents.reasoning_agent import ReasoningAgent

    bus = MagicMock(spec=EventBus)
    dlq = MagicMock(spec=DLQManager)
    redis = AsyncMock()
    agent = ReasoningAgent(bus=bus, dlq=dlq, redis_client=redis)

    data = {"symbol": "ETH/USD", "price": 3000.0, "signal_type": "MOMENTUM", "type": "event"}
    parsed = json.loads(agent._build_signal_summary(data))
    assert parsed["signal_type"] == "MOMENTUM"
