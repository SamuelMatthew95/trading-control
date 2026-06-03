from api.in_memory_store import InMemoryStore
from tests.helpers.ledger import apply_decision


def test_buy_sell_updates_ledger_and_pnl():
    store = InMemoryStore()
    apply_decision(
        store, {"action": "buy", "symbol": "BTC/USD", "price": 80000.0, "trace_id": "t1"}
    )
    assert store.open_positions()
    apply_decision(
        store, {"action": "sell", "symbol": "BTC/USD", "price": 81000.0, "trace_id": "t2"}
    )
    summary = store.paired_pnl_payload()["summary"]
    assert summary["realized_pnl"] > 0
    assert summary["open_positions"] == 0
    assert summary["closed_trades"] == 1
    assert summary["total_pnl"] > 0
    assert len(store.equity_curve) >= 2


def test_action_normalization_and_notifications_shape():
    store = InMemoryStore()
    event = apply_decision(
        store, {"action": "Buy", "symbol": "AAPL", "price": 300.0, "trace_id": "t3"}
    )
    assert event["action"] == "BUY"
    assert event["qty"] > 0


def test_sell_without_open_position_does_not_create_closed_trade() -> None:
    store = InMemoryStore()
    apply_decision(
        store, {"action": "sell", "symbol": "BTC/USD", "price": 81000.0, "trace_id": "t4"}
    )
    assert store.closed_trades == []
    assert store.orders == []


def test_buy_sell_missing_qty_can_close_at_loss() -> None:
    store = InMemoryStore()
    apply_decision(
        store, {"action": "buy", "symbol": "BTC/USD", "price": 81000.0, "trace_id": "t5"}
    )
    apply_decision(
        store, {"action": "sell", "symbol": "BTC/USD", "price": 80000.0, "trace_id": "t6"}
    )
    summary = store.paired_pnl_payload()["summary"]
    assert summary["open_positions"] == 0
    assert summary["closed_trades"] == 1
    assert summary["realized_pnl"] < 0


def test_partial_sell_with_explicit_qty_leaves_open_position() -> None:
    store = InMemoryStore()
    buy = apply_decision(
        store, {"action": "buy", "symbol": "AAPL", "price": 100.0, "trace_id": "t7"}
    )
    buy_qty = float(buy["qty"])
    apply_decision(
        store,
        {"action": "sell", "symbol": "AAPL", "price": 101.0, "qty": buy_qty / 2, "trace_id": "t8"},
    )
    summary = store.paired_pnl_payload()["summary"]
    assert summary["open_positions"] == 1
    assert summary["closed_trades"] == 1
    remaining = float(store.positions["AAPL"]["qty"])
    assert remaining == buy_qty / 2
