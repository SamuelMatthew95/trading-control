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


def test_seeded_agents_never_appear_live_without_heartbeat():
    """Regression: a DEFAULT_AGENTS entry that has never written a heartbeat must
    NOT be stamped with the current time (which painted never-started agents
    'Live'). It reports last_seen=0 and seconds_ago=-1 so the dashboard ages it
    out to Idle/offline."""
    import time

    from api.constants import AGENT_SIGNAL, ALL_AGENT_NAMES

    store = InMemoryStore()
    snapshot = store.dashboard_fallback_snapshot()
    statuses = {s["name"]: s for s in snapshot["agent_statuses"]}

    # Every seeded-but-idle agent reports the sentinels, never a fresh timestamp.
    now = time.time()
    for name in ALL_AGENT_NAMES:
        row = statuses[name]
        assert row["last_seen"] == 0.0, f"{name} fabricated a last_seen"
        assert row["seconds_ago"] == -1, f"{name} looks freshly seen"
        assert now - row["last_seen"] > 60  # would age out to Idle/offline

    # An agent that DID heartbeat keeps a real, recent timestamp.
    store.upsert_agent(AGENT_SIGNAL, {"status": "ACTIVE", "last_seen": now, "event_count": 3})
    refreshed = {s["name"]: s for s in store.dashboard_fallback_snapshot()["agent_statuses"]}
    assert refreshed[AGENT_SIGNAL]["last_seen"] == now
    assert refreshed[AGENT_SIGNAL]["seconds_ago"] >= 0


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


def test_has_open_quantity_true_for_nonzero():
    assert InMemoryStore._has_open_quantity({"qty": 0.5}) is True
    assert InMemoryStore._has_open_quantity({"qty": -0.1}) is True


def test_has_open_quantity_false_for_zero():
    assert InMemoryStore._has_open_quantity({"qty": 0}) is False
    assert InMemoryStore._has_open_quantity({"qty": 0.0}) is False
    assert InMemoryStore._has_open_quantity({}) is False


def test_normalize_position_maps_qty_and_current_price():
    store = InMemoryStore()
    raw = {"symbol": "BTC/USD", "qty": 0.5, "last_price": 50000.0, "unrealized_pnl": 250.0}
    out = store._normalize_position(raw)
    assert out["quantity"] == 0.5
    assert out["current_price"] == 50000.0
    assert out["pnl"] == 250.0
    assert out["symbol"] == "BTC/USD"


def test_normalize_position_prefers_current_price_over_last_price():
    store = InMemoryStore()
    raw = {"qty": 1.0, "current_price": 60000.0, "last_price": 55000.0}
    out = store._normalize_position(raw)
    assert out["current_price"] == 60000.0


def test_normalize_position_falls_back_to_price_field():
    store = InMemoryStore()
    raw = {"qty": 1.0, "price": 45000.0}
    out = store._normalize_position(raw)
    assert out["current_price"] == 45000.0


def test_normalize_position_prefers_unrealized_pnl_over_pnl():
    store = InMemoryStore()
    raw = {"qty": 1.0, "unrealized_pnl": 100.0, "pnl": 999.0}
    out = store._normalize_position(raw)
    assert out["pnl"] == 100.0


def test_decision_dedup_keys_are_bounded():
    """Regression: applied_decision_keys grew one key per decision forever —
    the only unbounded collection in a store whose whole point is long runs."""
    from api.in_memory_store import DECISION_KEY_CAP, InMemoryStore

    store = InMemoryStore()
    for i in range(DECISION_KEY_CAP + 200):
        store.record_decision({"id": f"dec-{i}", "symbol": "BTC/USD", "action": "hold"})

    assert len(store.applied_decision_keys) <= DECISION_KEY_CAP
    assert len(store.decision_key_order) <= DECISION_KEY_CAP
    # The newest keys are retained — re-delivering the latest decision still dedups.
    last = store.record_decision(
        {"id": f"dec-{DECISION_KEY_CAP + 199}", "symbol": "BTC/USD", "action": "hold"}
    )
    assert last.get("deduplicated") is True
