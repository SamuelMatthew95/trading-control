"""Per-agent performance grading — tests for api/services/dashboard/agent_performance.py.

Grading is exercised through controlled heartbeat + run payloads so the math is
deterministic and independent of Redis / Postgres. Covers: the streak-based
promotion (a single A window is TRUSTED until sustained, then PROMOTED), a
probation-tier agent with failing runs, a dormant UNRATED agent, the drill-in
detail (heartbeat + newest-first activity), the trust-apply writer, and 404.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

import api.services.dashboard.agent_performance as perf
from api.constants import (
    AGENT_PROMOTION_STREAK,
    AGENT_REASONING,
    AGENT_SIGNAL,
    REDIS_KEY_AGENT_TRUST,
    SOURCE_SIGNAL,
    TIER_PROMOTED,
    TIER_TRUSTED,
    TIER_UNRATED,
    StatusValue,
)
from api.routes import dashboard_v2


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


class _FakeStore:
    """Minimal RedisStore stand-in for per-agent grade history."""

    def __init__(self, history: list[dict[str, Any]] | None = None) -> None:
        self._history = list(history or [])
        self.recorded: list[tuple[str, dict[str, Any]]] = []

    async def list_agent_grades(self, name: str, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._history)

    async def record_agent_grade(self, name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._history.insert(0, snapshot)
        self.recorded.append((name, snapshot))
        return snapshot


class _FakePnlStore:
    """Stand-in for AgentPnLStore — returns the per-agent stats it was given."""

    def __init__(self, stats_by_agent: dict[str, dict[str, Any]] | None = None) -> None:
        self._stats = dict(stats_by_agent or {})

    async def get_all(self, names: list[str]) -> dict[str, dict[str, Any]]:
        return {n: self._stats[n] for n in names if n in self._stats}


def _pnl_stats(trade_count: int, win_rate: float, total_pnl: float = 0.0) -> dict[str, Any]:
    from api.constants import FieldName  # noqa: PLC0415

    return {
        FieldName.TRADE_COUNT: trade_count,
        FieldName.WIN_COUNT: round(trade_count * win_rate),
        FieldName.WIN_RATE: win_rate,
        FieldName.TOTAL_PNL: total_pnl,
        FieldName.UPDATED_AT: None,
    }


def _patch(monkeypatch, agents, runs, *, store=None, redis=None, pnl=None):
    async def _status():
        return {"agents": agents}

    async def _metrics():
        return {"runs": runs}

    async def _get_redis():
        return redis if redis is not None else _FakeRedis()

    monkeypatch.setattr(perf, "get_agents_status_payload", _status)
    monkeypatch.setattr(perf, "get_agent_metrics_payload", _metrics)
    monkeypatch.setattr(perf, "get_redis_store", lambda: store)
    monkeypatch.setattr(perf, "get_redis", _get_redis)
    # PnL store: None (no data) unless the test supplies stats.
    monkeypatch.setattr(perf, "get_agent_pnl_store", lambda: _FakePnlStore(pnl) if pnl else None)


def _agent(payload, name):
    return next(a for a in payload["agents"] if a["name"] == name)


def _winning_pnl():
    """A realized record that clears every PnL gate (sample, win rate, +PnL).

    Grades are coverage-capped: a TRADING agent can only reach A/A+ with its
    PnL dimension scored, so the healthy-agent tests must supply this."""
    return {AGENT_SIGNAL: _pnl_stats(trade_count=25, win_rate=0.7, total_pnl=500.0)}


def _active_signal_hb():
    return [
        {
            "name": AGENT_SIGNAL,
            "status": "ACTIVE",
            "event_count": 30,
            "last_event": "processed BTC/USD tick",
            "seconds_ago": 2,
            "last_seen": 100,
        }
    ]


def _clean_runs(n=5):
    return [
        {
            "source": SOURCE_SIGNAL,
            "status": StatusValue.COMPLETED,
            "trace_id": f"t{i}",
            "created_at": float(i),
            "latency_ms": 40,
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_single_a_window_is_trusted_not_yet_promoted(monkeypatch):
    # Fresh history → an A grade earns TRUSTED, promotion pending a streak. The
    # GET path is read-only: it must NOT write a snapshot.
    store = _FakeStore()
    _patch(monkeypatch, _active_signal_hb(), _clean_runs(), store=store, pnl=_winning_pnl())

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["grade"] in ("A", "A+")
    assert sig["tier"] == TIER_TRUSTED
    assert sig["promoted"] is False
    assert sig["grade_streak"] == 0  # no history yet (recorder hasn't run)
    assert payload["promoted"] == 0
    assert store.recorded == []  # read path never writes


@pytest.mark.asyncio
async def test_sustained_a_streak_earns_promotion(monkeypatch):
    # AGENT_PROMOTION_STREAK prior A snapshots (recent) → current A → PROMOTED.
    history = [
        {"grade": "A", "tier": TIER_TRUSTED, "timestamp": perf._iso(0)}
        for _ in range(AGENT_PROMOTION_STREAK)
    ]
    # Use a near-now timestamp so _should_record doesn't append a 4th and the
    # head grade matches; the streak comes from the 3 stored A's.
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    for h in history:
        h["timestamp"] = now
    # SIGNAL is a trading agent, so promotion now also requires a winning realized
    # record (the PnL gate) — supply one alongside the sustained A streak.
    _patch(
        monkeypatch,
        _active_signal_hb(),
        _clean_runs(),
        store=_FakeStore(history),
        pnl=_winning_pnl(),
    )

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["promoted"] is True
    assert sig["tier"] == TIER_PROMOTED
    assert sig["grade_streak"] >= AGENT_PROMOTION_STREAK
    assert payload["promoted"] == 1


@pytest.mark.asyncio
async def test_no_store_degrades_to_single_window(monkeypatch):
    # Without a RedisStore there is no durable history; promotion can't be earned.
    _patch(monkeypatch, _active_signal_hb(), _clean_runs(), store=None, pnl=_winning_pnl())

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["grade"] in ("A", "A+")
    assert sig["promoted"] is False
    assert sig["tier"] == TIER_TRUSTED


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
    _patch(monkeypatch, agents, runs, store=_FakeStore())

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["grade"] in ("D", "F")
    assert sig["promoted"] is False
    assert sig["failed_runs"] == 3
    latency_dim = next(d for d in sig["dimensions"] if d["key"] == "latency")
    assert latency_dim["data_available"] is False
    tones = [learning["tone"] for learning in sig["learnings"]]
    assert "danger" in tones


@pytest.mark.asyncio
async def test_dormant_agent_is_unrated_not_failed(monkeypatch):
    _patch(monkeypatch, [], [], store=_FakeStore())

    payload = await perf.get_agent_performance_payload()
    reasoning = _agent(payload, AGENT_REASONING)

    assert reasoning["grade"] is None
    assert reasoning["score"] is None
    assert reasoning["tier"] == TIER_UNRATED
    assert reasoning["promoted"] is False
    assert reasoning["grade_streak"] == 0
    assert reasoning["status"] == "INSUFFICIENT_DATA"
    assert "not graded" in reasoning["learnings"][0]["text"]


@pytest.mark.asyncio
async def test_alive_but_idle_agent_is_unrated_not_graded(monkeypatch):
    # Regression: an agent that is heartbeating but has processed 0 events and
    # has no runs must NOT earn a letter grade purely for being alive. Before the
    # fix it scored liveness/(liveness+throughput) = 0.40/0.55 = 72.7% → a fake
    # "B" / TRUSTED tier. It must read as UNRATED instead.
    agents = [
        {
            "name": AGENT_SIGNAL,
            "status": "ACTIVE",
            "event_count": 0,
            "last_event": "",
            "seconds_ago": 2,
            "last_seen": 100,
        }
    ]
    _patch(monkeypatch, agents, [], store=_FakeStore())

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["grade"] is None
    assert sig["score"] is None
    assert sig["tier"] == TIER_UNRATED
    assert sig["promoted"] is False
    # Throughput is no longer a scored dimension at 0 events.
    throughput = next(d for d in sig["dimensions"] if d["key"] == "throughput")
    assert throughput["data_available"] is False
    # Honest learning: "alive but idle", not "dormant / no heartbeat".
    assert "Idle" in sig["learnings"][0]["text"]


@pytest.mark.asyncio
async def test_detail_has_heartbeat_activity_history_and_trust(monkeypatch):
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
    _patch(monkeypatch, _active_signal_hb(), runs, store=_FakeStore())

    detail = await perf.get_agent_detail_payload(AGENT_SIGNAL)

    assert detail["heartbeat"]["status"] == "ACTIVE"
    assert detail["heartbeat"]["last_event"] == "processed BTC/USD tick"
    activity = detail["recent_activity"]
    assert activity[0]["trace_id"] == "t2"  # newest first
    assert activity[0]["symbol"] == "BTC/USD"
    # Drill-in carries durable history + live/target trust.
    assert "history" in detail
    assert detail["trust"] == 1.0
    assert "target_trust" in detail


@pytest.mark.asyncio
async def test_apply_promotions_writes_trust_weights(monkeypatch):
    redis = _FakeRedis()
    _patch(monkeypatch, _active_signal_hb(), _clean_runs(), store=_FakeStore(), redis=redis)

    result = await perf.apply_agent_promotions_payload()

    assert "applied" in result
    assert "enabled" in result  # reflects AGENT_TRUST_WEIGHTING_ENABLED (default False)
    # A trust weight was written for the signal agent (TRUSTED tier → 1.0).
    key = REDIS_KEY_AGENT_TRUST.format(name=AGENT_SIGNAL)
    assert key in redis.store
    entry = next(a for a in result["applied"] if a["name"] == AGENT_SIGNAL)
    assert entry["trust"] == 1.0


@pytest.mark.asyncio
async def test_record_grade_snapshots_writes_throttled_history(monkeypatch):
    store = _FakeStore()
    _patch(monkeypatch, _active_signal_hb(), _clean_runs(), store=store, pnl=_winning_pnl())

    # First pass writes a snapshot for the graded agent.
    n = await perf.record_grade_snapshots()
    assert n >= 1
    assert any(name == AGENT_SIGNAL for name, _ in store.recorded)
    assert store._history[0][perf.FieldName.GRADE] in ("A", "A+")

    # Immediate second pass is throttled (same grade, within interval) → no write.
    before = len(store.recorded)
    assert await perf.record_grade_snapshots() == 0
    assert len(store.recorded) == before


@pytest.mark.asyncio
async def test_record_grade_snapshots_skips_dormant_agents(monkeypatch):
    store = _FakeStore()
    _patch(monkeypatch, [], [], store=store)  # no heartbeats, no runs → all UNRATED
    assert await perf.record_grade_snapshots() == 0
    assert store.recorded == []


@pytest.mark.asyncio
async def test_streak_promotion_uses_recorded_history(monkeypatch):
    # The recorder builds history; once the streak is long enough the read path
    # reports PROMOTED — end-to-end through the single-writer design.
    store = _FakeStore()
    # SIGNAL is a trading agent → the PnL gate also requires a winning record.
    _patch(
        monkeypatch,
        _active_signal_hb(),
        _clean_runs(),
        store=store,
        pnl=_winning_pnl(),
    )

    # Seed a long streak by recording past the throttle (clear timestamps).
    for _ in range(AGENT_PROMOTION_STREAK):
        await perf.record_grade_snapshots()
        for snap in store._history:
            snap[perf.FieldName.TIMESTAMP] = perf._iso(0)  # age out the throttle

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)
    assert sig["grade_streak"] >= AGENT_PROMOTION_STREAK
    assert sig["promoted"] is True
    assert sig["tier"] == TIER_PROMOTED


@pytest.mark.asyncio
async def test_background_tick_reconciles_trust_only_when_enabled(monkeypatch):
    # Build a promoted streak so the agent's tier maps to a boosted trust weight.
    # SIGNAL is a trading agent → the PnL gate also requires a winning record.
    history = [
        {"grade": "A", "tier": TIER_PROMOTED, "timestamp": perf._iso(0)}
        for _ in range(AGENT_PROMOTION_STREAK)
    ]
    redis = _FakeRedis()
    _patch(
        monkeypatch,
        _active_signal_hb(),
        _clean_runs(),
        store=_FakeStore(history),
        redis=redis,
        pnl=_winning_pnl(),
    )
    trust_key = REDIS_KEY_AGENT_TRUST.format(name=AGENT_SIGNAL)

    # Flag OFF → background tick records snapshots but writes NO trust weights.
    monkeypatch.setattr(perf.settings, "AGENT_TRUST_WEIGHTING_ENABLED", False)
    await perf._grade_snapshot_tick()
    assert trust_key not in redis.store

    # Flag ON → background tick reconciles trust autonomously (no UI / button).
    monkeypatch.setattr(perf.settings, "AGENT_TRUST_WEIGHTING_ENABLED", True)
    await perf._grade_snapshot_tick()
    assert trust_key in redis.store
    assert float(redis.store[trust_key]) > 1.0  # promoted → boosted influence


@pytest.mark.asyncio
async def test_detail_route_404_for_unknown_agent():
    with pytest.raises(HTTPException) as exc:
        await dashboard_v2.get_agent_detail("NOT_A_REAL_AGENT")
    assert exc.value.status_code == 404


def test_status_text_handles_enum_and_string():
    """Version-safe: StrEnum members (memory-mode run status) normalize to value
    on both Python 3.10 (backport) and 3.11 (enum.StrEnum)."""
    assert perf._status_text(StatusValue.COMPLETED) == "completed"
    assert perf._status_text(StatusValue.FAILED) == "failed"
    assert perf._status_text("Completed") == "completed"
    assert perf._status_text(None) == ""


# ── Realized-PnL grading for trading agents (durable Redis store) ────────────


@pytest.mark.asyncio
async def test_trading_agent_graded_on_realized_pnl(monkeypatch):
    """A trading agent with enough closed trades gets a scored PnL dimension."""
    _patch(
        monkeypatch,
        _active_signal_hb(),
        _clean_runs(),
        store=_FakeStore(),
        pnl={AGENT_SIGNAL: _pnl_stats(trade_count=20, win_rate=0.7, total_pnl=900.0)},
    )
    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)
    pnl_dim = next(d for d in sig["dimensions"] if d["label"] == "Realized PnL")
    assert pnl_dim["data_available"] is True
    assert pnl_dim["value"] == pytest.approx(0.7, rel=1e-3)


@pytest.mark.asyncio
async def test_trading_agent_pnl_unrated_below_min_trades(monkeypatch):
    """Below the min-trades sample the PnL dimension is 'no data', not a fake 0%."""
    _patch(
        monkeypatch,
        _active_signal_hb(),
        _clean_runs(),
        store=_FakeStore(),
        pnl={AGENT_SIGNAL: _pnl_stats(trade_count=3, win_rate=1.0, total_pnl=50.0)},
    )
    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)
    pnl_dim = next(d for d in sig["dimensions"] if d["label"] == "Realized PnL")
    assert pnl_dim["data_available"] is False


@pytest.mark.asyncio
async def test_pnl_gate_blocks_promotion_when_losing(monkeypatch):
    """A sustained A streak does NOT promote a trading agent that loses money."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    history = [{"grade": "A", "tier": TIER_TRUSTED, "timestamp": now} for _ in range(3)]
    _patch(
        monkeypatch,
        _active_signal_hb(),
        _clean_runs(),
        store=_FakeStore(history),
        pnl={AGENT_SIGNAL: _pnl_stats(trade_count=20, win_rate=0.25, total_pnl=-800.0)},
    )
    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)
    assert sig["promoted"] is False  # losing money → gate blocks promotion
    assert sig["tier"] == TIER_TRUSTED  # A grade still shows TRUSTED, just not promoted


@pytest.mark.asyncio
async def test_partial_evidence_cannot_reach_top_grade(monkeypatch):
    """Regression for "3/5 dims scored → 100% A+": the score is capped by data
    coverage, so a trading agent with perfect liveness/success/throughput but NO
    latency and NO PnL evidence cannot renormalize its way to an A."""
    hb = [
        {
            "name": AGENT_SIGNAL,
            "status": "ACTIVE",
            "event_count": 500,  # saturates throughput
            "last_event": "x",
            "seconds_ago": 2,
            "last_seen": 100,
        }
    ]
    # Completed runs with no latency recorded → latency dim unavailable.
    runs = [
        {"source": SOURCE_SIGNAL, "status": StatusValue.COMPLETED, "trace_id": f"t{i}"}
        for i in range(5)
    ]
    _patch(monkeypatch, hb, runs, store=_FakeStore())  # no PnL data either

    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)

    assert sig["grade"] is not None  # still graded — just honestly
    assert sig["grade"] not in ("A", "A+")
    assert sig["score_pct"] < 70
    # The cap is explained to the operator.
    assert any("capped" in learning["text"] for learning in sig["learnings"])


@pytest.mark.asyncio
async def test_pnl_gate_requires_positive_total_pnl(monkeypatch):
    """A win rate above the bar with NEGATIVE total PnL must not promote —
    winning often while losing money overall is not a promotable record."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    history = [
        {"grade": "A", "tier": TIER_TRUSTED, "timestamp": now}
        for _ in range(AGENT_PROMOTION_STREAK)
    ]
    _patch(
        monkeypatch,
        _active_signal_hb(),
        _clean_runs(),
        store=_FakeStore(history),
        pnl={AGENT_SIGNAL: _pnl_stats(trade_count=25, win_rate=0.7, total_pnl=-120.0)},
    )
    payload = await perf.get_agent_performance_payload()
    sig = _agent(payload, AGENT_SIGNAL)
    assert sig["promoted"] is False


@pytest.mark.asyncio
async def test_non_trading_agent_has_no_pnl_dimension(monkeypatch):
    """The PnL dimension applies only to trading agents — others never carry it."""
    from api.constants import AGENT_REFLECTION

    hb = [
        {
            "name": AGENT_REFLECTION,
            "status": "ACTIVE",
            "event_count": 12,
            "seconds_ago": 2,
            "last_seen": 100,
        }
    ]
    _patch(monkeypatch, hb, [], store=_FakeStore())
    payload = await perf.get_agent_performance_payload()
    refl = _agent(payload, AGENT_REFLECTION)
    assert all(d["label"] != "Realized PnL" for d in refl["dimensions"])
