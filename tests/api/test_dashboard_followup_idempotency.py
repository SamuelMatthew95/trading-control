from api.in_memory_store import InMemoryStore
from api.routes import dashboard_v2
from api.runtime_state import set_db_available, set_runtime_store


def _seed(store: InMemoryStore) -> None:
    store.apply_decision(
        {"id": "d-1", "action": "buy", "symbol": "BTC/USD", "price": 80000.0, "trace_id": "t-1"}
    )
    store.apply_decision(
        {"id": "d-2", "action": "sell", "symbol": "BTC/USD", "price": 81000.0, "trace_id": "t-2"}
    )


def test_apply_decision_idempotent_duplicate_does_not_double_count() -> None:
    store = InMemoryStore()
    payload = {
        "id": "dup-1",
        "action": "buy",
        "symbol": "AAPL",
        "price": 300.0,
        "trace_id": "trace-dup",
    }
    store.apply_decision(payload)
    first = store.paired_pnl_payload()["summary"]
    store.apply_decision(payload)
    second = store.paired_pnl_payload()["summary"]
    assert len(store.decisions) == 1
    assert len(store.equity_curve) == 1
    assert first == second


async def test_snapshot_and_state_reads_are_stable_and_in_memory() -> None:
    store = InMemoryStore()
    _seed(store)
    set_runtime_store(store)
    set_db_available(False)

    snap1 = await dashboard_v2.get_dashboard_snapshot()
    snap2 = await dashboard_v2.get_dashboard_snapshot()
    state1 = await dashboard_v2.get_dashboard_state()
    state2 = await dashboard_v2.get_dashboard_state()

    assert snap1["source"] == "in_memory"
    assert snap2["source"] == "in_memory"
    assert state1["source"] == "in_memory"
    assert state2["source"] == "in_memory"
    assert snap1["has_data"] is True
    assert state1["has_data"] is True
    assert len(snap1["notifications"]) == len(snap2["notifications"])
    assert len(snap1["equity_curve"]) == len(snap2["equity_curve"])
    assert snap1["equity_curve"] == snap2["equity_curve"]


async def test_debug_route_available_under_dashboard_and_api_prefix(api_client) -> None:
    r1 = await api_client.get("/dashboard/debug/state")
    r2 = await api_client.get("/api/dashboard/debug/state")
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_record_decision_is_advisory_only_no_portfolio_mutation() -> None:
    store = InMemoryStore()
    store.record_decision({"id": "adv-1", "action": "buy", "symbol": "BTC/USD", "price": 80000.0})
    assert len(store.decisions) == 1
    assert store.open_positions() == []
    assert store.orders == []
    assert store.closed_trades == []
    assert store.equity_curve == []
