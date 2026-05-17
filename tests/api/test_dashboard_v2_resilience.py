from __future__ import annotations

import pytest

from api.constants import LogType
from api.in_memory_store import InMemoryStore
from api.routes import dashboard_v2
from api.runtime_state import set_db_available, set_runtime_store
import api.services.dashboard.agents as agents_svc
import api.services.dashboard.events as events_svc
import api.services.dashboard.flow as flow_svc
import api.services.dashboard.learning as learning_svc
import api.services.dashboard.pnl as pnl_svc
import api.services.dashboard.proposals as proposals_svc
import api.services.dashboard.state as state_svc
import api.services.dashboard.system as system_svc
import api.services.dashboard.trading as trading_svc
import api.services.dashboard.traces as traces_svc


class _ExplodingSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("db unavailable")


def _exploding_factory():
    return _ExplodingSession()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ResultWithFirst(_Result):
    def first(self):
        return self._rows[0] if self._rows else None


class _SessionFromResults:
    def __init__(self, queued_results):
        self._queued_results = queued_results

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        if not self._queued_results:
            raise AssertionError("No queued DB result left for execute()")
        return _Result(self._queued_results.pop(0))


class _FactoryWithQueuedSessions:
    def __init__(self, sessions_rows):
        self._sessions_rows = sessions_rows

    def __call__(self):
        if not self._sessions_rows:
            raise AssertionError("No queued session left for AsyncSessionFactory()")
        return _SessionFromResults(self._sessions_rows.pop(0))


class _SessionThatAlwaysFails:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("undefined column")


class _FactoryOneSuccessThenFail:
    def __init__(self, first_rows):
        self._first_rows = first_rows
        self._call_count = 0

    def __call__(self):
        self._call_count += 1
        if self._call_count == 1:
            return _SessionFromResults([self._first_rows])
        return _SessionThatAlwaysFails()


@pytest.mark.asyncio
async def test_trade_feed_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(trading_svc, "is_db_available", lambda: True)
    monkeypatch.setattr(trading_svc, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_trade_feed()

    assert payload["count"] == 0
    assert payload["trades"] == []
    assert payload["source"] == "in_memory"


@pytest.mark.asyncio
async def test_pnl_metrics_uses_in_memory_state_when_db_unavailable():
    set_db_available(False)
    store = InMemoryStore()
    store.add_order({"order_id": "o1", "symbol": "BTC/USD", "pnl": 125.5})
    store.add_order({"order_id": "o2", "symbol": "ETH/USD", "pnl": -25.0})
    store.upsert_position(
        "BTC/USD",
        {"symbol": "BTC/USD", "side": "long", "qty": 1.0, "unrealized_pnl": 10.0},
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_pnl_metrics()

    assert payload["source"] == "in_memory"
    assert payload["total_pnl"] == pytest.approx(100.5)
    assert payload["winning_trades"] == 1
    assert payload["losing_trades"] == 1
    assert payload["active_positions"] == 1


@pytest.mark.asyncio
async def test_pnl_metrics_counts_short_positions_in_memory_mode():
    set_db_available(False)
    store = InMemoryStore()
    store.upsert_position(
        "TSLA",
        {"symbol": "TSLA", "side": "short", "qty": -3.0, "unrealized_pnl": 12.5},
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_pnl_metrics()

    assert payload["source"] == "in_memory"
    assert payload["active_positions"] == 1


@pytest.mark.asyncio
async def test_paired_pnl_fallback_uses_in_memory_orders(monkeypatch):
    set_db_available(False)
    store = InMemoryStore()
    store.add_order({"order_id": "o1", "symbol": "BTC/USD", "pnl": 200.0})
    store.upsert_position(
        "BTC/USD",
        {"symbol": "BTC/USD", "side": "long", "qty": 2.0, "unrealized_pnl": 35.0},
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_paired_pnl(RequestStub())

    assert payload["source"] == "in_memory"
    assert payload["summary"]["realized_pnl"] == pytest.approx(200.0)
    assert payload["summary"]["unrealized_pnl"] == pytest.approx(35.0)
    assert payload["summary"]["total_pnl"] == pytest.approx(235.0)
    assert payload["summary"]["open_positions"] == 1


@pytest.mark.asyncio
async def test_paired_pnl_in_memory_filters_flat_and_bad_qty_positions():
    set_db_available(False)
    store = InMemoryStore()
    store.upsert_position(
        "TSLA",
        {"symbol": "TSLA", "side": "short", "qty": -2.0, "unrealized_pnl": 15.0},
    )
    store.upsert_position(
        "AAPL",
        {"symbol": "AAPL", "side": "long", "qty": 0.0, "unrealized_pnl": 99.0},
    )
    store.upsert_position(
        "BAD",
        {"symbol": "BAD", "side": "long", "qty": "bad", "unrealized_pnl": 50.0},
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_paired_pnl(RequestStub())

    assert payload["summary"]["open_positions"] == 1
    assert payload["summary"]["unrealized_pnl"] == pytest.approx(15.0)
    assert [p["symbol"] for p in payload["open_positions"]] == ["TSLA"]


class RequestStub:
    class _State:
        redis_client = None

    class _App:
        def __init__(self):
            self.state = RequestStub._State()

    def __init__(self):
        self.app = self._App()


class _MemoryModeRedis:
    async def mget(self, keys):
        return [None for _ in keys]

    async def get(self, _key):
        return None

    async def xlen(self, _stream):
        return 0


@pytest.mark.asyncio
async def test_performance_trends_falls_back_to_runtime_store_when_query_fails(monkeypatch):
    """DB failure should return runtime store data, not empty zeros."""
    monkeypatch.setattr(trading_svc, "is_db_available", lambda: True)
    store = InMemoryStore()
    store.apply_decision(
        {"action": "buy", "symbol": "BTC/USD", "price": 80000.0, "qty": 0.1, "trace_id": "pt1"}
    )
    store.apply_decision(
        {"action": "sell", "symbol": "BTC/USD", "price": 81000.0, "qty": 0.1, "trace_id": "pt2"}
    )
    set_runtime_store(store)
    monkeypatch.setattr(trading_svc, "AsyncSessionFactory", _exploding_factory)

    payload = await dashboard_v2.get_performance_trends()

    assert payload["source"] == "db_error"
    assert payload["summary"]["total_trades"] > 0
    assert payload["summary"]["total_pnl"] > 0
    assert payload["daily_pnl"] == []
    assert payload["grade_trend"] == []
    assert "error" not in payload


@pytest.mark.asyncio
async def test_agent_instances_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(agents_svc, "is_db_available", lambda: True)
    monkeypatch.setattr(agents_svc, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_agent_instances()

    assert payload["instances"] == []
    assert payload["active_count"] == 0
    assert payload["retired_count"] == 0
    assert payload["error"] == "agent_instances_unavailable"


@pytest.mark.asyncio
async def test_agent_instances_use_memory_without_opening_db_when_db_unavailable(monkeypatch):
    def _raise_if_called():
        raise AssertionError("DB session should not be created in memory mode")

    monkeypatch.setattr(agents_svc, "AsyncSessionFactory", _raise_if_called)
    store = InMemoryStore()
    store.upsert_agent(
        "SIGNAL_AGENT",
        {
            "status": "ACTIVE",
            "event_count": 7,
            "last_event": "heartbeat",
            "last_seen": 1_710_000_000,
            "last_seen_at": "2024-03-09T16:00:00Z",
        },
    )
    set_runtime_store(store)
    set_db_available(False)

    payload = await dashboard_v2.get_agent_instances()

    assert payload["source"] == "in_memory"
    assert payload["active_count"] == 1
    assert payload["retired_count"] == 0
    assert len(payload["instances"]) == 1
    row = payload["instances"][0]
    assert row["id"] == "memory:SIGNAL_AGENT"
    assert row["instance_key"] == "signal-agent"
    assert row["pool_name"] == "SIGNAL_AGENT"
    assert row["status"] == "active"
    assert row["started_at"] == "2024-03-09T16:00:00Z"
    assert row["retired_at"] is None
    assert row["event_count"] == 7
    assert row["uptime_seconds"] >= 0


def test_system_metrics_alias_route_exists():
    paths = {route.path for route in dashboard_v2.router.routes}
    assert "/dashboard/system-metrics" in paths


@pytest.mark.asyncio
async def test_event_history_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(events_svc, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_event_history()

    assert payload["stream_counts"] == []
    assert payload["persisted_events"] == []
    assert payload["persisted_logs"] == []


@pytest.mark.asyncio
async def test_learning_proposals_fallbacks_to_events_when_agent_logs_empty(monkeypatch):
    monkeypatch.setattr(learning_svc, "is_db_available", lambda: True)
    # First session (agent_logs query): empty. Second session (events query): one row.
    session_rows = [
        [[]],
        [[("evt-1", {"status": "pending", "confidence": 0.71}, None)]],
    ]
    monkeypatch.setattr(
        learning_svc,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    payload = await dashboard_v2.get_proposals(limit=10)

    assert payload["total"] == 1
    assert payload["proposals"][0]["id"] == "evt-1"
    assert payload["proposals"][0]["content"]["confidence"] == 0.71


@pytest.mark.asyncio
async def test_learning_proposals_returns_empty_when_events_fallback_errors(monkeypatch):
    monkeypatch.setattr(learning_svc, "is_db_available", lambda: True)
    monkeypatch.setattr(
        learning_svc,
        "AsyncSessionFactory",
        _FactoryOneSuccessThenFail(first_rows=[]),
    )

    payload = await dashboard_v2.get_proposals(limit=10)

    assert payload["total"] == 0
    assert payload["proposals"] == []


@pytest.mark.asyncio
async def test_learning_grades_fallbacks_to_agent_grades_when_logs_empty(monkeypatch):
    monkeypatch.setattr(learning_svc, "is_db_available", lambda: True)
    session_rows = [
        [[]],
        [[("trace-1", 0.84, {"fills_graded": 4}, None)]],
    ]
    monkeypatch.setattr(
        learning_svc,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    payload = await dashboard_v2.get_grade_history(limit=10)

    assert payload["total"] == 1
    assert payload["grades"][0]["trace_id"] == "trace-1"
    assert payload["grades"][0]["score"] == 0.84
    assert payload["grades"][0]["score_pct"] == 0.84
    assert payload["grades"][0]["fills_graded"] == 4


@pytest.mark.asyncio
async def test_learning_grades_uses_in_memory_when_db_unavailable(monkeypatch):
    # DB is not available → endpoint routes directly to in-memory store (no DB attempt).
    set_db_available(False)
    store = InMemoryStore()
    store.add_grade(
        {
            "trace_id": "mem-trace-1",
            "grade": "B",
            "score": 0.77,
            "score_pct": 77.0,
            "metrics": {"fills_graded": 2},
            "fills_graded": 2,
        }
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_grade_history(limit=10)

    assert payload["total"] == 1
    assert payload["grades"][0]["trace_id"] == "mem-trace-1"
    assert payload["source"] == "in_memory"


@pytest.mark.asyncio
async def test_trade_feed_fallbacks_to_orders_when_lifecycle_empty(monkeypatch):
    monkeypatch.setattr(trading_svc, "is_db_available", lambda: True)
    session_rows = [
        [[]],
        [[("ord-1", "AAPL", "buy", 1.5, 190.0, "filled", None, None, None, None)]],
    ]
    monkeypatch.setattr(
        trading_svc,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    payload = await dashboard_v2.get_trade_feed(limit=10)

    assert payload["count"] == 1
    assert payload["trades"][0]["id"] == "ord-1"
    assert payload["trades"][0]["symbol"] == "AAPL"
    assert payload["trades"][0]["status"] == "filled"
    assert payload["trades"][0]["execution_trace_id"] is None


@pytest.mark.asyncio
async def test_proposals_endpoint_falls_back_to_agent_logs_when_events_unavailable(monkeypatch):
    monkeypatch.setattr(proposals_svc, "is_db_available", lambda: True)
    session_rows = [
        [[]],
        [[("trace-99", {"symbol": "TSLA", "status": "pending"}, None)]],
    ]
    monkeypatch.setattr(
        proposals_svc,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    payload = await dashboard_v2.list_proposals()

    assert len(payload["proposals"]) == 1
    assert payload["proposals"][0]["id"] == "trace-99"
    assert payload["proposals"][0]["source"] == "agent_logs"


@pytest.mark.asyncio
async def test_proposals_use_memory_without_opening_db_when_db_unavailable(monkeypatch):
    def _raise_if_called():
        raise AssertionError("DB session should not be created in memory mode")

    monkeypatch.setattr(proposals_svc, "AsyncSessionFactory", _raise_if_called)
    monkeypatch.setattr(learning_svc, "AsyncSessionFactory", _raise_if_called)
    store = InMemoryStore()
    store.add_event(
        {
            "log_type": LogType.PROPOSAL,
            "trace_id": "mem-proposal",
            "payload": {
                "proposal_type": "parameter_change",
                "content": {"description": "Tighten sizing"},
                "confidence": 0.82,
                "status": "pending",
            },
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    panel_payload = await dashboard_v2.list_proposals()
    learning_payload = await dashboard_v2.get_proposals(limit=10)

    assert panel_payload["source"] == "in_memory"
    assert panel_payload["proposals"][0]["id"] == "mem-proposal"
    assert learning_payload["source"] == "in_memory"
    assert learning_payload["total"] == 1
    assert learning_payload["proposals"][0]["content"]["description"] == "Tighten sizing"


@pytest.mark.asyncio
async def test_dashboard_memory_mode_never_opens_db_sessions(monkeypatch):
    factory_calls = []

    def _record_db_call():
        factory_calls.append("called")
        return _ExplodingSession()

    async def _get_redis():
        return _MemoryModeRedis()

    # Patch AsyncSessionFactory on all service modules that have it
    for svc in (
        agents_svc,
        events_svc,
        flow_svc,
        learning_svc,
        pnl_svc,
        proposals_svc,
        state_svc,
        system_svc,
        trading_svc,
        traces_svc,
    ):
        monkeypatch.setattr(svc, "AsyncSessionFactory", _record_db_call)

    # Patch get_redis on all service modules that have it
    for svc in (agents_svc, state_svc, system_svc, trading_svc, learning_svc):
        monkeypatch.setattr(svc, "get_redis", _get_redis)

    store = InMemoryStore()
    store.add_event(
        {
            "id": "mem-proposal-event",
            "log_type": LogType.PROPOSAL,
            "trace_id": "mem-proposal",
            "payload": {
                "proposal_type": "parameter_change",
                "content": {"description": "Memory proposal"},
                "status": "pending",
            },
        }
    )
    store.add_agent_log(
        {
            "log_type": LogType.REFLECTION,
            "trace_id": "mem-trace",
            "payload": {"summary": "Memory reflection", "hypotheses": ["size down"]},
        }
    )
    store.add_agent_run(
        {
            "id": "run-1",
            "trace_id": "mem-trace",
            "agent_name": "ReflectionAgent",
            "status": "completed",
        }
    )
    store.add_grade({"trace_id": "mem-trace", "grade": "B", "score": 0.74})
    store.add_order({"order_id": "ord-1", "symbol": "SPY", "status": "filled", "pnl": 12.0})
    store.upsert_position("SPY", {"symbol": "SPY", "side": "long", "qty": 1, "unrealized_pnl": 3})
    store.upsert_trade_fill(
        {
            "id": "trade-1",
            "symbol": "SPY",
            "side": "buy",
            "qty": 1,
            "entry_price": 500,
            "execution_trace_id": "mem-trace",
            "status": "filled",
            "pnl": 12.0,
        }
    )
    store.upsert_agent(
        "SIGNAL_AGENT",
        {"status": "ACTIVE", "event_count": 1, "last_seen": 1_710_000_000},
    )
    set_runtime_store(store)
    set_db_available(False)

    payloads = [
        await dashboard_v2.get_dashboard_snapshot(),
        await dashboard_v2.get_dashboard_state(),
        await dashboard_v2.get_stream_lag(),
        await dashboard_v2.get_system_health(),
        await dashboard_v2.get_pnl_metrics(),
        await dashboard_v2.get_paired_pnl(RequestStub()),
        await dashboard_v2.get_agent_metrics(),
        await dashboard_v2.get_order_metrics(),
        await dashboard_v2.get_flow_status(),
        await dashboard_v2.get_prices(),
        await dashboard_v2.get_agents_status(),
        await dashboard_v2.get_system_stream_metrics(),
        await dashboard_v2.get_recent_events(),
        await dashboard_v2.get_event_history(),
        await dashboard_v2.list_proposals(),
        await dashboard_v2.get_proposals(limit=10),
        await dashboard_v2.get_grade_history(limit=10),
        await dashboard_v2.get_ic_weights(),
        await dashboard_v2.get_reflections(limit=10),
        await dashboard_v2.get_trace("mem-trace"),
        await dashboard_v2.get_trade_feed(limit=10),
        await dashboard_v2.get_performance_trends(),
        await dashboard_v2.get_agent_instances(),
        await dashboard_v2.approve_proposal("mem-proposal"),
        await dashboard_v2.reject_proposal("mem-proposal"),
        await dashboard_v2.update_proposal_status("mem-proposal", status="approved"),
    ]

    assert factory_calls == []
    assert all(isinstance(payload, dict) for payload in payloads)
    assert payloads[14]["proposals"][0]["source"] == "in_memory"
    assert payloads[18]["reflections"][0]["summary"] == "Memory reflection"
    assert payloads[19]["source"] == "in_memory"


@pytest.mark.asyncio
async def test_learning_endpoints_accept_stringified_payloads(monkeypatch):
    monkeypatch.setattr(learning_svc, "is_db_available", lambda: True)
    session_rows = [
        [[("trace-prop", '{"status":"approved","content":{"k":"v"}}', None)]],
        [[("trace-grade", '{"grade":"A","score":0.92,"metrics":{"fills_graded":3}}', None)]],
    ]
    monkeypatch.setattr(
        learning_svc,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    proposals_payload = await dashboard_v2.get_proposals(limit=5)
    grades_payload = await dashboard_v2.get_grade_history(limit=5)

    assert proposals_payload["total"] == 1
    assert proposals_payload["proposals"][0]["status"] == "approved"
    assert grades_payload["total"] == 1
    assert grades_payload["grades"][0]["grade"] == "A"


@pytest.mark.asyncio
async def test_dashboard_state_db_failure_returns_in_memory_snapshot(monkeypatch):
    class _FailingAggregator:
        def __init__(self, _session):
            pass

        async def get_raw_snapshot(self):
            raise RuntimeError("db unavailable")

    class _SessionOk:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(state_svc, "MetricsAggregator", _FailingAggregator)
    monkeypatch.setattr(state_svc, "AsyncSessionFactory", lambda: _SessionOk())
    store = InMemoryStore()
    store.last_health = "db_down"
    store.add_notification("db down", level="warning", notification_type="startup")
    set_runtime_store(store)
    set_db_available(False)

    payload = await dashboard_v2.get_dashboard_state()

    assert payload["mode"] == "in_memory_fallback"
    assert payload["db_health"] == "db_down"
    assert payload["notifications"]


@pytest.mark.asyncio
async def test_agents_status_active_has_non_null_last_seen_at(monkeypatch):
    class _Redis:
        async def get(self, _key):
            return '{"status":"ACTIVE","event_count":2,"last_event":"tick","last_seen":1710000000}'

    async def _get_redis():
        return _Redis()

    monkeypatch.setattr(agents_svc, "get_redis", _get_redis)
    monkeypatch.setattr(agents_svc, "is_db_available", lambda: False)
    payload = await dashboard_v2.get_agents_status()
    assert payload["agents"]
    assert all(
        a.get("last_seen_at") is not None for a in payload["agents"] if a["status"] == "ACTIVE"
    )


@pytest.mark.asyncio
async def test_agents_status_merges_db_and_heartbeat_by_agent_name(monkeypatch):
    class _Redis:
        async def get(self, _key):
            return '{"status":"ACTIVE","event_count":1,"last_event":"hb","last_seen":1710000010}'

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, *_args, **_kwargs):
            return _ResultWithFirst(
                [
                    (
                        "reasoning-agent",
                        "active",
                        None,
                        None,
                        4,
                        {"heartbeat_count": 3},
                    )
                ]
            )

    async def _get_redis():
        return _Redis()

    monkeypatch.setattr(agents_svc, "get_redis", _get_redis)
    monkeypatch.setattr(agents_svc, "is_db_available", lambda: True)
    monkeypatch.setattr(agents_svc, "AsyncSessionFactory", lambda: _Session())
    payload = await dashboard_v2.get_agents_status()
    rows = [r for r in payload["agents"] if r["name"] == "REASONING_AGENT"]
    assert len(rows) == 1
    assert rows[0]["event_count"] >= 1


class _FakeAggregator:
    def __init__(self, _session):
        pass

    async def get_raw_snapshot(self):
        return {"orders": [], "positions": [], "agent_logs": []}


@pytest.mark.asyncio
async def test_trade_feed_returns_in_memory_trades_when_db_unavailable():
    """When is_db_available() is False, /trade-feed must surface the in-memory trade_feed
    so paper fills that landed while the DB was down still appear on the dashboard."""
    set_db_available(False)
    store = InMemoryStore()
    store.upsert_trade_fill(
        {
            "id": "trace-mem-fill",
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.1,
            "entry_price": 50000.0,
            "exit_price": 50500.0,
            "pnl": 50.0,
            "order_id": "ord-mem-fill",
            "execution_trace_id": "trace-mem-fill",
            "status": "filled",
        }
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_trade_feed(limit=10)

    assert payload["count"] == 1
    assert payload["source"] == "in_memory"
    assert payload["trades"][0]["id"] == "trace-mem-fill"
    assert payload["trades"][0]["symbol"] == "BTC/USD"
    assert payload["trades"][0]["pnl"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_trade_feed_prefers_in_memory_when_db_returns_empty(monkeypatch):
    """When the DB is up but trade_lifecycle AND orders are both empty, the endpoint
    must fall back to the in-memory trade_feed — not return count=0."""
    monkeypatch.setattr(trading_svc, "is_db_available", lambda: True)
    session_rows = [[[]], [[]]]  # lifecycle empty, orders empty
    monkeypatch.setattr(
        trading_svc,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )
    store = InMemoryStore()
    store.upsert_trade_fill(
        {
            "id": "trace-bridge",
            "symbol": "ETH/USD",
            "side": "sell",
            "qty": 1.0,
            "entry_price": 3000.0,
            "exit_price": 2950.0,
            "pnl": -50.0,
            "execution_trace_id": "trace-bridge",
            "status": "filled",
        }
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_trade_feed(limit=10)

    assert payload["count"] == 1
    assert payload["source"] == "in_memory"
    assert payload["trades"][0]["id"] == "trace-bridge"


@pytest.mark.asyncio
async def test_trade_feed_db_orders_fallback_honors_session_filter(monkeypatch):
    """If lifecycle is empty and orders fallback is used, session_id filtering must still apply."""
    monkeypatch.setattr(trading_svc, "is_db_available", lambda: True)
    session_rows = [
        [[]],  # trade_lifecycle empty
        [[("ord-1", "BTC/USD", "buy", 0.1, 50000.0, "filled", "trace-1", None, None, "sess-a")]],
    ]
    monkeypatch.setattr(
        trading_svc,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    payload = await dashboard_v2.get_trade_feed(limit=10, session_id="sess-b")
    assert payload["count"] == 0
    assert payload["trades"] == []


@pytest.mark.asyncio
async def test_trade_feed_in_memory_honors_session_filter():
    """In-memory /trade-feed should apply session_id filtering just like DB mode."""
    set_db_available(False)
    store = InMemoryStore()
    store.upsert_trade_fill(
        {
            "id": "trace-a",
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.1,
            "entry_price": 50000.0,
            "pnl": None,
            "execution_trace_id": "trace-a",
            "session_id": "sess-a",
            "status": "filled",
        }
    )
    store.upsert_trade_fill(
        {
            "id": "trace-b",
            "symbol": "ETH/USD",
            "side": "sell",
            "qty": 1.0,
            "entry_price": 3000.0,
            "pnl": 25.0,
            "execution_trace_id": "trace-b",
            "session_id": "sess-b",
            "status": "filled",
        }
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_trade_feed(limit=10, session_id="sess-b")
    assert payload["source"] == "in_memory"
    assert payload["count"] == 1
    assert payload["trades"][0]["id"] == "trace-b"


@pytest.mark.asyncio
async def test_trade_feed_in_memory_filters_malformed_rows():
    """Malformed in-memory rows should be ignored instead of leaking partial payloads."""
    set_db_available(False)
    store = InMemoryStore()
    store.trade_feed.append({"debug": "noise-only"})
    store.upsert_trade_fill(
        {
            "id": "trace-good",
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.1,
            "entry_price": 50000.0,
            "execution_trace_id": "trace-good",
            "status": "filled",
        }
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_trade_feed(limit=10)
    assert payload["count"] == 1
    assert payload["trades"][0]["id"] == "trace-good"
    assert payload["trades"][0]["execution_trace_id"] == "trace-good"
    assert isinstance(payload["trades"][0]["created_at"], str)


@pytest.mark.asyncio
async def test_dashboard_state_sets_mode_even_if_redis_unavailable(monkeypatch):
    monkeypatch.setattr(state_svc, "MetricsAggregator", _FakeAggregator)

    class _SessionOk:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(state_svc, "AsyncSessionFactory", lambda: _SessionOk())

    async def _raise_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(state_svc, "get_redis", _raise_redis)
    set_db_available(False)

    payload = await dashboard_v2.get_dashboard_state()

    assert payload["mode"] == "in_memory_fallback"


# ---------------------------------------------------------------------------
# New tests: Tasks 10A–10E
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pnl_route_returns_real_data_after_buy_sell():
    """10A: /dashboard/pnl returns real data after BUY then SELL in memory mode."""
    set_db_available(False)
    store = InMemoryStore()
    store.apply_decision(
        {"action": "buy", "symbol": "BTC/USD", "price": 80000.0, "qty": 0.1, "trace_id": "t1"}
    )
    store.apply_decision(
        {"action": "sell", "symbol": "BTC/USD", "price": 81000.0, "qty": 0.1, "trace_id": "t2"}
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_pnl_metrics()

    assert payload["source"] == "in_memory"
    assert payload["total_pnl"] > 0
    assert len(payload["equity_curve"]) > 0
    assert payload["winning_trades"] > 0
    assert payload["has_data"] is True


@pytest.mark.asyncio
async def test_snapshot_returns_equity_curve_when_runtime_store_has_data():
    """10B: /dashboard/pnl equity_curve is non-empty when runtime store has BUY/SELL data."""
    set_db_available(False)
    store = InMemoryStore()
    store.apply_decision(
        {"action": "buy", "symbol": "BTC/USD", "price": 80000.0, "qty": 0.1, "trace_id": "t3"}
    )
    store.apply_decision(
        {"action": "sell", "symbol": "BTC/USD", "price": 81000.0, "qty": 0.1, "trace_id": "t4"}
    )
    set_runtime_store(store)

    pnl_payload = await dashboard_v2.get_pnl_metrics()
    perf_payload = await dashboard_v2.get_performance_trends()

    assert len(pnl_payload["equity_curve"]) > 0
    assert pnl_payload["total_pnl"] > 0
    assert perf_payload["summary"]["total_pnl"] > 0
    assert len(perf_payload["equity_curve"]) > 0


@pytest.mark.asyncio
async def test_buy_only_creates_active_position_and_equity_point():
    """10C: BUY-only creates an active open position and an equity curve entry."""
    set_db_available(False)
    store = InMemoryStore()
    store.apply_decision(
        {"action": "buy", "symbol": "BTC/USD", "price": 80000.0, "qty": 0.1, "trace_id": "t5"}
    )
    set_runtime_store(store)

    payload = await dashboard_v2.get_pnl_metrics()

    assert payload["source"] == "in_memory"
    assert payload["active_positions"] > 0
    assert len(payload["equity_curve"]) > 0


@pytest.mark.asyncio
async def test_execution_engine_db_failure_falls_back_to_memory(monkeypatch):
    """10D: ExecutionEngine falls back to _process_in_memory when DB session raises."""
    from unittest.mock import AsyncMock, MagicMock

    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.execution.brokers.paper import PaperBroker
    from api.services.execution.execution_engine import ExecutionEngine

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    mock_broker = MagicMock(spec=PaperBroker)
    mock_broker.place_order = AsyncMock(
        return_value={"broker_order_id": "b-1", "fill_price": 81000.0, "status": "filled"}
    )
    mock_broker.get_position = AsyncMock(return_value={})

    mock_bus = MagicMock(spec=EventBus)
    mock_bus.publish = AsyncMock()
    mock_dlq = MagicMock(spec=DLQManager)
    mock_dlq.push = AsyncMock()

    engine = ExecutionEngine(
        bus=mock_bus, dlq=mock_dlq, redis_client=mock_redis, broker=mock_broker
    )

    memory_called = []

    async def _spy_memory(data):
        memory_called.append(data)

    monkeypatch.setattr(engine, "_process_in_memory", _spy_memory)
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)

    class _FailAfterIdempotencySession:
        """Passes the idempotency SELECT (first execute), fails on INSERT (second execute)."""

        def __init__(self):
            self._call_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, *_, **__):
            self._call_count += 1
            if self._call_count == 1:
                # Idempotency check: no existing duplicate order
                result = MagicMock()
                result.mappings.return_value.first.return_value = None
                return result
            raise RuntimeError("simulated db failure on INSERT")

        async def rollback(self):
            pass

    monkeypatch.setattr(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        lambda: _FailAfterIdempotencySession(),
    )

    data = {
        "action": "buy",
        "symbol": "BTC/USD",
        "qty": 0.1,
        "price": 80000.0,
        "trace_id": "t-db-fail",
        "composite_score": 0.9,
        "timestamp": "2024-01-01T12:00:00+00:00",
    }
    await engine.process(data)

    assert len(memory_called) == 1, "Expected _process_in_memory to be called once"


@pytest.mark.asyncio
async def test_proposal_applier_log_failure_does_not_stop_process(monkeypatch):
    """10E: ProposalApplier continues and writes heartbeat even if write_agent_log raises."""
    from unittest.mock import AsyncMock

    from api.constants import ProposalType
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.agents.proposal_applier import ProposalApplier

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"1.0")
    mock_redis.set = AsyncMock(return_value=True)

    mock_bus = AsyncMock(spec=EventBus)
    mock_dlq = AsyncMock(spec=DLQManager)

    applier = ProposalApplier(bus=mock_bus, dlq=mock_dlq, redis_client=mock_redis)

    heartbeat_calls = []

    async def _fake_heartbeat(redis, agent_name, **kwargs):
        heartbeat_calls.append(agent_name)

    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", _fake_heartbeat)

    async def _failing_write_agent_log(*_args, **_kwargs):
        raise RuntimeError("log write failed")

    monkeypatch.setattr(
        "api.services.agents.proposal_applier.write_agent_log", _failing_write_agent_log
    )

    data = {
        "proposal_type": ProposalType.SIGNAL_WEIGHT_REDUCTION,
        "content": {"reason": "test"},
        "trace_id": "t-proposal-fail",
    }
    await applier.process(stream="proposals", redis_id="0-1", data=data)

    assert len(heartbeat_calls) == 1, "Heartbeat must fire despite log write failure"
