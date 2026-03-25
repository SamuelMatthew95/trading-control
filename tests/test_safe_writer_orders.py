"""
SafeWriter Order Tests - Order-specific functionality.
"""

import pytest
from decimal import Decimal
from sqlalchemy import select


class TestOrderCreation:
    """Test order creation functionality."""
    
    @pytest.mark.asyncio
    async def test_order_basic_creation(self, safe_writer, test_strategy, db_session):
        """Basic order creation works."""
        from api.core.models import Order, Event
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "price": 150.50,
            "idempotency_key": "order-basic-1",
            "exchange": "NYSE",
            "metadata": {"test": True}
        }
        
        result = await safe_writer.write_order("msg-order-1", "orders", data)
        assert result is True
        
        # Verify order created
        orders_result = await db_session.execute(select(Order))
        order = orders_result.scalar_one()
        assert order.symbol == "AAPL"
        assert order.side == "buy"
        assert order.quantity == Decimal("100")
        assert order.price == Decimal("150.50")
        assert order.schema_version == "v2"
        
        # Verify event created
        events_result = await db_session.execute(select(Event))
        event = events_result.scalar_one()
        assert event.event_type == "order.created"
        assert event.entity_type == "order"
    
    @pytest.mark.asyncio
    async def test_order_without_price(self, safe_writer, test_strategy, db_session):
        """Market order without price should work."""
        from api.core.models import Order
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "GOOGL",
            "side": "sell",
            "order_type": "market",
            "quantity": 50,
            "idempotency_key": "order-no-price"
        }
        
        result = await safe_writer.write_order("msg-order-2", "orders", data)
        assert result is True
        
        orders_result = await db_session.execute(select(Order))
        order = orders_result.scalar_one()
        assert order.price is None
        assert order.order_type == "market"
    
    @pytest.mark.asyncio
    async def test_order_decimal_precision(self, safe_writer, test_strategy, db_session):
        """Order should maintain decimal precision."""
        from api.core.models import Order
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "BTC",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.12345678,
            "price": 45000.12345678,
            "idempotency_key": "order-decimal"
        }
        
        result = await safe_writer.write_order("msg-order-3", "orders", data)
        assert result is True
        
        orders_result = await db_session.execute(select(Order))
        order = orders_result.scalar_one()
        
        # Verify precision maintained
        assert order.quantity == Decimal("0.12345678")
        assert order.price == Decimal("45000.12345678")
    
    @pytest.mark.asyncio
    async def test_order_status_default(self, safe_writer, test_strategy, db_session):
        """Order should default to 'pending' status."""
        from api.core.models import Order
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "MSFT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 10,
            "price": 300.00,
            "idempotency_key": "order-status"
        }
        
        result = await safe_writer.write_order("msg-order-4", "orders", data)
        assert result is True
        
        orders_result = await db_session.execute(select(Order))
        order = orders_result.scalar_one()
        assert order.status == "pending"
        assert order.filled_quantity == Decimal("0")
        assert order.commission == Decimal("0")


class TestOrderSideValidation:
    """Test order side validation."""
    
    @pytest.mark.asyncio
    async def test_valid_buy_side(self, safe_writer, test_strategy):
        """Buy side should be accepted."""
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "side-buy"
        }
        
        result = await safe_writer.write_order("msg-side-1", "orders", data)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_valid_sell_side(self, safe_writer, test_strategy):
        """Sell side should be accepted."""
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "sell",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "side-sell"
        }
        
        result = await safe_writer.write_order("msg-side-2", "orders", data)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_invalid_side_rejected(self, safe_writer, test_strategy):
        """Invalid side should be rejected."""
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "invalid",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "side-invalid"
        }
        
        # Should raise ValueError due to enum validation
        with pytest.raises(ValueError):
            await safe_writer.write_order("msg-side-3", "orders", data)


class TestOrderTypeValidation:
    """Test order type validation."""
    
    @pytest.mark.asyncio
    async def test_market_order(self, safe_writer, test_strategy):
        """Market order type should be accepted."""
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "type-market"
        }
        
        result = await safe_writer.write_order("msg-type-1", "orders", data)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_limit_order(self, safe_writer, test_strategy):
        """Limit order type should be accepted."""
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": 10,
            "price": 150.00,
            "idempotency_key": "type-limit"
        }
        
        result = await safe_writer.write_order("msg-type-2", "orders", data)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_stop_order(self, safe_writer, test_strategy):
        """Stop order type should be accepted."""
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "sell",
            "order_type": "stop",
            "quantity": 10,
            "price": 140.00,
            "idempotency_key": "type-stop"
        }
        
        result = await safe_writer.write_order("msg-type-3", "orders", data)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_invalid_order_type_rejected(self, safe_writer, test_strategy):
        """Invalid order type should be rejected."""
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "invalid",
            "quantity": 10,
            "idempotency_key": "type-invalid"
        }
        
        # Should raise ValueError due to enum validation
        with pytest.raises(ValueError):
            await safe_writer.write_order("msg-type-4", "orders", data)
