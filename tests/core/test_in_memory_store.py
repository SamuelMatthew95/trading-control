"""Tests for InMemoryStore — orders, positions, and dashboard_fallback_snapshot."""

from __future__ import annotations

from api.in_memory_store import InMemoryStore


def test_add_order_appends_and_returns_payload():
    store = InMemoryStore()
    order = {"order_id": "o1", "symbol": "BTC/USD", "side": "buy", "qty": 0.1}
    result = store.add_order(order)
    assert len(store.orders) == 1
    assert result["order_id"] == "o1"
    assert result["symbol"] == "BTC/USD"
    # created_at is added automatically
    assert "created_at" in result


def test_add_order_truncates_at_500():
    store = InMemoryStore()
    for i in range(600):
        store.add_order({"order_id": str(i), "symbol": "BTC/USD"})
    assert len(store.orders) == 500
    # Should keep the newest 500
    assert store.orders[-1]["order_id"] == "599"


def test_upsert_position_creates_new():
    store = InMemoryStore()
    store.upsert_position("BTC/USD", {"symbol": "BTC/USD", "qty": 0.5, "side": "long"})
    assert "BTC/USD" in store.positions
    assert store.positions["BTC/USD"]["qty"] == 0.5
    assert store.positions["BTC/USD"]["side"] == "long"


def test_upsert_position_merges_with_existing():
    store = InMemoryStore()
    store.upsert_position(
        "BTC/USD", {"symbol": "BTC/USD", "qty": 0.5, "side": "long", "entry_price": 50000.0}
    )
    # Update only qty
    store.upsert_position("BTC/USD", {"qty": 1.0, "current_price": 55000.0})
    pos = store.positions["BTC/USD"]
    assert pos["qty"] == 1.0
    assert pos["current_price"] == 55000.0
    # Original fields preserved
    assert pos["entry_price"] == 50000.0
    assert pos["side"] == "long"


def test_dashboard_fallback_snapshot_includes_orders():
    store = InMemoryStore()
    store.add_order({"order_id": "o1", "symbol": "BTC/USD", "side": "buy", "qty": 0.1})
    snapshot = store.dashboard_fallback_snapshot()
    assert len(snapshot["orders"]) == 1
    assert snapshot["orders"][0]["order_id"] == "o1"


def test_dashboard_fallback_snapshot_excludes_flat_positions():
    """Positions with qty=0 must NOT appear in the snapshot."""
    store = InMemoryStore()
    store.upsert_position("BTC/USD", {"symbol": "BTC/USD", "qty": 0, "side": "flat"})
    store.upsert_position("ETH/USD", {"symbol": "ETH/USD", "qty": 0.0, "side": "flat"})
    snapshot = store.dashboard_fallback_snapshot()
    assert snapshot["positions"] == [], (
        "Flat positions (qty=0) should be excluded from dashboard snapshot"
    )


def test_dashboard_fallback_snapshot_includes_active_positions():
    """Positions with qty>0 must appear in the snapshot."""
    store = InMemoryStore()
    store.upsert_position("BTC/USD", {"symbol": "BTC/USD", "qty": 0.5, "side": "long"})
    store.upsert_position("ETH/USD", {"symbol": "ETH/USD", "qty": 0.0, "side": "flat"})
    snapshot = store.dashboard_fallback_snapshot()
    symbols = [p["symbol"] for p in snapshot["positions"]]
    assert "BTC/USD" in symbols
    assert "ETH/USD" not in symbols
