from api.in_memory_store import InMemoryStore
from api.runtime_state import set_runtime_store
from api.services.dashboard_read_service import DashboardReadService


def test_runtime_positions_portfolio_notifications_and_agent_runs_payloads():
    store = InMemoryStore()
    store.upsert_position("BTC/USD", {"symbol": "BTC/USD", "side": "long", "qty": 1})
    store.add_order({"id": "o1", "pnl": 3})
    store.add_agent_run({"run_id": "r1"})
    store.record_notification({"id": "n1", "message": "m"})
    set_runtime_store(store)

    svc = DashboardReadService()
    positions = svc.runtime_positions_payload()
    portfolio = svc.runtime_portfolio_payload()
    runs = svc.runtime_agent_runs_payload()
    notes = svc.runtime_notifications_payload()

    assert positions["count"] == 1
    assert "portfolio" in portfolio
    assert runs["count"] == 1
    assert notes["count"] == 1


def test_runtime_and_empty_paired_pnl_payloads():
    svc = DashboardReadService()
    runtime_payload = svc.runtime_paired_pnl_payload()
    empty_payload = svc.empty_paired_pnl_payload()
    assert "summary" in runtime_payload
    assert empty_payload["summary"]["total_pnl"] == 0.0


def test_runtime_and_empty_recent_events_payloads():
    svc = DashboardReadService()
    runtime_payload = svc.runtime_recent_events_payload()
    empty_payload = svc.empty_recent_events_payload()
    assert "events" in runtime_payload
    assert empty_payload["events"] == []


def test_runtime_and_empty_stage2_payloads():
    svc = DashboardReadService()
    history = svc.runtime_event_history_payload(limit=10)
    trace = svc.runtime_trace_payload(trace_id="missing")
    perf = svc.empty_performance_trends_payload()
    instances = svc.empty_agent_instances_payload()
    assert "persisted_events" in history
    assert trace["trace_id"] == "missing"
    assert perf["summary"]["total_trades"] == 0
    assert instances["instances"] == []


def test_runtime_and_empty_stage3_payloads():
    svc = DashboardReadService()
    stream_lag = svc.runtime_stream_lag_payload()
    flow_status = svc.runtime_flow_status_payload()
    challengers = svc.empty_challengers_payload()
    assert "stream_lag" in stream_lag
    assert "counts" in flow_status
    assert challengers["challengers"] == []
