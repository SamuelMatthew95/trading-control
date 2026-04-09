from __future__ import annotations

import pytest

from api.routes import dashboard_v2


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
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_trade_feed()

    assert payload["count"] == 0
    assert payload["trades"] == []
    assert payload["error"] == "trade_feed_unavailable"


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
    assert payload["grades"][0]["score"] == 84.0
    assert payload["grades"][0]["score_pct"] == 84.0
    assert payload["grades"][0]["fills_graded"] == 4


@pytest.mark.asyncio
async def test_trade_feed_fallbacks_to_orders_when_lifecycle_empty(monkeypatch):
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
