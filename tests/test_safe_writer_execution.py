"""
SafeWriter Execution Tests - Execution and position updates.
"""

import pytest
from decimal import Decimal
from sqlalchemy import select


class TestExecutionFlow:
    """Test complete execution flow with position updates."""
    
    @pytest.mark.asyncio
    async def test_execution_updates_order(self, safe_writer, test_strategy, db_session):
        """Execution should update order status."""
        from api.core.models import Order
        
        # First create an order
        order_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "idempotency_key": "exec-order-1"
        }
        
        await safe_writer.write_order("msg-exec-1", "orders", order_data)
        
        # Get the order ID
        orders_result = await db_session.execute(select(Order))
        order = orders_result.scalar_one()
        
        # Now execute it
        execution_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "order_id": str(order.id),
            "filled_quantity": 100,
            "filled_price": 150.50,
            "new_quantity": 100,
            "new_avg_cost": 150.50,
            "market_value": 15050.00,
            "unrealized_pnl": 0
        }
        
        result = await safe_writer.write_execution("msg-exec-2", "executions", execution_data)
        assert result is True
        
        # Verify order updated
        await db_session.refresh(order)
        assert order.status == "filled"
        assert order.filled_quantity == Decimal("100")
        assert order.filled_price == Decimal("150.50")
    
    @pytest.mark.asyncio
    async def test_execution_creates_position(self, safe_writer, test_strategy, db_session):
        """Execution should create position."""
        from api.core.models import Order, Position
        
        # Create order
        order_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "MSFT",
            "side": "buy",
            "order_type": "market",
            "quantity": 50,
            "idempotency_key": "exec-pos-1"
        }
        
        await safe_writer.write_order("msg-pos-1", "orders", order_data)
        
        orders_result = await db_session.execute(select(Order))
        order = orders_result.scalar_one()
        
        # Execute
        execution_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "MSFT",
            "order_id": str(order.id),
            "filled_quantity": 50,
            "filled_price": 300.00,
            "new_quantity": 50,
            "new_avg_cost": 300.00,
            "market_value": 15000.00,
            "unrealized_pnl": 0
        }
        
        await safe_writer.write_execution("msg-pos-2", "executions", execution_data)
        
        # Verify position created
        positions_result = await db_session.execute(select(Position))
        position = positions_result.scalar_one()
        
        assert position.symbol == "MSFT"
        assert position.quantity == Decimal("50")
        assert position.avg_cost == Decimal("300.00")
        assert position.market_value == Decimal("15000.00")
    
    @pytest.mark.asyncio
    async def test_execution_updates_position(self, safe_writer, test_strategy, db_session):
        """Multiple executions should update same position."""
        from api.core.models import Order, Position
        
        # First execution - create position
        order1_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "TSLA",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "exec-update-1"
        }
        
        await safe_writer.write_order("msg-upd-1", "orders", order1_data)
        orders_result = await db_session.execute(select(Order))
        order1 = orders_result.scalars().first()
        
        exec1_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "TSLA",
            "order_id": str(order1.id),
            "filled_quantity": 10,
            "filled_price": 200.00,
            "new_quantity": 10,
            "new_avg_cost": 200.00,
            "market_value": 2000.00,
            "unrealized_pnl": 0
        }
        
        await safe_writer.write_execution("msg-upd-2", "executions", exec1_data)
        
        # Second execution - update position
        order2_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "TSLA",
            "side": "buy",
            "order_type": "market",
            "quantity": 5,
            "idempotency_key": "exec-update-2"
        }
        
        await safe_writer.write_order("msg-upd-3", "orders", order2_data)
        orders_result = await db_session.execute(select(Order))
        orders = orders_result.scalars().all()
        order2 = [o for o in orders if o.idempotency_key == "exec-update-2"][0]
        
        exec2_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "TSLA",
            "order_id": str(order2.id),
            "filled_quantity": 5,
            "filled_price": 210.00,
            "new_quantity": 15,
            "new_avg_cost": 203.33,  # Weighted average
            "market_value": 3049.95,
            "unrealized_pnl": 50.05
        }
        
        await safe_writer.write_execution("msg-upd-4", "executions", exec2_data)
        
        # Verify single position with updated values
        positions_result = await db_session.execute(select(Position))
        positions = positions_result.scalars().all()
        assert len(positions) == 1
        
        position = positions[0]
        assert position.quantity == Decimal("15")
        assert position.avg_cost == Decimal("203.33")
    
    @pytest.mark.asyncio
    async def test_execution_nonexistent_order_fails(self, safe_writer, test_strategy):
        """Execution with non-existent order should fail."""
        
        execution_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "order_id": "fake-order-id-12345",
            "filled_quantity": 10,
            "filled_price": 150.00,
            "new_quantity": 10,
            "new_avg_cost": 150.00,
            "market_value": 1500.00,
            "unrealized_pnl": 0
        }
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_execution("msg-fail-1", "executions", execution_data)
        
        assert "not found" in str(exc_info.value).lower()


class TestExecutionValidation:
    """Test execution validation."""
    
    @pytest.mark.asyncio
    async def test_execution_missing_order_id(self, safe_writer, test_strategy):
        """Execution without order_id should fail."""
        
        execution_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            # missing order_id
            "filled_quantity": 10,
            "filled_price": 150.00,
            "new_quantity": 10,
            "new_avg_cost": 150.00,
            "market_value": 1500.00,
            "unrealized_pnl": 0
        }
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_execution("msg-val-1", "executions", execution_data)
        
        assert "order_id" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_execution_missing_symbol(self, safe_writer, test_strategy):
        """Execution without symbol should fail."""
        
        execution_data = {
            "strategy_id": str(test_strategy.id),
            # missing symbol
            "order_id": "some-id",
            "filled_quantity": 10,
            "filled_price": 150.00,
            "new_quantity": 10,
            "new_avg_cost": 150.00,
            "market_value": 1500.00,
            "unrealized_pnl": 0
        }
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_execution("msg-val-2", "executions", execution_data)
        
        assert "symbol" in str(exc_info.value).lower()


class TestExecutionDecimalPrecision:
    """Test execution decimal precision."""
    
    @pytest.mark.asyncio
    async def test_execution_maintains_precision(self, safe_writer, test_strategy, db_session):
        """Execution should maintain decimal precision."""
        from api.core.models import Order, Position
        
        order_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "BTC",
            "side": "buy",
            "order_type": "market",
            "quantity": 0.12345678,
            "idempotency_key": "exec-decimal-1"
        }
        
        await safe_writer.write_order("msg-dec-1", "orders", order_data)
        
        orders_result = await db_session.execute(select(Order))
        order = orders_result.scalar_one()
        
        execution_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "BTC",
            "order_id": str(order.id),
            "filled_quantity": 0.12345678,
            "filled_price": 45000.12345678,
            "new_quantity": 0.12345678,
            "new_avg_cost": 45000.12345678,
            "market_value": 5555.55555555,
            "unrealized_pnl": 0.00000001
        }
        
        await safe_writer.write_execution("msg-dec-2", "executions", execution_data)
        
        positions_result = await db_session.execute(select(Position))
        position = positions_result.scalar_one()
        
        assert position.quantity == Decimal("0.12345678")
        assert position.avg_cost == Decimal("45000.12345678")
        assert position.market_value == Decimal("5555.55555555")
