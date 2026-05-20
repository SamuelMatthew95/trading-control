from unittest.mock import AsyncMock

import pytest

from api.constants import FieldName
from api.services.execution.execution_engine import ExecutionEngine


class _Broker:
    def __init__(self, qty: float):
        self.qty = qty

    async def get_position(self, symbol: str):
        return {FieldName.QTY: self.qty}


@pytest.fixture
def _engine():
    bus = AsyncMock()
    dlq = AsyncMock()
    redis = AsyncMock()
    redis.get.return_value = None
    return ExecutionEngine(bus, dlq, redis, _Broker(0.0))


@pytest.mark.asyncio
async def test_fallback_buy_blocked_when_not_allowed(_engine):
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
