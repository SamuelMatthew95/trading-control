from __future__ import annotations

import pytest

from api.in_memory_store import InMemoryStore
from api.routes import dashboard_v2
from api.runtime_state import set_db_available, set_runtime_store


# Helper: enable the DB code path in tests that mock the session factory
def _enable_db(monkeypatch):
    """Patch is_db_available to True so DB-path branches execute in tests."""
    monkeypatch.setattr(dashboard_v2, "is_db_available", lambda: True)


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
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
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
    assert payload["summary"]["total_pnl"] == pytest.approx(200.0)
    assert payload["summary"]["open_positions"] == 1


class RequestStub:
    class _State:
        redis_client = None

    class _App:
        def __init__(self):
            self.state = RequestStub._State()

    def __init__(self):
        self.app = self._App()


@pytest.mark.asyncio
async def test_performance_trends_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_performance_trends()

    assert payload["summary"]["total_trades"] == 0
    assert payload["daily_pnl"] == []
    assert payload["grade_trend"] == []
    assert payload["error"] == "performance_trends_unavailable"


@pytest.mark.asyncio
async def test_agent_instances_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_agent_instances()

    assert payload["instances"] == []
    assert payload["active_count"] == 0
    assert payload["retired_count"] == 0
    assert payload["error"] == "agent_instances_unavailable"


def test_system_metrics_alias_route_exists():
    paths = {route.path for route in dashboard_v2.router.routes}
    assert "/dashboard/system-metrics" in paths


@pytest.mark.asyncio
async def test_event_history_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_event_history()

    assert payload["stream_counts"] == []
    assert payload["persisted_events"] == []
    assert payload["persisted_logs"] == []


@pytest.mark.asyncio
async def test_learning_proposals_fallbacks_to_events_when_agent_logs_empty(monkeypatch):
    # First session (agent_logs query): empty. Second session (events query): one row.
    session_rows = [
        [[]],
        [[("evt-1", {"status": "pending", "confidence": 0.71}, None)]],
    ]
    monkeypatch.setattr(
        dashboard_v2,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    payload = await dashboard_v2.get_proposals(limit=10)

    assert payload["total"] == 1
    assert payload["proposals"][0]["id"] == "evt-1"
    assert payload["proposals"][0]["content"]["confidence"] == 0.71


@pytest.mark.asyncio
async def test_learning_proposals_returns_empty_when_events_fallback_errors(monkeypatch):
    monkeypatch.setattr(
        dashboard_v2,
        "AsyncSessionFactory",
        _FactoryOneSuccessThenFail(first_rows=[]),
    )

    payload = await dashboard_v2.get_proposals(limit=10)

    assert payload["total"] == 0
    assert payload["proposals"] == []


@pytest.mark.asyncio
async def test_learning_grades_fallbacks_to_agent_grades_when_logs_empty(monkeypatch):
    _enable_db(monkeypatch)
    session_rows = [
        [[]],
        [[("trace-1", 0.84, {"fills_graded": 4}, None)]],
    ]
    monkeypatch.setattr(
        dashboard_v2,
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
    _enable_db(monkeypatch)
    session_rows = [
        [[]],
        [[("ord-1", "AAPL", "buy", 1.5, 190.0, "filled", None, None, None)]],
    ]
    monkeypatch.setattr(
        dashboard_v2,
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
    session_rows = [
        [[]],
        [[("trace-99", {"symbol": "TSLA", "status": "pending"}, None)]],
    ]
    monkeypatch.setattr(
        dashboard_v2,
        "AsyncSessionFactory",
        _FactoryWithQueuedSessions(session_rows),
    )

    payload = await dashboard_v2.list_proposals()

    assert len(payload["proposals"]) == 1
    assert payload["proposals"][0]["id"] == "trace-99"
    assert payload["proposals"][0]["source"] == "agent_logs"


@pytest.mark.asyncio
async def test_learning_endpoints_accept_stringified_payloads(monkeypatch):
    _enable_db(monkeypatch)
    session_rows = [
        [[("trace-prop", '{"status":"approved","content":{"k":"v"}}', None)]],
        [[("trace-grade", '{"grade":"A","score":0.92,"metrics":{"fills_graded":3}}', None)]],
    ]
    monkeypatch.setattr(
        dashboard_v2,
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

    monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FailingAggregator)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: _SessionOk())
    store = InMemoryStore()
    store.last_health = "db_down"
    store.add_notification("db down", level="warning", notification_type="startup")
    set_runtime_store(store)
    set_db_available(False)

    payload = await dashboard_v2.get_dashboard_state()

    assert payload["mode"] == "in_memory_fallback"
    assert payload["db_health"] == "db_down"
    assert payload["notifications"]


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
    _enable_db(monkeypatch)
    session_rows = [[[]], [[]]]  # lifecycle empty, orders empty
    monkeypatch.setattr(
        dashboard_v2,
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
async def test_dashboard_state_sets_mode_even_if_redis_unavailable(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FakeAggregator)

    class _SessionOk:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: _SessionOk())

    async def _raise_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(dashboard_v2, "get_redis", _raise_redis)
    set_db_available(False)

    payload = await dashboard_v2.get_dashboard_state()

    assert payload["mode"] == "in_memory_fallback"
