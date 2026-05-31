"""Pipeline handoff tests: EE idle heartbeats, HOLD/BUY gates, degraded-mode dashboard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.constants import (
    FieldName,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


def _make_dlq() -> DLQManager:
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


def _make_redis(*, kill_switch: str | None = None, trading_paused: str | None = None) -> AsyncMock:
    redis = AsyncMock()

    async def _get_side_effect(key, *args, **kwargs):
        from api.constants import REDIS_KEY_KILL_SWITCH, REDIS_KEY_TRADING_PAUSED

        if key == REDIS_KEY_KILL_SWITCH:
            return kill_switch
        if key == REDIS_KEY_TRADING_PAUSED:
            return trading_paused
        return None

    redis.get = AsyncMock(side_effect=_get_side_effect)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.setnx = AsyncMock(return_value=True)
    return redis


def _make_broker() -> PaperBroker:
    broker = MagicMock(spec=PaperBroker)
    broker.place_order = AsyncMock(
        return_value={
            "broker_order_id": "broker-abc",
            "fill_price": 50001.0,
            "status": "filled",
        }
    )
    broker.get_position = AsyncMock(return_value={})
    return broker


def _decision_payload(
    *,
    action: str = "buy",
    signal_confidence: float = 0.9,
    reasoning_score: float = 0.9,
    symbol: str = "BTC/USD",
    qty: float = 0.1,
    price: float = 50000.0,
    trace_id: str = "trace-handoff-001",
) -> dict:
    return {
        FieldName.ACTION: action,
        FieldName.SYMBOL: symbol,
        FieldName.QTY: qty,
        FieldName.PRICE: price,
        FieldName.SIGNAL_CONFIDENCE: signal_confidence,
        FieldName.REASONING_SCORE: reasoning_score,
        FieldName.TRACE_ID: trace_id,
        FieldName.STRATEGY_ID: "strat-pipeline-1",
    }


class _MockAsyncSession:
    """Minimal async session that returns scalar 'ok' and mapping None (no duplicate)."""

    def __init__(self):
        result = MagicMock()
        result.scalar_one.return_value = "order-uuid-1"
        result.scalar.return_value = "order-uuid-1"
        result.mappings.return_value.first.return_value = None
        result.first.return_value = None
        self._result = result

    async def execute(self, *_a, **_kw):
        return self._result

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def begin(self):
        return _Ctx()


class _Ctx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class _MockSessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _MockAsyncSession()

    async def __aexit__(self, *_):
        pass


# Force DB-available path so tests use process(), not _process_in_memory().
@pytest.fixture(autouse=True)
def _force_db(monkeypatch):
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)


# ---------------------------------------------------------------------------
# Idle heartbeat tests — HOLD / score gate / missing fields
# ---------------------------------------------------------------------------


async def test_hold_decision_writes_idle_heartbeat_no_order():
    """HOLD action: no broker call, heartbeat written with idle:hold status."""
    redis = _make_redis()
    bus = _make_bus()
    dlq = _make_dlq()
    broker = _make_broker()
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)

    heartbeat_calls: list[str] = []

    async def _fake_heartbeat(r, agent, event_str, count=0, extra=None):
        heartbeat_calls.append(event_str)

    with (
        patch(
            "api.services.execution.execution_engine.AsyncSessionFactory",
            _MockSessionFactory(),
        ),
        patch(
            "api.services.execution.execution_engine._write_heartbeat",
            side_effect=_fake_heartbeat,
        ),
    ):
        await engine.process(_decision_payload(action="hold"))

    broker.place_order.assert_not_called()
    # Heartbeat must have been written with the hold status
    assert any("idle:hold" in c for c in heartbeat_calls), (
        f"no idle:hold heartbeat — got {heartbeat_calls}"
    )


async def test_buy_with_low_score_writes_gated_heartbeat():
    """Score below threshold: no order, heartbeat with gated:score."""
    redis = _make_redis()
    bus = _make_bus()
    dlq = _make_dlq()
    broker = _make_broker()
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)

    heartbeat_calls: list[str] = []

    async def _fake_heartbeat(r, agent, event_str, count=0, extra=None):
        heartbeat_calls.append(event_str)

    # Use very low scores so final_score < EXECUTION_DECISION_THRESHOLD (0.55)
    payload = _decision_payload(signal_confidence=0.1, reasoning_score=0.1)

    with (
        patch(
            "api.services.execution.execution_engine.AsyncSessionFactory",
            _MockSessionFactory(),
        ),
        patch(
            "api.services.execution.execution_engine._write_heartbeat",
            side_effect=_fake_heartbeat,
        ),
    ):
        await engine.process(payload)

    broker.place_order.assert_not_called()
    assert any("gated:score" in c for c in heartbeat_calls), (
        f"expected gated:score heartbeat — got {heartbeat_calls}"
    )


async def test_buy_with_high_score_reaches_broker():
    """BUY intent with score above threshold reaches the broker."""
    redis = _make_redis()
    bus = _make_bus()
    dlq = _make_dlq()
    broker = _make_broker()
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)

    payload = _decision_payload(action="buy", signal_confidence=0.95, reasoning_score=0.95)

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(payload)

    broker.place_order.assert_called_once()


async def test_sell_with_high_score_reaches_broker():
    """SELL intent with score above threshold AND open position reaches the broker."""
    redis = _make_redis()
    bus = _make_bus()
    dlq = _make_dlq()
    broker = _make_broker()
    # Return an existing long position so the sell-rejection guard is bypassed.
    # _reject_unmatched_sell requires side=="long" AND qty > 0.
    broker.get_position = AsyncMock(
        return_value={FieldName.QTY: 0.1, FieldName.ENTRY_PRICE: 50000.0, FieldName.SIDE: "long"}
    )
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)

    payload = _decision_payload(action="sell", signal_confidence=0.95, reasoning_score=0.95)

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(payload)

    broker.place_order.assert_called_once()


async def test_missing_fields_writes_error_heartbeat():
    """Missing required fields (qty) writes error:missing_fields heartbeat."""
    redis = _make_redis()
    bus = _make_bus()
    dlq = _make_dlq()
    broker = _make_broker()
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)

    heartbeat_calls: list[str] = []

    async def _fake_heartbeat(r, agent, event_str, count=0, extra=None):
        heartbeat_calls.append(event_str)

    payload = {
        FieldName.ACTION: "buy",
        FieldName.SYMBOL: "BTC/USD",
        # qty deliberately omitted
        FieldName.PRICE: 50000.0,
        FieldName.TRACE_ID: "trace-missing-001",
    }

    with (
        patch(
            "api.services.execution.execution_engine.AsyncSessionFactory",
            _MockSessionFactory(),
        ),
        patch(
            "api.services.execution.execution_engine._write_heartbeat",
            side_effect=_fake_heartbeat,
        ),
    ):
        await engine.process(payload)

    broker.place_order.assert_not_called()
    assert any("error:missing_fields" in c for c in heartbeat_calls), (
        f"expected error:missing_fields heartbeat — got {heartbeat_calls}"
    )


async def test_trading_paused_writes_blocked_heartbeat():
    """When trading is paused, heartbeat with blocked:trading_paused is written."""
    redis = _make_redis(trading_paused="1")
    bus = _make_bus()
    dlq = _make_dlq()
    broker = _make_broker()
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)

    heartbeat_calls: list[str] = []

    async def _fake_heartbeat(r, agent, event_str, count=0, extra=None):
        heartbeat_calls.append(event_str)

    with patch(
        "api.services.execution.execution_engine._write_heartbeat",
        side_effect=_fake_heartbeat,
    ):
        await engine.process(_decision_payload())

    broker.place_order.assert_not_called()
    assert any("blocked:trading_paused" in c for c in heartbeat_calls), (
        f"expected blocked:trading_paused heartbeat — got {heartbeat_calls}"
    )


# ---------------------------------------------------------------------------
# Score gate boundary test
# ---------------------------------------------------------------------------


async def test_score_above_threshold_clears_gate():
    """Score above EXECUTION_DECISION_THRESHOLD must reach the broker.

    final_score = signal*0.50 + reasoning*0.30 + 0.50*0.20
    With signal=reasoning=0.7: final_score = 0.35 + 0.21 + 0.10 = 0.66 > 0.55
    """
    redis = _make_redis()
    bus = _make_bus()
    dlq = _make_dlq()
    broker = _make_broker()
    engine = ExecutionEngine(bus=bus, dlq=dlq, redis_client=redis, broker=broker)

    # 0.66 is comfortably above threshold (0.55)
    payload = _decision_payload(signal_confidence=0.7, reasoning_score=0.7)

    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(payload)

    broker.place_order.assert_called_once()


async def test_momentum_tier_decision_clears_confidence_gate():
    """REGRESSION: a MOMENTUM-tier decision (signal_confidence=0.55) must reach the
    broker through the full gate chain. SIGNAL_CONFIDENCE_MIN_GATE used to be 0.65 —
    above the 0.55 momentum tier — so it silently blocked every momentum trade before
    the execution-score gate (tuned to admit 0.55) ever ran. Lowered to 0.50, the two
    gates now agree: execution_score = 0.55*0.50 + 0.55*0.30 + 0.6*0.20 = 0.56 > 0.55
    and the confidence gate 0.55 >= 0.50.
    """
    broker = _make_broker()
    engine = ExecutionEngine(
        bus=_make_bus(), dlq=_make_dlq(), redis_client=_make_redis(), broker=broker
    )

    payload = _decision_payload(signal_confidence=0.55, reasoning_score=0.55)
    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(payload)

    broker.place_order.assert_called_once()


async def test_below_momentum_confidence_blocked_even_with_high_reasoning():
    """The confidence gate still blocks sub-momentum signals so the 0.50 value can't
    be widened by accident. signal_confidence=0.45 clears the execution-score gate
    when reasoning is high (0.45*0.50 + 0.9*0.30 + 0.6*0.20 = 0.615 > 0.55) but the
    confidence gate (0.45 < 0.50) blocks it, so no order is placed.
    """
    broker = _make_broker()
    engine = ExecutionEngine(
        bus=_make_bus(), dlq=_make_dlq(), redis_client=_make_redis(), broker=broker
    )

    payload = _decision_payload(signal_confidence=0.45, reasoning_score=0.9)
    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory",
        _MockSessionFactory(),
    ):
        await engine.process(payload)

    broker.place_order.assert_not_called()


# ---------------------------------------------------------------------------
# Dashboard degraded_mode tests
# ---------------------------------------------------------------------------


async def test_flow_status_degraded_mode_when_db_unavailable():
    """GET /dashboard/flow-status includes degraded_mode=True when DB is unavailable."""
    from api.in_memory_store import InMemoryStore
    from api.routes import dashboard_v2
    from api.runtime_state import set_db_available, set_runtime_store

    set_runtime_store(InMemoryStore())
    set_db_available(False)

    result = await dashboard_v2.get_flow_status()

    assert result["degraded_mode"] is True
    assert result.get("degraded_reason") == "db_unavailable"
    assert "realtime_event_count" in result
    assert "persisted_event_count" in result
    assert result["persisted_event_count"] == 0


async def test_flow_status_not_degraded_when_db_available(monkeypatch):
    """GET /dashboard/flow-status returns degraded_mode=False when DB is available."""
    from api.in_memory_store import InMemoryStore
    from api.routes import dashboard_v2
    from api.runtime_state import set_db_available, set_runtime_store

    set_runtime_store(InMemoryStore())
    set_db_available(False)  # autouse reset

    # Patch is_db_available where it is looked up (flow service, not dashboard_v2 router)
    import api.services.dashboard.flow as _flow_svc

    monkeypatch.setattr(_flow_svc, "is_db_available", lambda: True)

    class _ZeroResult:
        def mappings(self):
            return self

        def first(self):
            return {
                "agent_runs": 0,
                "agent_logs": 0,
                "agent_grades": 0,
                "orders": 0,
                "trade_lifecycle": 0,
            }

        def scalar(self):
            return None

    class _ZeroSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, *_a, **_kw):
            return _ZeroResult()

    class _ZeroFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _ZeroSession()

        async def __aexit__(self, *_):
            pass

    monkeypatch.setattr(_flow_svc, "AsyncSessionFactory", _ZeroFactory())

    result = await dashboard_v2.get_flow_status()

    assert result["degraded_mode"] is False
    assert "degraded_reason" not in result
    assert "realtime_event_count" in result
    assert "persisted_event_count" in result


# ---------------------------------------------------------------------------
# Trade feed empty_reason tests
# ---------------------------------------------------------------------------


async def test_trade_feed_empty_reason_db_degraded():
    """Trade feed returns empty_reason=db_degraded when DB is unavailable and in-memory is empty."""
    from api.in_memory_store import InMemoryStore
    from api.routes import dashboard_v2
    from api.runtime_state import set_db_available, set_runtime_store

    set_runtime_store(InMemoryStore())
    set_db_available(False)

    result = await dashboard_v2.get_trade_feed()

    assert result["count"] == 0
    assert result.get("empty_reason") == "db_degraded"
