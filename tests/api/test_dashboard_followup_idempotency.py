from api.in_memory_store import InMemoryStore
from api.routes import dashboard_v2
from api.runtime_state import set_db_available, set_runtime_store
from api.services.redis_store import RedisStore, get_redis_store, set_redis_store


async def _with_redis_store(fake_redis):
    previous = get_redis_store()
    store = RedisStore(fake_redis)
    set_redis_store(store)
    return store, previous


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


async def test_dashboard_hydrates_from_redis_decisions_when_db_unavailable(fake_redis) -> None:
    store, previous = await _with_redis_store(fake_redis)
    try:
        set_runtime_store(InMemoryStore())
        set_db_available(False)
        await store.push_decision(
            {"id": "d-1", "action": "buy", "symbol": "BTC/USD", "price": 80000.0, "trace_id": "t-1"}
        )
        await store.push_notification({"id": "n-1", "title": "BUY BTC/USD executed"})

        snap = await dashboard_v2.get_dashboard_snapshot()
        state = await dashboard_v2.get_dashboard_state()

        assert snap["has_data"] is True
        assert len(snap["decisions"]) > 0
        assert len(snap["positions"]) == 0
        assert snap["equity_curve"] == []
        assert state["has_data"] is True
        assert snap["source"] == "redis_hydrated"
        assert state["source"] == "redis_hydrated"
        assert snap["ledger_source"] == "runtime_store"
        assert state["ledger_source"] == "runtime_store"
        assert snap["persistence_source"] == "redis"
        assert state["persistence_source"] == "redis"
        assert snap["hydration"]["status"] == "completed"
        assert state["hydration"]["status"] == "completed"
        assert snap["hydration"]["applied_decision_keys"] >= 1
        assert state["hydration"]["applied_decision_keys"] >= 1
    finally:
        set_redis_store(previous)


async def test_dashboard_hydration_is_idempotent_across_repeated_reads(fake_redis) -> None:
    store, previous = await _with_redis_store(fake_redis)
    try:
        set_runtime_store(InMemoryStore())
        set_db_available(False)
        await store.push_decision(
            {
                "id": "buy-1",
                "action": "buy",
                "symbol": "BTC/USD",
                "price": 80000.0,
                "trace_id": "buy-t",
            }
        )
        await store.push_decision(
            {
                "id": "sell-1",
                "action": "sell",
                "symbol": "BTC/USD",
                "price": 81000.0,
                "trace_id": "sell-t",
            }
        )
        await store.push_notification({"id": "n-buy", "title": "BUY BTC/USD"})
        await store.push_notification({"id": "n-sell", "title": "SELL BTC/USD"})

        first = await dashboard_v2.get_dashboard_debug_state()
        second = await dashboard_v2.get_dashboard_debug_state()

        assert first["counts"]["redis_hydration_status"] == "completed"
        assert first["ledger_source"] == "runtime_store"
        assert first["persistence_source"] == "redis"
        assert first["counts"]["decisions"] == second["counts"]["decisions"] == 2
        assert first["counts"]["notifications"] == second["counts"]["notifications"] == 2
        assert first["counts"]["closed_trades"] == second["counts"]["closed_trades"] == 0
        assert first["counts"]["open_positions"] == second["counts"]["open_positions"] == 0
        assert first["counts"]["redis_decisions_applied"] == 2
        assert second["counts"]["redis_decisions_applied"] == 0
        assert first["summary"]["realized_pnl"] == 0
        assert second["summary"]["realized_pnl"] == 0
        assert first["source"] == "redis_hydrated"
    finally:
        set_redis_store(previous)


async def test_debug_route_available_under_dashboard_and_api_prefix(api_client) -> None:
    headers = {"host": "localhost"}
    r1 = await api_client.get("/dashboard/debug/state", headers=headers)
    r2 = await api_client.get("/api/dashboard/debug/state", headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    body1 = r1.json()
    body2 = r2.json()
    assert "source" in body1
    assert "counts" in body1
    assert "db_available" in body1
    assert "source" in body2
    assert "counts" in body2
    assert "db_available" in body2


async def test_debug_route_is_explicitly_runtime_store_scoped() -> None:
    set_db_available(True)
    payload = await dashboard_v2.get_dashboard_debug_state()
    assert payload["db_available"] is True
    assert payload["source"] == "in_memory"
    assert payload["scope"] == "runtime_store"


async def test_debug_state_closed_trades_uses_paired_orders_in_memory_path() -> None:
    store = InMemoryStore()
    store.add_order(
        {
            "id": "ord-1",
            "symbol": "BTC/USD",
            "side": "sell",
            "qty": 0.1,
            "price": 81000.0,
            "pnl": 100.0,
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    payload = await dashboard_v2.get_dashboard_debug_state()

    assert payload["source"] == "in_memory"
    assert payload["counts"]["closed_trades"] == 1
    assert payload["summary"]["closed_trades"] == 1
    assert payload["latest_closed_trade"]["id"] == "ord-1"


async def test_debug_state_closed_trade_count_matches_summary_for_breakeven_orders() -> None:
    store = InMemoryStore()
    store.add_order(
        {
            "id": "ord-0",
            "symbol": "ETH/USD",
            "side": "sell",
            "qty": 1.0,
            "price": 3000.0,
            "pnl": 0.0,
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    payload = await dashboard_v2.get_dashboard_debug_state()

    assert payload["counts"]["closed_trades"] == payload["summary"]["closed_trades"] == 0
    assert payload["latest_closed_trade"]["id"] == "ord-0"


def test_record_decision_is_advisory_only_no_portfolio_mutation() -> None:
    store = InMemoryStore()
    store.record_decision({"id": "adv-1", "action": "buy", "symbol": "BTC/USD", "price": 80000.0})
    assert len(store.decisions) == 1
    assert store.open_positions() == []
    assert store.orders == []
    assert store.closed_trades == []
    assert store.equity_curve == []
