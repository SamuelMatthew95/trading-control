"""Tests for the live cognitive snapshot adapter (real agent data, not demo)."""

from __future__ import annotations

import fakeredis

from api.constants import FieldName
from api.in_memory_store import InMemoryStore
from api.runtime_state import set_runtime_store
from api.services.cognitive_live import build_live_events, build_live_snapshot
from api.services.redis_store import RedisStore, set_redis_store


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
    # live_agents is now keyed by real agent names (signal + reasoning slots).
    from api.constants import AGENT_REASONING, AGENT_SIGNAL

    assert AGENT_SIGNAL in snap["live_agents"]
    assert AGENT_REASONING in snap["live_agents"]
    assert snap["event_count"] == 0
    # Agent Health roster is always populated (8 live agents) so the card is
    # never a blank box — idle until they produce activity.
    assert len(snap["health"]["agents"]) == 8
    assert all(info["status"] == "idle" for info in snap["health"]["agents"].values())


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


async def test_proposals_carry_real_grade_and_reason():
    """StrategyProposer suggestions must surface their grade/confidence/reason —
    the 'suggesting' integration, not an empty placeholder."""
    store = InMemoryStore()
    set_runtime_store(store)
    store.add_event(
        {
            "log_type": "proposal",
            "payload": {
                "proposal_type": "parameter_change",
                "grade_score": 0.82,
                "confidence": 0.7,
                "strategy_name": "momentum_v2",
                "content": {"parameter": "buy_threshold", "old_value": 0.6, "new_value": 0.55},
                "status": "approved",
            },
        }
    )
    snap = await build_live_snapshot()
    assert len(snap["proposals"]) == 1
    entry = snap["proposals"][0]
    assert entry["proposal_grade"]["grade"] == "B"  # 0.82 → B band
    assert entry["confidence"] == 0.7
    assert entry["proposal"]["target"] in {"momentum_v2", "buy_threshold"}
    assert entry["proposal"]["new_value"] == 0.55
    # proposal_success_rates reflect the approved suggestion
    rates = snap["evolution"]["proposal_success_rates"]
    assert rates["parameter_change"]["successes"] == 1


async def test_signal_activity_and_grade_attach_to_real_agent():
    """Signals/grades are written with source='signal_generator'; they must map to
    the canonical SIGNAL_AGENT card (the link that was previously broken)."""
    from api.constants import AGENT_SIGNAL

    store = InMemoryStore()
    set_runtime_store(store)
    store.add_event(
        {
            "source": "signal_generator",
            "data": {
                "action": "buy",
                "confidence": 0.8,
                "rsi": 31.5,
                "pct": 1.2,
                "strength": "high",
            },
        }
    )
    store.add_grade({"source": "signal_generator", "score": 0.72})

    snap = await build_live_snapshot()
    sig_live = snap["live_agents"][AGENT_SIGNAL]
    assert sig_live is not None and sig_live["rsi"] == 31.5 and sig_live["action"] == "buy"
    subjects = {g["subject_id"] for g in snap["learning"]["agent_grades"]}
    assert AGENT_SIGNAL in subjects  # source normalized to canonical agent name


async def test_live_events_shape():
    store = InMemoryStore()
    set_runtime_store(store)
    store.add_event({"type": "grade", "score": 0.5})
    events = await build_live_events(10)
    assert len(events) == 1
    assert events[0]["type"] == "grade"
    assert "seq" in events[0] and "payload" in events[0]


async def test_memory_mode_end_to_end_with_redis_up():
    """The deployed scenario: Postgres down (memory mode) but Redis up.

    ReasoningAgent pushes decisions to the RedisStore and GradeAgent writes grades
    to the runtime store — the Cognitive snapshot must reflect both, proving the
    page is live (not demo) in memory mode.
    """
    store = InMemoryStore()
    set_runtime_store(store)
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    set_redis_store(RedisStore(redis))
    try:
        rs = RedisStore(redis)
        set_redis_store(rs)
        await rs.push_decision(
            {
                FieldName.TRACE_ID: "trace-1",
                FieldName.ACTION: "buy",
                FieldName.SYMBOL: "BTC/USD",
                FieldName.CONFIDENCE: 0.77,
                FieldName.REASONING_SUMMARY: "momentum edge",
            }
        )
        store.add_grade({"subject": "REASONING_AGENT", "grade": "A", "score": 0.9})

        snap = await build_live_snapshot()

        # Decision flows from Redis into reasoning + decision + traces.
        assert snap["decision"]["latest"] is not None
        assert snap["decision"]["latest"]["action"] == "buy"
        assert snap["decision"]["latest"]["score"] == 0.77
        assert any(t["trace_id"] == "trace-1" for t in snap["traces"])
        # Grade flows from the runtime store into agent_grades.
        subjects = {g["subject_id"] for g in snap["learning"]["agent_grades"]}
        assert "REASONING_AGENT" in subjects
    finally:
        set_redis_store(None)
        await redis.aclose()
