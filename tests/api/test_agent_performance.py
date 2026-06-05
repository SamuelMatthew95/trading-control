"""Per-agent performance grading — tests for api/services/dashboard/agent_performance.py.

Grading is exercised through controlled heartbeat + run payloads so the math is
deterministic and independent of Redis / Postgres. Covers: a promoted top
performer, a probation-tier agent with failing runs, a dormant UNRATED agent,
the drill-in detail (heartbeat + newest-first activity), and the route 404.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import api.services.dashboard.agent_performance as perf
from api.constants import (
    AGENT_REASONING,
    AGENT_SIGNAL,
    SOURCE_SIGNAL,
    TIER_PROMOTED,
    TIER_UNRATED,
    StatusValue,
)
from api.routes import dashboard_v2


def _patch(monkeypatch, agents, runs):
    async def _status():
        return {"agents": agents}

    async def _metrics():
        return {"runs": runs}

    monkeypatch.setattr(perf, "get_agents_status_payload", _status)
    monkeypatch.setattr(perf, "get_agent_metrics_payload", _metrics)


def _agent(payload, name):
    return next(a for a in payload["agents"] if a["name"] == name)


@pytest.mark.asyncio
async def test_active_clean_agent_is_promoted(monkeypatch):
    agents = [
        {
            "name": AGENT_SIGNAL,
            "status": "ACTIVE",
            "event_count": 30,
            "last_event": "processed BTC/USD tick",
            "seconds_ago": 2,
            "last_seen": 100,
        }
    ]
    runs = [
        {
            "source": SOURCE_SIGNAL,
            "status": StatusValue.COMPLETED,
            "trace_id": f"t{i}",
            "created_at": float(i),
            "latency_ms": 40,
        }
        for i in range(5)
    ]
    _patch(monkeypatch, agents, runs)

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["grade"] in ("A", "A+")
    assert sig["tier"] == TIER_PROMOTED
    assert sig["promoted"] is True
    assert sig["completed_runs"] == 5
    assert sig["failed_runs"] == 0
    assert payload["promoted"] >= 1
    # All four dimensions had data (active heartbeat, runs, events, latency).
    assert all(d["data_available"] for d in sig["dimensions"])
    texts = " ".join(learning["text"] for learning in sig["learnings"])
    assert "Live" in texts
    assert "completed cleanly" in texts


@pytest.mark.asyncio
async def test_stale_failing_agent_drops_to_probation(monkeypatch):
    agents = [
        {
            "name": AGENT_SIGNAL,
            "status": "STALE",
            "event_count": 3,
            "last_event": "x",
            "seconds_ago": 300,
            "last_seen": 1,
        }
    ]
    runs = [
        {"source": SOURCE_SIGNAL, "status": StatusValue.COMPLETED, "trace_id": "c1"},
        {"source": SOURCE_SIGNAL, "status": StatusValue.COMPLETED, "trace_id": "c2"},
        {"source": SOURCE_SIGNAL, "status": StatusValue.FAILED, "trace_id": "f1"},
        {"source": SOURCE_SIGNAL, "status": StatusValue.FAILED, "trace_id": "f2"},
        {"source": SOURCE_SIGNAL, "status": StatusValue.FAILED, "trace_id": "f3"},
    ]
    _patch(monkeypatch, agents, runs)

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["grade"] in ("D", "F")
    assert sig["promoted"] is False
    assert sig["failed_runs"] == 3
    # No latency recorded → that dimension is flagged unavailable, not scored 0.
    latency_dim = next(d for d in sig["dimensions"] if d["key"] == "latency")
    assert latency_dim["data_available"] is False
    tones = [learning["tone"] for learning in sig["learnings"]]
    assert "danger" in tones  # 60% failure rate is a danger-toned learning


@pytest.mark.asyncio
async def test_dormant_agent_is_unrated_not_failed(monkeypatch):
    # No heartbeat row, no runs anywhere.
    _patch(monkeypatch, [], [])

    payload = await perf.get_agent_performance_payload()
    reasoning = _agent(payload, AGENT_REASONING)

    assert reasoning["grade"] is None
    assert reasoning["score"] is None
    assert reasoning["tier"] == TIER_UNRATED
    assert reasoning["promoted"] is False
    assert reasoning["status"] == "INSUFFICIENT_DATA"
    assert "not graded" in reasoning["learnings"][0]["text"]


@pytest.mark.asyncio
async def test_detail_has_heartbeat_and_newest_first_activity(monkeypatch):
    agents = [
        {
            "name": AGENT_SIGNAL,
            "status": "ACTIVE",
            "event_count": 10,
            "last_event": "tick",
            "seconds_ago": 1,
            "last_seen": 99,
        }
    ]
    runs = [
        {
            "source": SOURCE_SIGNAL,
            "status": StatusValue.COMPLETED,
            "trace_id": f"t{i}",
            "created_at": float(i),
            "input_data": {"symbol": "BTC/USD"},
        }
        for i in range(3)
    ]
    _patch(monkeypatch, agents, runs)

    detail = await perf.get_agent_detail_payload(AGENT_SIGNAL)

    assert detail["heartbeat"]["status"] == "ACTIVE"
    assert detail["heartbeat"]["last_event"] == "tick"
    activity = detail["recent_activity"]
    assert len(activity) == 3
    # Newest run (last appended) first.
    assert activity[0]["trace_id"] == "t2"
    assert activity[0]["symbol"] == "BTC/USD"
    assert detail["recent_activity"][-1]["trace_id"] == "t0"


@pytest.mark.asyncio
async def test_detail_route_404_for_unknown_agent():
    with pytest.raises(HTTPException) as exc:
        await dashboard_v2.get_agent_detail("NOT_A_REAL_AGENT")
    assert exc.value.status_code == 404
