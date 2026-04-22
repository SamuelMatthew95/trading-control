"""Tests for ExecutionEngine — order execution, idempotency, PnL, and kill switch."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine

pytestmark = pytest.mark.asyncio


# All tests in this file exercise the DB path via fake sessions.
# Force is_db_available=True so the engine doesn't route to _process_in_memory.
@pytest.fixture(autouse=True)
def _force_db_available(monkeypatch):
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


class _MockAsyncSession:
    """Async session that supports 'async with session.begin()'."""

    def __init__(self, existing_row=None, scalar_value=None):
        self._existing_row = existing_row  # controls idempotency check response
        self._scalar_value = scalar_value or "order-uuid-123"
        self._result = MagicMock()
        self._result.scalar_one.return_value = self._scalar_value
        self._result.scalar.return_value = self._scalar_value
        # Idempotency check: mappings().first() returns None (no existing order)
        self._result.mappings.return_value.first.return_value = existing_row

    async def execute(self, *args, **kwargs):
        return self._result

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def begin(self):
        return _AsyncCtx()


class _AsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _MockSessionFactory:
    """Callable context manager yielding a mock session."""

    def __init__(self, existing_row=None):
        self._existing_row = existing_row

    def __call__(self):
        return self

    async def __aenter__(self):
        return _MockAsyncSession(existing_row=self._existing_row)

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
    redis.get = AsyncMock(return_value=None)  # kill switch OFF by default
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.setnx = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_broker():
    broker = MagicMock(spec=PaperBroker)
    broker.place_order = AsyncMock(
        return_value={
            "broker_order_id": "broker-abc-123",
            "fill_price": 50001.0,
            "status": "filled",
        }
    )
    broker.get_position = AsyncMock(return_value={})
    return broker


@pytest.fixture
def engine(mock_bus, mock_dlq, mock_redis, mock_broker):
    return ExecutionEngine(bus=mock_bus, dlq=mock_dlq, redis_client=mock_redis, broker=mock_broker)


def _make_order(side="buy", symbol="BTC/USD", strategy_id="strat-1"):
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "side": side,
        "qty": 1.0,
        "price": 50000.0,
        "timestamp": "2024-01-01T12:00:00+00:00",
        "trace_id": "trace-exec-001",
        "composite_score": 0.75,
        "signal_type": "MOMENTUM",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_idempotency_skips_duplicate_order(engine, mock_bus, mock_redis, mock_broker):
    """Second call with same idempotency_key returns early without placing another order."""
    existing_row = {
        "id": "order-existing-id",
        "status": "filled",
        "broker_order_id": "b-1",
        "idempotency_key": "key-1",
    }

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(existing_row=existing_row),
    ):
        await engine.process(_make_order())

    # Broker should NOT have been called (duplicate skipped)
    mock_broker.place_order.assert_not_called()
    # No order published to 'executions'
    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "executions" not in published_streams


async def test_builds_idempotency_key_deterministic(engine):
    """Same inputs produce the same idempotency key; different side produces different key."""
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    signal = {"composite_score": 0.75, "signal_type": "MOMENTUM", "price": 50000.0, "qty": 1.0}

    key1 = engine._build_idempotency_key("strat-1", "BTC/USD", "buy", ts, signal)
    key2 = engine._build_idempotency_key("strat-1", "BTC/USD", "buy", ts, signal)
    key_sell = engine._build_idempotency_key("strat-1", "BTC/USD", "sell", ts, signal)

    assert key1 == key2, "Same inputs must produce same key"
    assert key1 != key_sell, "Different side must produce different key"
    assert "strat-1" in key1
    assert "BTC" in key1


async def test_publishes_execution_event(engine, mock_bus, mock_redis, mock_broker):
    """After successful fill, bus.publish is called with 'executions' stream."""
    mock_redis.set = AsyncMock(return_value=True)

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(_make_order("buy"))

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "executions" in published_streams

    exec_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "executions")
    payload = exec_call.args[1]
    assert payload["type"] == "order_filled"
    assert payload["symbol"] == "BTC/USD"
    assert payload["side"] == "buy"
    assert "fill_price" in payload
    assert "trace_id" in payload


async def test_publishes_trade_performance(engine, mock_bus, mock_redis, mock_broker):
    """After successful fill, bus.publish is called with 'trade_performance' stream."""
    mock_redis.set = AsyncMock(return_value=True)

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(_make_order("buy"))

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "trade_performance" in published_streams

    tp_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "trade_performance")
    payload = tp_call.args[1]
    assert payload["type"] == "trade_performance"
    assert payload["symbol"] == "BTC/USD"
    assert "pnl" in payload
    assert "fill_price" in payload
    assert "trace_id" in payload


async def test_trade_performance_payload_satisfies_safe_writer_contract(
    engine, mock_bus, mock_redis, mock_broker
):
    """Regression: the trade_performance payload must carry every field that
    SafeWriter.write_trade_performance requires, or the row silently fails
    validation and PnL metrics permanently read zero.
    See safe_writer.py::write_trade_performance validate_payload + _validate_schema_v3.
    """
    mock_redis.set = AsyncMock(return_value=True)

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(_make_order("buy"))

    tp_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "trade_performance")
    payload = tp_call.args[1]

    # validate_payload required keys
    for required in ("strategy_id", "symbol", "trade_id", "entry_price", "quantity"):
        assert required in payload, f"trade_performance payload missing {required!r}"

    # _validate_schema_v3 check
    assert payload.get("schema_version") == "v3", (
        f"schema_version must be 'v3', got {payload.get('schema_version')!r}"
    )

    # entry_time is read unconditionally via data[FieldName.ENTRY_TIME]
    assert "entry_time" in payload, "trade_performance payload missing entry_time"
    assert payload["entry_time"], "entry_time must be a non-empty ISO timestamp"


async def test_kill_switch_raises(engine, mock_redis):
    """When kill_switch:active is '1' in Redis, RuntimeError('KillSwitchActive') is raised."""
    mock_redis.get = AsyncMock(return_value="1")

    with pytest.raises(RuntimeError, match="KillSwitchActive"):
        await engine.process(_make_order())


async def test_position_upsert_called(engine, mock_bus, mock_redis, mock_broker):
    """After fill, the DB position is upserted via _upsert_position."""
    mock_redis.set = AsyncMock(return_value=True)
    execute_calls = []

    class _TrackingSession:
        async def execute(self, stmt, *args, **kwargs):
            sql_text = str(stmt) if hasattr(stmt, "text") else str(stmt)
            execute_calls.append(sql_text)
            result = MagicMock()
            result.scalar_one.return_value = "order-id-123"
            result.mappings.return_value.first.return_value = None
            result.scalar.return_value = "order-id-123"
            return result

        async def flush(self):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

        def begin(self):
            return _AsyncCtx()

    class _TrackingFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _TrackingSession()

        async def __aexit__(self, *args):
            pass

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _TrackingFactory(),
    ):
        await engine.process(_make_order("buy"))

    # Verify that at least one SQL call included "positions"
    position_calls = [c for c in execute_calls if "positions" in c.lower()]
    assert len(position_calls) > 0, "Expected upsert to positions table"


async def test_pnl_computed_for_closing_trade(engine, mock_bus, mock_redis, mock_broker):
    """When prior position exists as 'long', selling computes positive realized PnL."""
    prior_position = {
        "symbol": "BTC/USD",
        "side": "long",
        "qty": 1.0,
        "entry_price": 49000.0,  # bought at 49k
        "current_price": 50000.0,
    }
    mock_broker.get_position = AsyncMock(return_value=prior_position)
    mock_broker.place_order = AsyncMock(
        return_value={
            "broker_order_id": "broker-close-001",
            "fill_price": 51000.0,  # selling at 51k → PnL = (51000-49000)*1 = 2000
            "status": "filled",
        }
    )

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(_make_order("sell"))

    # Check trade_performance payload has positive pnl
    tp_call = next(
        (c for c in mock_bus.publish.call_args_list if c.args[0] == "trade_performance"),
        None,
    )
    assert tp_call is not None, "trade_performance not published"
    payload = tp_call.args[1]
    assert payload["pnl"] == pytest.approx(2000.0, abs=0.01)


async def test_pnl_zero_for_opening_trade(engine, mock_bus, mock_redis, mock_broker):
    """When no prior position, opening a trade has zero realized PnL."""
    mock_broker.get_position = AsyncMock(return_value={})  # flat / no position
    mock_broker.place_order = AsyncMock(
        return_value={
            "broker_order_id": "broker-open-001",
            "fill_price": 50001.0,
            "status": "filled",
        }
    )

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(_make_order("buy"))

    tp_call = next(
        (c for c in mock_bus.publish.call_args_list if c.args[0] == "trade_performance"),
        None,
    )
    assert tp_call is not None
    payload = tp_call.args[1]
    assert payload["pnl"] == pytest.approx(0.0)


async def test_compute_realized_pnl_long_close(engine):
    """_compute_realized_pnl returns correct value when closing a long."""
    prior = {"side": "long", "entry_price": 100.0, "qty": 5.0}
    pnl = engine._compute_realized_pnl(prior, "sell", 5.0, 120.0)
    assert pnl == pytest.approx(100.0)  # (120-100) * 5


async def test_compute_realized_pnl_short_close(engine):
    """_compute_realized_pnl returns correct value when closing a short."""
    prior = {"side": "short", "entry_price": 100.0, "qty": 5.0}
    pnl = engine._compute_realized_pnl(prior, "buy", 5.0, 80.0)
    assert pnl == pytest.approx(100.0)  # (100-80) * 5


async def test_compute_realized_pnl_opening_is_zero(engine):
    """_compute_realized_pnl returns 0.0 when opening a new position."""
    prior = {}  # no prior position
    pnl = engine._compute_realized_pnl(prior, "buy", 1.0, 50000.0)
    assert pnl == 0.0


# ---------------------------------------------------------------------------
# _compute_pnl_percent tests
# ---------------------------------------------------------------------------


async def test_pnl_percent_full_long_close(engine):
    """Buy 1 BTC at $50k, sell 1 BTC at $55k → pnl_percent ≈ 10.0."""
    prior = {"side": "long", "qty": 1.0, "entry_price": 50000.0}
    realized_pnl = 5000.0  # (55000 - 50000) * 1
    pnl_pct = engine._compute_pnl_percent(prior, "sell", 1.0, 50000.0, realized_pnl)
    assert pnl_pct == pytest.approx(10.0, rel=1e-4)


async def test_pnl_percent_zero_on_open(engine):
    """Opening a trade returns pnl_percent of 0.0 (realized_pnl is 0)."""
    prior = {}  # no prior position
    pnl_pct = engine._compute_pnl_percent(prior, "buy", 1.0, 50000.0, 0.0)
    assert pnl_pct == 0.0


async def test_pnl_percent_oversell_uses_closed_qty(engine):
    """Position has 0.1 BTC; order sells 0.2 BTC. closed_qty=0.1, denominator uses 0.1 not 0.2."""
    prior = {"side": "long", "qty": 0.1, "entry_price": 50000.0}
    # Realized PnL computed on 0.1 BTC closed (min(0.2, 0.1) = 0.1)
    realized_pnl = (55000.0 - 50000.0) * 0.1  # 500.0
    pnl_pct = engine._compute_pnl_percent(prior, "sell", 0.2, 50000.0, realized_pnl)
    # cost_basis = 50000 * 0.1 = 5000; pnl_percent = 500/5000*100 = 10.0
    assert pnl_pct == pytest.approx(10.0, rel=1e-4)


# ---------------------------------------------------------------------------
# _process_in_memory tests
# ---------------------------------------------------------------------------


async def test_process_in_memory_writes_order_to_store(
    engine, mock_bus, mock_redis, mock_broker, monkeypatch
):
    """With is_db_available=False, process() writes one order to InMemoryStore."""
    # Override the autouse _force_db_available fixture for this test
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)

    mock_broker.get_position = AsyncMock(return_value={})
    mock_broker.place_order = AsyncMock(
        return_value={"broker_order_id": "x", "fill_price": 50001.0, "status": "filled"}
    )

    from api.runtime_state import get_runtime_store

    await engine.process(_make_order("buy"))

    orders = get_runtime_store().orders
    assert len(orders) == 1
    order = orders[0]
    assert order["symbol"] == "BTC/USD"
    assert order["side"] == "buy"
    assert order["filled_price"] == pytest.approx(50001.0)
    assert "pnl" in order
    assert "pnl_percent" in order


async def test_process_in_memory_upserts_position(
    engine, mock_bus, mock_redis, mock_broker, monkeypatch
):
    """After a buy in memory mode, the InMemoryStore position for BTC/USD has positive qty."""
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)

    mock_broker.get_position = AsyncMock(return_value={})
    mock_broker.place_order = AsyncMock(
        return_value={"broker_order_id": "x", "fill_price": 50001.0, "status": "filled"}
    )

    from api.runtime_state import get_runtime_store

    await engine.process(_make_order("buy"))

    positions = get_runtime_store().positions
    assert "BTC/USD" in positions
    assert float(positions["BTC/USD"]["qty"]) > 0


async def test_process_in_memory_publishes_streams(
    engine, mock_bus, mock_redis, mock_broker, monkeypatch
):
    """In memory mode, bus.publish is called for STREAM_EXECUTIONS and STREAM_TRADE_PERFORMANCE."""
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)

    mock_broker.get_position = AsyncMock(return_value={})
    mock_broker.place_order = AsyncMock(
        return_value={"broker_order_id": "x", "fill_price": 50001.0, "status": "filled"}
    )

    await engine.process(_make_order("buy"))

    published_streams = [call.args[0] for call in mock_bus.publish.call_args_list]
    assert "executions" in published_streams
    assert "trade_performance" in published_streams


async def test_in_memory_trade_performance_payload_satisfies_safe_writer_contract(
    engine, mock_bus, mock_redis, mock_broker, monkeypatch
):
    """Same contract as test_trade_performance_payload_satisfies_safe_writer_contract
    but for the in-memory (is_db_available=False) code path. Both paths must
    emit the fields SafeWriter validates or the pipeline silently drops the
    row once DB availability returns.
    """
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)

    mock_broker.get_position = AsyncMock(return_value={})
    mock_broker.place_order = AsyncMock(
        return_value={"broker_order_id": "x", "fill_price": 50001.0, "status": "filled"}
    )

    await engine.process(_make_order("buy"))

    tp_call = next(c for c in mock_bus.publish.call_args_list if c.args[0] == "trade_performance")
    payload = tp_call.args[1]

    for required in ("strategy_id", "symbol", "trade_id", "entry_price", "quantity"):
        assert required in payload, f"in-memory trade_performance missing {required!r}"
    assert payload.get("schema_version") == "v3"
    assert payload.get("entry_time"), "in-memory payload missing entry_time"


async def test_process_in_memory_deduplicates_replayed_messages(
    engine, mock_bus, mock_redis, mock_broker, monkeypatch
):
    """A redelivered decision message must not produce a second fill in memory mode.

    BaseStreamConsumer is at-least-once; the Redis SET NX dedup key must prevent
    the broker from being called more than once for the same idempotency key.
    """
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: False)

    mock_broker.get_position = AsyncMock(return_value={})
    mock_broker.place_order = AsyncMock(
        return_value={"broker_order_id": "x", "fill_price": 50001.0, "status": "filled"}
    )

    # Track dedup key attempts separately from order-lock NX attempts.
    # Both use nx=True, so we key off the Redis key prefix to distinguish them.
    dedup_seen: set[str] = set()

    async def _fake_set(key, value, ex=None, nx=False):
        if nx and key.startswith("order:dedup:"):
            if key in dedup_seen:
                return False  # duplicate — second replay attempt
            dedup_seen.add(key)
            return True  # first attempt — let it through
        return True  # order lock and all non-NX sets always succeed

    mock_redis.set = _fake_set

    order = _make_order("buy")

    # First delivery — should execute
    await engine.process(order)
    assert mock_broker.place_order.call_count == 1

    # Second delivery (replay) — same message, same idempotency key
    await engine.process(order)
    assert mock_broker.place_order.call_count == 1, (
        "Broker must NOT be called a second time for a replayed message"
    )
