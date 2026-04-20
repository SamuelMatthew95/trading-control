"""Tests for PaperBroker — slippage, cash/position updates, and flat positions."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from api.constants import DEFAULT_PAPER_CASH
from api.services.execution.brokers.paper import PaperBroker

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def broker(redis):
    return PaperBroker(redis_client=redis)


async def test_place_order_buy_fill_price_above_requested(broker):
    """Buy fill_price must be strictly greater than the requested price (slippage adds cost)."""
    result = await broker.place_order(symbol="BTC/USD", side="buy", qty=1.0, price=50000.0)
    assert result["fill_price"] > 50000.0, (
        f"Buy fill_price {result['fill_price']} should be above requested 50000.0"
    )


async def test_place_order_sell_fill_price_below_requested(broker):
    """Sell fill_price must be strictly less than the requested price (slippage reduces proceeds)."""
    result = await broker.place_order(symbol="BTC/USD", side="sell", qty=1.0, price=50000.0)
    assert result["fill_price"] < 50000.0, (
        f"Sell fill_price {result['fill_price']} should be below requested 50000.0"
    )


async def test_place_order_slippage_is_proportional(broker):
    """Slippage fraction must be 0.0001–0.0005 of the price, NOT a flat $0.0001–$0.0005."""
    price = 50000.0
    result = await broker.place_order(symbol="BTC/USD", side="buy", qty=1.0, price=price)
    fill_price = result["fill_price"]

    # Absolute difference between fill and requested price
    abs_slippage = fill_price - price

    # With percentage-based slippage, abs_slippage must be in range [price*0.0001, price*0.0005]
    # i.e. [$5.00, $25.00] for a $50,000 price — NOT a flat $0.0001 to $0.0005
    min_expected = price * 0.0001
    max_expected = price * 0.0005
    assert abs_slippage >= min_expected, (
        f"Slippage {abs_slippage:.6f} is below {min_expected:.6f} — looks like flat, not percentage"
    )
    assert abs_slippage <= max_expected + 0.01, (  # small float rounding buffer
        f"Slippage {abs_slippage:.6f} is above {max_expected:.6f}"
    )


async def test_place_order_updates_cash_and_position(broker, redis):
    """After a buy, cash decreases and position is written to Redis."""
    price = 50000.0
    qty = 0.1
    result = await broker.place_order(symbol="BTC/USD", side="buy", qty=qty, price=price)
    fill_price = result["fill_price"]

    cash = await broker.get_cash()
    expected_cash = DEFAULT_PAPER_CASH - (qty * fill_price)
    assert cash == pytest.approx(expected_cash, rel=1e-6)

    position = await broker.get_position("BTC/USD")
    assert position["symbol"] == "BTC/USD"
    assert float(position["qty"]) == pytest.approx(qty, rel=1e-6)
    assert position["side"] == "long"


async def test_get_position_returns_flat_when_absent(broker):
    """get_position returns a flat position dict when no position exists in Redis."""
    position = await broker.get_position("ETH/USD")
    assert position["symbol"] == "ETH/USD"
    assert float(position["qty"]) == 0.0
    assert position["side"] == "flat"
    assert float(position["entry_price"]) == 0.0
