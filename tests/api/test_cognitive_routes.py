"""Tests for the read-only cognitive observability API."""

from __future__ import annotations

from api.routes import cognitive as route

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
    # Default is now the LIVE snapshot — it must expose every tab the UI renders
    # (empty in a fresh store, but every key present so the page never crashes).
    snapshot = await route.cognitive_state()
    for tab in TABS:
        assert tab in snapshot
    assert isinstance(snapshot["event_count"], int)
    assert len(snapshot["agents_roster"]) > 0
    # Live snapshot is fully keyed for the frontend's deep accesses.
    assert isinstance(snapshot["evolution"]["agent_grades"], list)
    assert isinstance(snapshot["drift"]["alerts"], list)
    assert set(snapshot["live_agents"]) == {"news", "tech", "macro", "risk"}


async def test_demo_state_still_seeded():
    snapshot = await route.cognitive_state(demo=True)
    for tab in TABS:
        assert tab in snapshot
    assert snapshot["event_count"] > 0


async def test_events_endpoint_respects_limit():
    events = await route.cognitive_events(limit=10)
    assert len(events) <= 10
    assert all("type" in event and "seq" in event for event in events)


async def test_config_endpoint_returns_versioned_config():
    config = await route.cognitive_config()
    assert set(config["weights"]) == {"news", "tech", "macro"}
    assert "version" in config


async def test_agents_endpoint_lists_full_roster():
    agents = await route.cognitive_agents()
    names = {agent["name"] for agent in agents}
    assert {"news_agent", "technical_agent", "macro_agent", "risk_agent", "proposal_agent"} <= names


async def test_trace_endpoint_reconstructs_a_full_chain():
    # Trace reconstruction reads the seeded demo stream, so drive it via demo mode.
    snapshot = await route.cognitive_state(demo=True)
    trace_id = snapshot["traces"][0]["trace_id"]
    trace = await route.cognitive_trace(trace_id)
    assert trace["trace_id"] == trace_id
    assert trace["decision"] is not None
    assert trace["execution"] is not None


async def test_reseed_rebuilds_and_returns_snapshot():
    snapshot = await route.cognitive_reseed()
    assert snapshot["event_count"] > 0
    assert "evolution" in snapshot
