"""Tests for the read-only cognitive observability API (live agents only)."""

from __future__ import annotations

import fakeredis

from api.constants import AGENT_REASONING, AGENT_SIGNAL, FieldName
from api.in_memory_store import InMemoryStore
from api.routes import cognitive as route
from api.runtime_state import set_runtime_store
from api.services.redis_store import RedisStore, set_redis_store

TABS = (
    "live_agents",
    "reasoning",
    "decision",
    "proposals",
    "challenger",
    "learning",
    "evolution",
    "health",
    "traces",
    "agents_roster",
    "config",
)


async def test_state_exposes_all_observability_tabs():
    # The default (and only) snapshot is LIVE — it must expose every tab the UI
    # renders (empty in a fresh store, but every key present so it never crashes).
    snapshot = await route.cognitive_state()
    for tab in TABS:
        assert tab in snapshot
    assert isinstance(snapshot["event_count"], int)
    assert len(snapshot["agents_roster"]) > 0
    assert isinstance(snapshot["evolution"]["agent_grades"], list)
    assert isinstance(snapshot["drift"]["alerts"], list)
    assert isinstance(snapshot["live_agents"], dict)
    # Memory mode reported honestly (no DB bound in tests).
    assert snapshot["db_available"] is False


async def test_events_endpoint_respects_limit():
    events = await route.cognitive_events(limit=10)
    assert len(events) <= 10
    assert all("type" in event and "seq" in event for event in events)


async def test_config_endpoint_returns_live_versioned_config():
    config = await route.cognitive_config()
    assert "version" in config and isinstance(config["version"], int)
    # Live weights are the IC weights (empty dict when none computed yet) —
    # never the seeded news/tech/macro demo weights.
    assert isinstance(config["weights"], dict)


async def test_agents_endpoint_lists_live_roster():
    agents = await route.cognitive_agents()
    names = {agent["name"] for agent in agents}
    # Real agent-name constants, not the demo's news_agent/technical_agent/...
    assert {AGENT_SIGNAL, AGENT_REASONING} <= names
    assert all({"name", "role", "emits", "description"} <= set(a) for a in agents)


async def test_trace_endpoint_reconstructs_live_chain_by_id():
    set_runtime_store(InMemoryStore())
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    rs = RedisStore(redis)
    set_redis_store(rs)
    try:
        await rs.push_decision(
            {
                FieldName.TRACE_ID: "trace-xyz",
                FieldName.ACTION: "buy",
                FieldName.SYMBOL: "BTC/USD",
                FieldName.CONFIDENCE: 0.8,
                FieldName.REASONING_SUMMARY: "momentum edge",
            }
        )
        trace = await route.cognitive_trace("trace-xyz")
        assert trace["trace_id"] == "trace-xyz"
        assert trace["decision"] is not None
        assert trace["decision"]["action"] == "buy"
    finally:
        set_redis_store(None)
        await redis.aclose()


async def test_trace_endpoint_unknown_id_returns_keyed_empty():
    set_runtime_store(InMemoryStore())
    set_redis_store(None)
    trace = await route.cognitive_trace("does-not-exist")
    assert trace["trace_id"] == "does-not-exist"
    assert trace["decision"] is None
