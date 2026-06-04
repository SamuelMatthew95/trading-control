"""Tests for the live cognitive snapshot adapter (real agent data, not demo)."""

from __future__ import annotations

from api.in_memory_store import InMemoryStore
from api.runtime_state import set_runtime_store
from api.services.cognitive_live import build_live_events, build_live_snapshot


async def test_live_snapshot_is_fully_keyed_when_empty():
    set_runtime_store(InMemoryStore())
    snap = await build_live_snapshot()
    # Every path the frontend deep-accesses must exist so the page never crashes.
    assert isinstance(snap["agents_roster"], list) and snap["agents_roster"]
    assert isinstance(snap["evolution"]["agent_grades"], list)
    assert isinstance(snap["evolution"]["config_versions"], list)
    assert isinstance(snap["evolution"]["proposal_success_rates"], dict)
    assert isinstance(snap["proposals"], list)
    assert isinstance(snap["drift"]["alerts"], list)
    assert isinstance(snap["traces"], list)
    assert set(snap["live_agents"]) == {"news", "tech", "macro", "risk"}
    assert snap["event_count"] == 0


async def test_live_snapshot_reflects_real_grades_and_events():
    store = InMemoryStore()
    set_runtime_store(store)
    store.add_grade({"subject": "REASONING_AGENT", "grade": "B", "score": 0.8})
    store.add_grade({"subject": "REASONING_AGENT", "grade": "A", "score": 0.9})
    store.add_event({"type": "decision", "action": "buy"})

    snap = await build_live_snapshot()
    grades = {g["subject_id"]: g for g in snap["learning"]["agent_grades"]}
    assert "REASONING_AGENT" in grades
    assert grades["REASONING_AGENT"]["samples"] == 2
    # average of 0.8 and 0.9
    assert abs(grades["REASONING_AGENT"]["score"] - 0.85) < 1e-9
    assert snap["event_count"] == 1


async def test_live_events_shape():
    store = InMemoryStore()
    set_runtime_store(store)
    store.add_event({"type": "grade", "score": 0.5})
    events = await build_live_events(10)
    assert len(events) == 1
    assert events[0]["type"] == "grade"
    assert "seq" in events[0] and "payload" in events[0]
