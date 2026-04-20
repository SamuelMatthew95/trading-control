"""Tests for db_helpers — upsert_trade_lifecycle in memory mode."""

from __future__ import annotations

import pytest

from api.runtime_state import get_runtime_store
from api.services.agents.db_helpers import upsert_trade_lifecycle

pytestmark = pytest.mark.asyncio

# The autouse _reset_runtime_state fixture in tests/conftest.py resets the store
# and sets is_db_available=False before each test. These tests rely on that.


async def test_upsert_trade_lifecycle_memory_mode_writes_order():
    """In memory mode, upsert_trade_lifecycle writes a compact order record to InMemoryStore."""
    # Confirm db is unavailable (set by autouse fixture)
    assert not __import__("api.runtime_state", fromlist=["is_db_available"]).is_db_available()

    await upsert_trade_lifecycle(
        execution_trace_id="t1",
        symbol="BTC/USD",
        side="sell",
        qty=0.1,
        entry_price=50000.0,
        exit_price=55000.0,
        pnl=500.0,
        pnl_percent=10.0,
        order_id="o1",
        status="filled",
    )

    orders = get_runtime_store().orders
    assert len(orders) == 1

    order = orders[0]
    assert order["symbol"] == "BTC/USD"
    assert order["side"] == "sell"
    assert order["qty"] == pytest.approx(0.1)
    assert order["pnl"] == pytest.approx(500.0)
    assert order["pnl_percent"] == pytest.approx(10.0)
    assert order["status"] == "filled"
    assert order["order_id"] == "o1"


async def test_upsert_trade_lifecycle_db_mode_no_op_without_db(monkeypatch):
    """When is_db_available=True but no real DB, the function must not raise."""
    monkeypatch.setattr("api.services.agents.db_helpers.is_db_available", lambda: True)

    # Should not raise — it catches the DB exception and logs a warning
    await upsert_trade_lifecycle(
        execution_trace_id="t2",
        symbol="ETH/USD",
        side="buy",
        qty=0.5,
        entry_price=3000.0,
        exit_price=3100.0,
        pnl=50.0,
        pnl_percent=1.67,
        order_id="o2",
        status="filled",
    )
    # No assertion needed beyond "did not raise"
