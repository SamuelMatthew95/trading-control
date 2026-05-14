from api.in_memory_store import InMemoryStore


def test_buy_sell_updates_ledger_and_pnl():
    store = InMemoryStore()
    store.apply_decision({"action": "buy", "symbol": "BTC/USD", "price": 80000.0, "trace_id": "t1"})
    assert store.open_positions()
    store.apply_decision(
        {"action": "sell", "symbol": "BTC/USD", "price": 81000.0, "trace_id": "t2"}
    )
    summary = store.paired_pnl_payload()["summary"]
    assert summary["realized_pnl"] > 0
    assert summary["open_positions"] == 0
    assert len(store.equity_curve) >= 2


def test_action_normalization_and_notifications_shape():
    store = InMemoryStore()
    event = store.apply_decision(
        {"action": "Buy", "symbol": "AAPL", "price": 300.0, "trace_id": "t3"}
    )
    assert event["action"] == "BUY"
    assert event["qty"] > 0
