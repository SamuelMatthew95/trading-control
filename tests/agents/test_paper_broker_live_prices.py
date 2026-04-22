"""Tests for PaperBroker live price fetching functionality."""

import json
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import time

from api.constants import (
    STREAM_MARKET_TICKS,
    STREAM_TRADE_PERFORMANCE,
    STREAM_AGENT_LOGS,
    FieldName,
    REDIS_KEY_PAPER_POSITION,
    REDIS_KEY_PAPER_CASH,
    REDIS_KEY_PRICES,
)
from api.services.execution.brokers.paper import PaperBroker
from api.services.events import EventBus


@pytest.mark.asyncio
async def test_paperbroker_uses_live_price_for_buy():
    """Test that PaperBroker fetches live market price for BUY orders."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock live price from Redis
    live_price_data = {
        FieldName.PRICE: 385.50,
        "change": 2.50,
        FieldName.PCT: 0.65,
        FieldName.TS: 1640995200,
    }
    mock_redis.get.return_value = json.dumps(live_price_data)

    # Mock Redis operations for position and order management
    mock_redis.setnx.return_value = True
    mock_redis.get.return_value = json.dumps(live_price_data)
    mock_redis.set.return_value = True

    result = await broker.place_order("TSLA", "buy", 2.0, 380.0)

    # Verify live price was fetched
    mock_redis.get.assert_called_with(REDIS_KEY_PRICES.format(symbol="TSLA"))

    # Verify fill price is based on live price with slippage
    assert result[FieldName.FILL_PRICE] != 380.0  # Should not use input price
    assert result[FieldName.FILL_PRICE] > 385.50  # Should be live price + slippage
    assert result[FieldName.SIDE] == "buy"
    assert result["filled_qty"] == 2.0


@pytest.mark.asyncio
async def test_paperbroker_uses_live_price_for_sell():
    """Test that PaperBroker fetches live market price for SELL orders."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock live price from Redis
    live_price_data = {
        FieldName.PRICE: 375.25,
        "change": -1.25,
        FieldName.PCT: -0.33,
        FieldName.TS: 1640995200,
    }
    mock_redis.get.return_value = json.dumps(live_price_data)

    # Mock Redis operations
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("TSLA", "sell", 1.0, 380.0)

    # Verify live price was fetched
    mock_redis.get.assert_called_with(REDIS_KEY_PRICES.format(symbol="TSLA"))

    # Verify fill price is based on live price with slippage (negative for sell)
    assert result[FieldName.FILL_PRICE] != 380.0  # Should not use input price
    assert result[FieldName.FILL_PRICE] < 375.25  # Should be live price - slippage
    assert result[FieldName.SIDE] == "sell"
    assert result["filled_qty"] == 1.0


@pytest.mark.asyncio
async def test_paperbroker_fallback_to_input_price_when_live_unavailable():
    """Test that PaperBroker falls back to input price when live price fetch fails."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock Redis get to return None (no live price available)
    mock_redis.get.return_value = None

    # Mock Redis operations
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("TSLA", "buy", 1.0, 380.0)

    # Verify live price was attempted
    mock_redis.get.assert_called_with(REDIS_KEY_PRICES.format(symbol="TSLA"))

    # Verify fill price uses input price as fallback
    assert result[FieldName.FILL_PRICE] > 380.0  # Input price + slippage
    assert result[FieldName.FILL_PRICE] < 380.20  # Should be close to input price


@pytest.mark.asyncio
async def test_paperbroker_handles_invalid_live_price_data():
    """Test that PaperBroker handles invalid/empty live price data gracefully."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock Redis get to return invalid JSON
    mock_redis.get.return_value = "invalid_json_data"

    # Mock Redis operations
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("TSLA", "buy", 1.0, 380.0)

    # Verify live price was attempted
    mock_redis.get.assert_called_with(REDIS_KEY_PRICES.format(symbol="TSLA"))

    # Verify fill price falls back to input price
    assert result[FieldName.FILL_PRICE] > 380.0  # Input price + slippage


@pytest.mark.asyncio
async def test_paperbroker_handles_redis_exception_gracefully():
    """Test that PaperBroker handles Redis exceptions gracefully."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock Redis get to raise exception
    mock_redis.get.side_effect = Exception("Redis connection failed")

    # Mock Redis operations for other calls
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("TSLA", "buy", 1.0, 380.0)

    # Verify live price was attempted
    mock_redis.get.assert_called_with(REDIS_KEY_PRICES.format(symbol="TSLA"))

    # Verify fill price falls back to input price
    assert result[FieldName.FILL_PRICE] > 380.0  # Input price + slippage


@pytest.mark.asyncio
async def test_paperbroker_live_price_fetch_for_crypto_symbols():
    """Test that PaperBroker correctly fetches live prices for crypto symbols."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock live price for crypto symbol
    crypto_price_data = {
        FieldName.PRICE: 45000.75,
        "change": 125.50,
        FieldName.PCT: 0.28,
        FieldName.TS: 1640995200,
    }
    mock_redis.get.return_value = json.dumps(crypto_price_data)

    # Mock Redis operations
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("BTC/USD", "buy", 0.1, 44000.0)

    # Verify correct Redis key was used
    mock_redis.get.assert_called_with(REDIS_KEY_PRICES.format(symbol="BTC/USD"))

    # Verify fill price is based on live crypto price
    assert result[FieldName.FILL_PRICE] != 44000.0  # Should not use input price
    assert result[FieldName.FILL_PRICE] > 45000.75  # Should be live price + slippage


@pytest.mark.asyncio
async def test_paperbroker_live_price_fetch_for_stock_symbols():
    """Test that PaperBroker correctly fetches live prices for stock symbols."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock live price for stock symbol
    stock_price_data = {
        FieldName.PRICE: 155.25,
        "change": 2.75,
        FieldName.PCT: 1.80,
        FieldName.TS: 1640995200,
    }
    mock_redis.get.return_value = json.dumps(stock_price_data)

    # Mock Redis operations
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("AAPL", "sell", 10.0, 160.0)

    # Verify correct Redis key was used
    mock_redis.get.assert_called_with(REDIS_KEY_PRICES.format(symbol="AAPL"))

    # Verify fill price is based on live stock price
    assert result[FieldName.FILL_PRICE] != 160.0  # Should not use input price
    assert result[FieldName.FILL_PRICE] < 155.25  # Should be live price - slippage


@pytest.mark.asyncio
async def test_paperbroker_position_updated_with_live_price():
    """Test that position is updated with live price-based fill price."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock live price
    live_price_data = {
        FieldName.PRICE: 385.50,
        "change": 2.50,
        FieldName.PCT: 0.65,
        FieldName.TS: 1640995200,
    }
    mock_redis.get.return_value = json.dumps(live_price_data)

    # Mock Redis operations
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("TSLA", "buy", 2.0, 380.0)

    # Verify position was updated with live price-based fill price
    expected_position_key = REDIS_KEY_PAPER_POSITION.format(symbol="TSLA")
    mock_redis.set.assert_any_call(
        expected_position_key,
        pytest.helpers.anything  # JSON string with updated position
    )

    # Check that the position call includes the live price-based fill price
    position_calls = [call for call in mock_redis.set.call_args_list
                      if expected_position_key in str(call)]
    assert len(position_calls) > 0

    # Extract and verify the position data
    position_json = position_calls[0][0][1]
    position_data = json.loads(position_json)
    assert position_data[FieldName.ENTRY_PRICE] == result[FieldName.FILL_PRICE]
    assert position_data["current_price"] == result[FieldName.FILL_PRICE]


@pytest.mark.asyncio
async def test_paperbroker_cash_updated_with_live_price():
    """Test that cash is updated correctly based on live price-based execution."""

    mock_redis = AsyncMock()
    broker = PaperBroker(mock_redis)

    # Mock live price and existing cash
    live_price_data = {
        FieldName.PRICE: 385.50,
        "change": 2.50,
        FieldName.PCT: 0.65,
        FieldName.TS: 1640995200,
    }
    mock_redis.get.side_effect = [
        json.dumps(live_price_data),  # Live price fetch
        "10000.0",                   # Current cash
    ]

    # Mock Redis operations
    mock_redis.setnx.return_value = True
    mock_redis.set.return_value = True

    result = await broker.place_order("TSLA", "buy", 2.0, 380.0)

    # Verify cash was updated
    cash_key = REDIS_KEY_PAPER_CASH
    cash_calls = [call for call in mock_redis.set.call_args_list
                  if cash_key in str(call)]
    assert len(cash_calls) > 0

    # Cash should be reduced by (fill_price * quantity)
    expected_cash_reduction = result[FieldName.FILL_PRICE] * 2.0
    new_cash = 10000.0 - expected_cash_reduction

    # Verify the cash update call
    cash_update_call = cash_calls[0]
    actual_new_cash = float(cash_update_call[0][1])
    assert abs(actual_new_cash - new_cash) < 0.01  # Allow for small floating point differences
