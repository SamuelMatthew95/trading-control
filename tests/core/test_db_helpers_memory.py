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


async def test_upsert_trade_lifecycle_memory_mode_populates_trade_feed():
    """In memory mode, upsert_trade_lifecycle also writes to trade_feed so the dashboard
    Trade Feed panel surfaces the fill — previously memory-mode fills were invisible."""
    await upsert_trade_lifecycle(
        execution_trace_id="trace-tf-1",
        symbol="AAPL",
        side="buy",
        qty=2.0,
        entry_price=190.0,
        exit_price=195.0,
        pnl=10.0,
        pnl_percent=2.63,
        order_id="ord-tf-1",
        status="filled",
        grade="A",
        grade_score=0.9,
    )

    feed = get_runtime_store().trade_feed
    assert len(feed) == 1
    row = feed[0]
    assert row["id"] == "trace-tf-1"
    assert row["symbol"] == "AAPL"
    assert row["side"] == "buy"
    assert row["qty"] == pytest.approx(2.0)
    assert row["entry_price"] == pytest.approx(190.0)
    assert row["exit_price"] == pytest.approx(195.0)
    assert row["pnl"] == pytest.approx(10.0)
    assert row["grade"] == "A"
    assert row["status"] == "filled"
    assert row["order_id"] == "ord-tf-1"
    assert row["execution_trace_id"] == "trace-tf-1"


async def test_upsert_trade_lifecycle_memory_mode_dedups_on_execution_trace_id():
    """Second call with the same execution_trace_id must merge into the same trade_feed row,
    not create a duplicate — so grade/reflection updates don't spawn phantom fills."""
    await upsert_trade_lifecycle(
        execution_trace_id="trace-dup",
        symbol="BTC/USD",
        side="buy",
        qty=0.1,
        entry_price=50000.0,
        exit_price=50000.0,
        order_id="ord-dup",
        status="filled",
    )
    await upsert_trade_lifecycle(
        execution_trace_id="trace-dup",
        symbol="BTC/USD",
        side="buy",
        grade="B",
        grade_score=0.75,
        status="graded",
    )

    feed = get_runtime_store().trade_feed
    assert len(feed) == 1
    row = feed[0]
    assert row["grade"] == "B"
    assert row["grade_score"] == pytest.approx(0.75)
    # The original fill data must still be present (merge not overwrite)
    assert row["entry_price"] == pytest.approx(50000.0)
    assert row["qty"] == pytest.approx(0.1)
    # Grade/update upserts must not create a random extra order row.
    assert len(get_runtime_store().orders) == 1


async def test_upsert_trade_lifecycle_memory_mode_preserves_null_pnl_and_session():
    """Opening fills should keep pnl/pnl_percent as None and carry session_id."""
    await upsert_trade_lifecycle(
        execution_trace_id="trace-open",
        symbol="BTC/USD",
        side="buy",
        qty=0.2,
        entry_price=50000.0,
        exit_price=None,
        pnl=None,
        pnl_percent=None,
        order_id="ord-open",
        status="filled",
        session_id="sess-123",
    )

    order = get_runtime_store().orders[0]
    assert order["pnl"] is None
    assert order["pnl_percent"] is None
    assert order["session_id"] == "sess-123"

    row = get_runtime_store().trade_feed[0]
    assert row["pnl"] is None
    assert row["pnl_percent"] is None
    assert row["session_id"] == "sess-123"


async def test_upsert_trade_lifecycle_memory_mode_normalizes_status_case():
    """Memory rows should treat FILLED/filled consistently for downstream consumers."""
    await upsert_trade_lifecycle(
        execution_trace_id="trace-case",
        symbol="ETH/USD",
        side="sell",
        qty=1.0,
        entry_price=3000.0,
        exit_price=3025.0,
        order_id="ord-case",
        status="FILLED",
    )

    order = get_runtime_store().orders[0]
    row = get_runtime_store().trade_feed[0]
    assert order["status"] == "filled"
    assert row["status"] == "filled"


async def test_write_agent_log_memory_mode_populates_agent_logs():
    """write_agent_log in memory mode must also push a row onto agent_logs so the
    dashboard Agent Thought Stream surfaces reasoning/grade/reflection activity."""
    from api.constants import LogType
    from api.services.agents.db_helpers import write_agent_log

    await write_agent_log(
        "trace-log-1",
        LogType.REASONING_SUMMARY,
        {
            "message": "Bullish momentum detected",
            "source": "REASONING_AGENT",
            "confidence": 0.82,
        },
    )

    logs = get_runtime_store().agent_logs
    assert len(logs) == 1
    log = logs[0]
    assert log["trace_id"] == "trace-log-1"
    assert log["message"] == "Bullish momentum detected"
    assert log["agent_name"] == "REASONING_AGENT"
    assert log["confidence"] == pytest.approx(0.82)
    assert log["log_type"] == LogType.REASONING_SUMMARY
