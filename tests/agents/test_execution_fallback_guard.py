from unittest.mock import AsyncMock

import pytest

from api.constants import FieldName
from api.services.execution.execution_engine import ExecutionEngine


class _Broker:
    def __init__(self, qty: float, side: str = "long", should_raise: bool = False):
        self.qty = qty
        self.side = side
        self.should_raise = should_raise

    async def get_position(self, symbol: str):
        if self.should_raise:
            raise AssertionError("get_position should not be called")
        return {FieldName.QTY: self.qty, FieldName.SIDE: self.side}


@pytest.fixture
def _engine():
    bus = AsyncMock()
    dlq = AsyncMock()
    redis = AsyncMock()
    redis.get.return_value = None
    return ExecutionEngine(bus, dlq, redis, _Broker(0.0))


@pytest.mark.asyncio
async def test_fallback_buy_blocked_when_not_allowed(_engine, monkeypatch):
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)
    data = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.ACTION: "buy",
        FieldName.QTY: 0.1,
        FieldName.PRICE: 100,
        FieldName.REASON: "fallback timeout",
        FieldName.TRACE_ID: "t1",
    }
    parsed = await _engine._parse_and_validate(data)
    assert parsed is None


@pytest.mark.asyncio
async def test_fallback_sell_reduce_only_allowed(_engine, monkeypatch):
    from api.config import settings

    _engine.broker = _Broker(0.5)
    monkeypatch.setattr(settings, "ALLOW_FALLBACK_TRADES", True)
    monkeypatch.setattr(settings, "MAX_FALLBACK_ORDER_QTY", 1.0)
    monkeypatch.setattr(settings, "MAX_SYMBOL_EXPOSURE", 1.0)
    monkeypatch.setattr(settings, "MAX_OPEN_POSITION_QTY", 1.0)

    data = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.ACTION: "sell",
        FieldName.QTY: 0.1,
        FieldName.PRICE: 100,
        FieldName.REASON: "fallback timeout",
        FieldName.TRACE_ID: "t2",
    }
    parsed = await _engine._parse_and_validate(data)
    assert parsed is not None


@pytest.mark.asyncio
async def test_fallback_not_allowed_blocks_before_broker_io(_engine, monkeypatch):
    from api.config import settings

    monkeypatch.setattr(settings, "ALLOW_FALLBACK_TRADES", False)
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)
    _engine.broker = _Broker(0.0, should_raise=True)
    data = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.ACTION: "buy",
        FieldName.QTY: 0.1,
        FieldName.PRICE: 100,
        FieldName.REASON: "fallback timeout",
        FieldName.TRACE_ID: "t3",
    }
    parsed = await _engine._parse_and_validate(data)
    assert parsed is None


@pytest.mark.asyncio
async def test_fallback_detected_from_primary_edge_with_reasoning_source(_engine, monkeypatch):
    from api.config import settings

    monkeypatch.setattr(settings, "ALLOW_FALLBACK_TRADES", False)
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)
    _engine.broker = _Broker(0.0, should_raise=True)
    data = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.ACTION: "buy",
        FieldName.QTY: 0.1,
        FieldName.PRICE: 100,
        FieldName.SOURCE: "reasoning_agent",
        FieldName.PRIMARY_EDGE: "fallback:skip_reasoning",
        FieldName.TRACE_ID: "t3b",
    }
    parsed = await _engine._parse_and_validate(data)
    assert parsed is None


@pytest.mark.asyncio
async def test_fallback_buy_reduces_short_not_blocked(_engine, monkeypatch):
    from api.config import settings

    monkeypatch.setattr(settings, "ALLOW_FALLBACK_TRADES", True)
    monkeypatch.setattr(settings, "MAX_FALLBACK_ORDER_QTY", 10.0)
    monkeypatch.setattr(settings, "MAX_SYMBOL_EXPOSURE", 10.0)
    monkeypatch.setattr(settings, "MAX_OPEN_POSITION_QTY", 10.0)
    _engine.broker = _Broker(5.0, side="short")
    data = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.ACTION: "buy",
        FieldName.QTY: 2.0,
        FieldName.PRICE: 100,
        FieldName.REASON: "fallback timeout",
        FieldName.TRACE_ID: "t4",
    }
    parsed = await _engine._parse_and_validate(data)
    assert parsed is not None


@pytest.mark.asyncio
async def test_fallback_buy_over_closes_short_and_opens_long_blocked(_engine, monkeypatch):
    from api.config import settings

    monkeypatch.setattr(settings, "ALLOW_FALLBACK_TRADES", True)
    monkeypatch.setattr(settings, "MAX_FALLBACK_ORDER_QTY", 10.0)
    monkeypatch.setattr(settings, "MAX_SYMBOL_EXPOSURE", 10.0)
    monkeypatch.setattr(settings, "MAX_OPEN_POSITION_QTY", 10.0)
    monkeypatch.setattr("api.services.execution.execution_engine.is_db_available", lambda: True)
    _engine.broker = _Broker(5.0, side="short")
    data = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.ACTION: "buy",
        FieldName.QTY: 7.0,
        FieldName.PRICE: 100,
        FieldName.REASON: "fallback timeout",
        FieldName.TRACE_ID: "t5",
    }
    parsed = await _engine._parse_and_validate(data)
    assert parsed is None


def test_signed_position_qty_preserves_sign_without_side():
    assert ExecutionEngine._signed_position_qty({FieldName.QTY: -3.0}) == pytest.approx(-3.0)
    assert ExecutionEngine._signed_position_qty({FieldName.QTY: 3.0}) == pytest.approx(3.0)
