"""Trade lifecycle guardrail tests.

Verifies that the execution engine enforces strict BUY-before-SELL ordering:
  SIGNAL → BUY → OPEN POSITION → SELL → CLOSED POSITION → REALIZED P&L

Key invariants under test:
1. SELL with no open BUY is rejected (no P&L, no fill).
2. BUY → SELL closes the position and calculates realized P&L correctly.
3. Duplicate SELL does not double-close or double-count P&L.
4. Duplicate BUY does not create duplicate open positions.
5. SELL quantity > open quantity is clamped to available qty.
6. In-memory mode follows the same rules as DB mode.
7. Dashboard P&L does not count rejected/unmatched SELLs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.constants import STREAM_SELL_REJECTED, FieldName, PositionSide
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.runtime_state import set_runtime_store
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(
    side: str = "buy",
    symbol: str = "BTC/USD",
    qty: float = 1.0,
    price: float = 50_000.0,
    strategy_id: str = "strat-1",
    trace_id: str = "trace-001",
) -> dict:
    return {
        FieldName.STRATEGY_ID: strategy_id,
        FieldName.SYMBOL: symbol,
        FieldName.SIDE: side,
        FieldName.QTY: qty,
        FieldName.PRICE: price,
        FieldName.TIMESTAMP: "2024-01-01T12:00:00+00:00",
        FieldName.TRACE_ID: trace_id,
        "composite_score": 0.75,
        "signal_type": "MOMENTUM",
    }


def _flat_position() -> dict:
    return {}


def _long_position(qty: float = 1.0, entry_price: float = 50_000.0) -> dict:
    return {
        FieldName.SIDE: PositionSide.LONG,
        FieldName.QTY: qty,
        FieldName.ENTRY_PRICE: entry_price,
    }


class _MockAsyncSession:
    def __init__(self, existing_row=None, first_row=("rejected-order-uuid-001",)):
        self._existing_row = existing_row
        self._result = MagicMock()
        self._result.scalar_one.return_value = "order-uuid-123"
        self._result.scalar.return_value = "order-uuid-123"
        self._result.mappings.return_value.first.return_value = existing_row
        # Used by insert_rejected_order_once / insert_pending_order RETURNING id
        self._result.first.return_value = first_row

    async def execute(self, *args, **kwargs):
        return self._result

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _MockSessionFactory:
    def __init__(self, existing_row=None, first_row=("rejected-order-uuid-001",)):
        self._existing_row = existing_row
        self._first_row = first_row

    def __call__(self):
        return self

    async def __aenter__(self):
        return _MockAsyncSession(existing_row=self._existing_row, first_row=self._first_row)

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


@pytest.fixture
def mock_dlq():
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def mock_broker():
    broker = MagicMock(spec=PaperBroker)
    broker.place_order = AsyncMock(
        return_value={
            FieldName.BROKER_ORDER_ID: "broker-123",
            FieldName.FILL_PRICE: 50_001.0,
            FieldName.STATUS: "filled",
        }
    )
    broker.get_position = AsyncMock(return_value=_flat_position())
    return broker


@pytest.fixture
def engine_db(mock_bus, mock_dlq, mock_redis, mock_broker, monkeypatch):
    """ExecutionEngine with DB path forced on."""
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)
    return ExecutionEngine(bus=mock_bus, dlq=mock_dlq, redis_client=mock_redis, broker=mock_broker)


@pytest.fixture
def engine_mem(mock_bus, mock_dlq, mock_redis, mock_broker, monkeypatch):
    """ExecutionEngine with in-memory path forced on."""
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)
    store = InMemoryStore()
    set_runtime_store(store)
    return ExecutionEngine(bus=mock_bus, dlq=mock_dlq, redis_client=mock_redis, broker=mock_broker)


# ---------------------------------------------------------------------------
# 1. SELL with no open BUY is rejected — DB path
# ---------------------------------------------------------------------------


async def test_db_sell_rejected_when_no_open_position(engine_db, mock_bus, mock_broker):
    """SELL with a flat prior position must not call broker and must publish a rejection."""
    mock_broker.get_position.return_value = _flat_position()

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine_db.process(_make_decision(side="sell"))

    mock_broker.place_order.assert_not_called()

    # A sell_rejected event must be published; no fill event.
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert STREAM_SELL_REJECTED in published_streams
    assert "executions" not in published_streams


async def test_db_sell_rejected_event_payload(engine_db, mock_bus, mock_broker):
    """Rejection event payload carries required fields including durable order_id."""
    mock_broker.get_position.return_value = _flat_position()

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine_db.process(_make_decision(side="sell", symbol="ETH/USD", trace_id="t-99"))

    rejection_calls = [
        c for c in mock_bus.publish.call_args_list if c.args[0] == STREAM_SELL_REJECTED
    ]
    assert len(rejection_calls) == 1
    payload = rejection_calls[0].args[1]
    assert payload[FieldName.REJECTION_REASON] == "NO_OPEN_POSITION"
    assert payload[FieldName.SYMBOL] == "ETH/USD"
    assert payload[FieldName.SIDE] == "sell"
    assert payload[FieldName.TRACE_ID] == "t-99"
    # Durable identifiers — added for at-least-once idempotency
    assert FieldName.ORDER_ID in payload
    assert FieldName.IDEMPOTENCY_KEY in payload


async def test_db_duplicate_rejected_sell_is_no_op(engine_db, mock_bus, mock_broker):
    """Replayed SELL rejection (same idempotency_key) must not publish a second event.

    Simulates the at-least-once redelivery case: the first invocation persisted
    a REJECTED order row; on replay the early dedup check finds it and returns
    without publishing another sell_rejected event.
    """
    existing = {"id": "rejected-order-1", "status": "rejected", "idempotency_key": "k"}
    mock_broker.get_position.return_value = _flat_position()

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(existing_row=existing),
    ):
        await engine_db.process(_make_decision(side="sell"))

    mock_broker.place_order.assert_not_called()
    mock_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# 2. BUY → SELL closes position with correct P&L — DB path
# ---------------------------------------------------------------------------


async def test_db_sell_accepted_when_long_position_exists(engine_db, mock_bus, mock_broker):
    """SELL with an open LONG position must reach the broker and publish fill events."""
    mock_broker.get_position.return_value = _long_position(qty=1.0, entry_price=48_000.0)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-sell-1",
        FieldName.FILL_PRICE: 52_000.0,
        FieldName.STATUS: "filled",
    }

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine_db.process(_make_decision(side="sell", qty=1.0, trace_id="t-sell-1"))

    mock_broker.place_order.assert_called_once()

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "executions" in published_streams
    assert STREAM_SELL_REJECTED not in published_streams


async def test_db_pnl_computed_from_matched_buy(engine_db, mock_bus, mock_broker):
    """Realized P&L must use the entry_price from the matched BUY position."""
    entry = 48_000.0
    exit_p = 52_000.0
    qty = 1.0
    expected_pnl = (exit_p - entry) * qty  # 4000.0

    mock_broker.get_position.return_value = _long_position(qty=qty, entry_price=entry)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-pnl",
        FieldName.FILL_PRICE: exit_p,
        FieldName.STATUS: "filled",
    }

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine_db.process(_make_decision(side="sell", qty=qty, trace_id="t-pnl"))

    exec_calls = [c for c in mock_bus.publish.call_args_list if c.args[0] == "executions"]
    assert len(exec_calls) == 1
    payload = exec_calls[0].args[1]
    assert abs(payload[FieldName.PNL] - expected_pnl) < 1e-6


async def test_db_no_pnl_on_rejected_sell(engine_db, mock_bus, mock_broker):
    """Rejected SELL must not publish any P&L to the executions stream."""
    mock_broker.get_position.return_value = _flat_position()

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine_db.process(_make_decision(side="sell"))

    exec_calls = [c for c in mock_bus.publish.call_args_list if c.args[0] == "executions"]
    assert len(exec_calls) == 0


# ---------------------------------------------------------------------------
# 3. Duplicate SELL does not double-close or double-count P&L — DB path
# ---------------------------------------------------------------------------


async def test_db_duplicate_sell_skipped_via_idempotency(engine_db, mock_bus, mock_broker):
    """Second SELL with same idempotency_key must be skipped (DB dedup)."""
    existing = {"id": "order-123", "status": "filled", "idempotency_key": "k"}
    mock_broker.get_position.return_value = _long_position()

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(existing_row=existing),
    ):
        await engine_db.process(_make_decision(side="sell"))

    mock_broker.place_order.assert_not_called()
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "executions" not in published_streams


# ---------------------------------------------------------------------------
# 4. Duplicate BUY does not create duplicate open positions — DB path
# ---------------------------------------------------------------------------


async def test_db_duplicate_buy_skipped_via_idempotency(engine_db, mock_bus, mock_broker):
    """Second BUY with same idempotency_key must be skipped (DB dedup)."""
    existing = {"id": "order-buy-123", "status": "filled", "idempotency_key": "k"}
    mock_broker.get_position.return_value = _flat_position()

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(existing_row=existing),
    ):
        await engine_db.process(_make_decision(side="buy"))

    mock_broker.place_order.assert_not_called()
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "executions" not in published_streams


# ---------------------------------------------------------------------------
# 5. SELL quantity > open quantity is clamped to available
# ---------------------------------------------------------------------------


async def test_db_sell_qty_clamped_when_oversell(engine_db, mock_bus, mock_broker):
    """SELL qty greater than open position qty is clamped; broker receives clamped qty."""
    open_qty = 0.5
    mock_broker.get_position.return_value = _long_position(qty=open_qty)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-clamp",
        FieldName.FILL_PRICE: 51_000.0,
        FieldName.STATUS: "filled",
    }

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        # Request qty=2.0 but only 0.5 available
        await engine_db.process(_make_decision(side="sell", qty=2.0))

    mock_broker.place_order.assert_called_once()
    # Broker should have received the clamped qty (0.5), not 2.0
    call_args = mock_broker.place_order.call_args
    actual_qty = call_args.args[2] if len(call_args.args) >= 3 else call_args.kwargs.get("qty")
    assert actual_qty == pytest.approx(open_qty)


async def test_db_vwap_plan_recomputed_after_clamp(engine_db, mock_bus, mock_broker):
    """After oversell clamping the VWAP plan reflects the clamped qty, not the requested qty.

    LARGE_ORDER_THRESHOLD is 10.0: request qty=15.0 (above threshold) clamped to
    open_qty=3.0 (below threshold) must produce vwap_plan=None in the executions payload.
    """
    open_qty = 3.0
    mock_broker.get_position.return_value = _long_position(qty=open_qty)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-vwap-db",
        FieldName.FILL_PRICE: 51_000.0,
        FieldName.STATUS: "filled",
    }

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine_db.process(_make_decision(side="sell", qty=15.0))

    exec_calls = [c for c in mock_bus.publish.call_args_list if c.args[0] == "executions"]
    assert len(exec_calls) == 1
    assert exec_calls[0].args[1][FieldName.VWAP_PLAN] is None


async def test_db_short_side_also_clamped(engine_db, mock_bus, mock_broker):
    """side='short' (sell-equivalent) is subject to the same oversell clamp as side='sell'."""
    open_qty = 0.4
    mock_broker.get_position.return_value = _long_position(qty=open_qty)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-short-clamp",
        FieldName.FILL_PRICE: 51_000.0,
        FieldName.STATUS: "filled",
    }

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine_db.process(_make_decision(side="short", qty=10.0))

    mock_broker.place_order.assert_called_once()
    call_args = mock_broker.place_order.call_args
    actual_qty = call_args.args[2] if len(call_args.args) >= 3 else call_args.kwargs.get("qty")
    assert actual_qty == pytest.approx(open_qty)


# ---------------------------------------------------------------------------
# 6. In-memory mode: SELL with no BUY is rejected and recorded
# ---------------------------------------------------------------------------


async def test_mem_sell_rejected_when_no_open_position(
    engine_mem, mock_bus, mock_broker, monkeypatch
):
    """In-memory path: SELL with no open position is rejected, recorded in store."""
    mock_broker.get_position.return_value = _flat_position()

    await engine_mem.process(_make_decision(side="sell", trace_id="t-mem-rej"))

    mock_broker.place_order.assert_not_called()

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert STREAM_SELL_REJECTED in published_streams
    assert "executions" not in published_streams


async def test_mem_sell_rejection_recorded_in_store(engine_mem, mock_bus, mock_broker):
    """In-memory path: rejected SELL is recorded in InMemoryStore.rejected_sells."""
    from api.runtime_state import get_runtime_store

    mock_broker.get_position.return_value = _flat_position()

    await engine_mem.process(_make_decision(side="sell", symbol="BTC/USD", trace_id="t-rej-store"))

    store = get_runtime_store()
    assert len(store.rejected_sells) == 1
    entry = store.rejected_sells[0]
    assert entry[FieldName.SYMBOL] == "BTC/USD"
    assert entry[FieldName.REJECTION_REASON] == "NO_OPEN_POSITION"
    assert entry[FieldName.TRACE_ID] == "t-rej-store"


async def test_mem_buy_then_sell_closes_position(engine_mem, mock_bus, mock_broker):
    """In-memory path: BUY fills position; subsequent SELL reaches broker."""
    entry_price = 45_000.0
    mock_broker.get_position.return_value = _long_position(qty=1.0, entry_price=entry_price)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-mem-sell",
        FieldName.FILL_PRICE: 48_000.0,
        FieldName.STATUS: "filled",
    }

    await engine_mem.process(_make_decision(side="sell", qty=1.0, trace_id="t-mem-sell"))

    mock_broker.place_order.assert_called_once()
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "executions" in published_streams
    assert STREAM_SELL_REJECTED not in published_streams


async def test_mem_pnl_only_on_matched_close(engine_mem, mock_bus, mock_broker):
    """In-memory path: P&L in executions stream must match (exit - entry) * qty."""
    entry = 40_000.0
    exit_p = 44_000.0
    qty = 0.5
    expected_pnl = (exit_p - entry) * qty  # 2000.0

    mock_broker.get_position.return_value = _long_position(qty=qty, entry_price=entry)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-mem-pnl",
        FieldName.FILL_PRICE: exit_p,
        FieldName.STATUS: "filled",
    }

    await engine_mem.process(_make_decision(side="sell", qty=qty, trace_id="t-mem-pnl"))

    exec_calls = [c for c in mock_bus.publish.call_args_list if c.args[0] == "executions"]
    assert len(exec_calls) == 1
    payload = exec_calls[0].args[1]
    assert abs(payload[FieldName.PNL] - expected_pnl) < 1e-6


async def test_mem_sell_qty_clamped_when_oversell(engine_mem, mock_bus, mock_broker):
    """In-memory path: oversell qty is clamped to available position qty."""
    open_qty = 0.3
    mock_broker.get_position.return_value = _long_position(qty=open_qty)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-mem-clamp",
        FieldName.FILL_PRICE: 51_000.0,
        FieldName.STATUS: "filled",
    }

    await engine_mem.process(_make_decision(side="sell", qty=5.0, trace_id="t-mem-clamp"))

    mock_broker.place_order.assert_called_once()
    call_args = mock_broker.place_order.call_args
    actual_qty = call_args.args[2] if len(call_args.args) >= 3 else call_args.kwargs.get("qty")
    assert actual_qty == pytest.approx(open_qty)


async def test_mem_vwap_plan_none_after_clamp_below_threshold(engine_mem, mock_bus, mock_broker):
    """In-memory path: VWAP plan is None when clamped qty falls below LARGE_ORDER_THRESHOLD.

    LARGE_ORDER_THRESHOLD is 10.0: request qty=20.0 (above threshold) clamped to
    open_qty=2.0 (below threshold) must produce vwap_plan=None in executions payload.
    """
    open_qty = 2.0
    mock_broker.get_position.return_value = _long_position(qty=open_qty)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-mem-vwap",
        FieldName.FILL_PRICE: 51_000.0,
        FieldName.STATUS: "filled",
    }

    await engine_mem.process(_make_decision(side="sell", qty=20.0, trace_id="t-vwap-mem"))

    exec_calls = [c for c in mock_bus.publish.call_args_list if c.args[0] == "executions"]
    assert len(exec_calls) == 1
    assert exec_calls[0].args[1][FieldName.VWAP_PLAN] is None


async def test_mem_short_side_also_clamped(engine_mem, mock_bus, mock_broker):
    """In-memory path: side='short' (sell-equivalent) is clamped to the open position qty."""
    open_qty = 0.6
    mock_broker.get_position.return_value = _long_position(qty=open_qty)
    mock_broker.place_order.return_value = {
        FieldName.BROKER_ORDER_ID: "broker-mem-short",
        FieldName.FILL_PRICE: 51_000.0,
        FieldName.STATUS: "filled",
    }

    await engine_mem.process(_make_decision(side="short", qty=12.0, trace_id="t-mem-short"))

    mock_broker.place_order.assert_called_once()
    call_args = mock_broker.place_order.call_args
    actual_qty = call_args.args[2] if len(call_args.args) >= 3 else call_args.kwargs.get("qty")
    assert actual_qty == pytest.approx(open_qty)


async def test_rejection_publish_failure_does_not_propagate(engine_mem, mock_bus, mock_broker):
    """A bus.publish failure during SELL rejection must not propagate — store is the record."""
    from api.runtime_state import get_runtime_store

    mock_broker.get_position.return_value = _flat_position()
    mock_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))

    # Should not raise even though publish fails
    await engine_mem.process(_make_decision(side="sell", trace_id="t-pub-fail"))

    mock_broker.place_order.assert_not_called()
    store = get_runtime_store()
    # Rejection still recorded in store despite publish failure
    assert len(store.rejected_sells) == 1
    assert store.rejected_sells[0][FieldName.TRACE_ID] == "t-pub-fail"


# ---------------------------------------------------------------------------
# 7. Dashboard P&L: InMemoryStore.paired_pnl_payload ignores rejected SELLs
# ---------------------------------------------------------------------------


def test_dashboard_pnl_ignores_rejected_sells():
    """paired_pnl_payload must not include P&L from rejected/unmatched SELLs."""
    store = InMemoryStore()

    # Simulate two open positions but no filled orders
    store.upsert_position(
        "BTC/USD",
        {
            FieldName.SIDE: PositionSide.LONG,
            FieldName.QTY: 1.0,
            FieldName.ENTRY_PRICE: 50_000.0,
            FieldName.UNREALIZED_PNL: 500.0,
        },
    )

    # Record a rejection — must not add any orders or realized P&L
    store.reject_sell_no_position("ETH/USD", trace_id="t1", event_id="e1")
    store.reject_sell_no_position("BTC/USD", trace_id="t2", event_id="e2")

    payload = store.paired_pnl_payload()
    summary = payload[FieldName.SUMMARY]

    # No filled orders → realized P&L must be zero
    assert summary[FieldName.REALIZED_PNL] == pytest.approx(0.0)
    # One open position with unrealized PnL
    assert summary[FieldName.UNREALIZED_PNL] == pytest.approx(500.0)
    # Rejections not counted as closed trades
    assert summary[FieldName.CLOSED_TRADES] == 0


# ---------------------------------------------------------------------------
# 8. InMemoryStore lifecycle helpers
# ---------------------------------------------------------------------------


def test_has_open_position_returns_false_when_flat():
    store = InMemoryStore()
    assert not store.has_open_position("BTC/USD")


def test_has_open_position_returns_true_for_long():
    store = InMemoryStore()
    store.upsert_position(
        "BTC/USD",
        {FieldName.SIDE: PositionSide.LONG, FieldName.QTY: 0.5, FieldName.ENTRY_PRICE: 50_000.0},
    )
    assert store.has_open_position("BTC/USD")


def test_has_open_position_false_for_zero_qty():
    store = InMemoryStore()
    store.upsert_position("BTC/USD", {FieldName.SIDE: PositionSide.LONG, FieldName.QTY: 0.0})
    assert not store.has_open_position("BTC/USD")


def test_get_open_position_returns_none_when_absent():
    store = InMemoryStore()
    assert store.get_open_position("ETH/USD") is None


def test_get_open_position_returns_copy_when_present():
    store = InMemoryStore()
    pos = {FieldName.SIDE: PositionSide.LONG, FieldName.QTY: 1.0, FieldName.ENTRY_PRICE: 40_000.0}
    store.upsert_position("ETH/USD", pos)
    result = store.get_open_position("ETH/USD")
    assert result is not None
    assert result[FieldName.QTY] == pytest.approx(1.0)
    # Returned value is a copy — mutating it does not change the store
    result[FieldName.QTY] = 99.0
    assert store.positions["ETH/USD"][FieldName.QTY] == pytest.approx(1.0)


def test_reject_sell_no_position_records_entry():
    store = InMemoryStore()
    entry = store.reject_sell_no_position("BTC/USD", trace_id="t1", event_id="e1")
    assert entry[FieldName.SYMBOL] == "BTC/USD"
    assert entry[FieldName.REJECTION_REASON] == "NO_OPEN_POSITION"
    assert len(store.rejected_sells) == 1


def test_reject_sell_no_position_caps_list():
    store = InMemoryStore()
    for i in range(600):
        store.reject_sell_no_position("SYM", trace_id=f"t{i}", event_id=f"e{i}")
    assert len(store.rejected_sells) <= 500


def test_rejected_sells_not_counted_in_pnl():
    store = InMemoryStore()
    for i in range(5):
        store.reject_sell_no_position("BTC/USD", trace_id=f"t{i}", event_id=f"e{i}")
    payload = store.paired_pnl_payload()
    assert payload[FieldName.SUMMARY][FieldName.REALIZED_PNL] == pytest.approx(0.0)
    assert payload[FieldName.SUMMARY][FieldName.CLOSED_TRADES] == 0
