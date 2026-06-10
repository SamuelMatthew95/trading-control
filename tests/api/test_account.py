"""Tests for GET /account — the broker-truth paper-account snapshot.

Cash comes from the PaperBroker's real balance; equity marks the broker's open
positions to the live price cache. The endpoint must degrade to explicit nulls
("unavailable") — never fabricated dollars — when broker truth cannot be read.
"""

from __future__ import annotations

import json

import fakeredis
import pytest

from api.constants import (
    DEFAULT_PAPER_CASH,
    REDIS_KEY_PAPER_CASH,
    REDIS_KEY_PAPER_POSITION,
    REDIS_KEY_PRICES,
    FieldName,
)
from api.routes import positions as positions_module
from api.services.execution.brokers.paper import PaperBroker

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def redis():
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield r
    await r.aclose()


async def _seed_position(redis, symbol: str, side: str, qty: float, entry: float) -> None:
    await redis.set(
        REDIS_KEY_PAPER_POSITION.format(symbol=symbol),
        json.dumps(
            {
                FieldName.SYMBOL: symbol,
                FieldName.SIDE: side,
                FieldName.QTY: qty,
                FieldName.ENTRY_PRICE: entry,
                FieldName.CURRENT_PRICE: entry,
            }
        ),
    )


async def test_account_unavailable_when_no_broker(monkeypatch):
    monkeypatch.setattr(positions_module, "get_paper_broker", lambda: None)
    payload = await positions_module.get_account()
    assert payload[FieldName.SOURCE] == "unavailable"
    assert payload[FieldName.CASH] is None
    assert payload[FieldName.EQUITY] is None
    assert payload[FieldName.STARTING_CASH] == DEFAULT_PAPER_CASH


async def test_account_reports_broker_cash_and_live_marked_equity(redis, monkeypatch):
    broker = PaperBroker(redis)
    await redis.set(REDIS_KEY_PAPER_CASH, 99000.0)
    await _seed_position(redis, "BTC/USD", "long", 0.001, 50000.0)
    await redis.set(
        REDIS_KEY_PRICES.format(symbol="BTC/USD"), json.dumps({FieldName.PRICE: 60000.0})
    )
    monkeypatch.setattr(positions_module, "get_paper_broker", lambda: broker)

    payload = await positions_module.get_account()

    assert payload[FieldName.SOURCE] == "paper_broker"
    assert payload[FieldName.CASH] == 99000.0
    # equity = cash + 0.001 × live mark (60000) = 99060
    assert payload[FieldName.EQUITY] == pytest.approx(99060.0)
    assert payload[FieldName.TOTAL_PNL] == pytest.approx(99060.0 - DEFAULT_PAPER_CASH)
    assert payload[FieldName.BUYING_POWER] == 99000.0


async def test_account_short_position_uses_signed_qty(redis, monkeypatch):
    broker = PaperBroker(redis)
    await redis.set(REDIS_KEY_PAPER_CASH, 101000.0)  # proceeds of the short sale
    await _seed_position(redis, "ETH/USD", "short", -0.5, 2000.0)
    await redis.set(
        REDIS_KEY_PRICES.format(symbol="ETH/USD"), json.dumps({FieldName.PRICE: 1800.0})
    )
    monkeypatch.setattr(positions_module, "get_paper_broker", lambda: broker)

    payload = await positions_module.get_account()

    # equity = 101000 + (−0.5 × 1800) = 100100 → the short is +$100 in profit
    assert payload[FieldName.EQUITY] == pytest.approx(100100.0)
    assert payload[FieldName.TOTAL_PNL] == pytest.approx(100.0)


async def test_account_falls_back_to_position_mark_when_cache_empty(redis, monkeypatch):
    broker = PaperBroker(redis)
    await redis.set(REDIS_KEY_PAPER_CASH, 99950.0)
    await _seed_position(redis, "AAPL", "long", 1.0, 50.0)
    # No live price cached → fall back to the position's stored current_price.
    monkeypatch.setattr(positions_module, "get_paper_broker", lambda: broker)

    payload = await positions_module.get_account()

    assert payload[FieldName.EQUITY] == pytest.approx(99950.0 + 50.0)


async def test_account_degrades_when_broker_read_fails(redis, monkeypatch):
    broker = PaperBroker(redis)

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(broker, "get_cash", _boom)
    monkeypatch.setattr(positions_module, "get_paper_broker", lambda: broker)

    payload = await positions_module.get_account()

    assert payload[FieldName.SOURCE] == "unavailable"
    assert payload[FieldName.CASH] is None
