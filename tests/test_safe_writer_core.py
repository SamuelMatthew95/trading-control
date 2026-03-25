"""
Core SafeWriter Tests - Exactly-once processing, atomicity, validation.

These tests prove the critical guarantees:
1. Exactly-once processing (ProcessedEvent dedup)
2. Atomic transactions
3. Idempotency key enforcement
4. Payload validation
"""

import pytest
import asyncio
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def has_pgvector(db_session):
    """Check if pgvector extension is available."""
    try:
        from sqlalchemy import text
        result = db_session.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
        return result.scalar() is not None
    except Exception:
        return False


class TestExactlyOnceProcessing:
    """Test exactly-once message processing via ProcessedEvent."""
    
    @pytest.mark.asyncio
    async def test_write_order_exactly_once(self, safe_writer, test_strategy, db_session):
        """Same message ID should NEVER write twice."""
        from api.core.models import Order, ProcessedEvent
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "price": 150.00,
            "idempotency_key": "idem-test-1",
            "exchange": "NYSE",
            "metadata": {}
        }
        
        msg_id = "msg-1"
        
        # First write should succeed
        result1 = await safe_writer.write_order(msg_id, "orders", data)
        assert result1 is True
        
        # Second write with same msg_id should be blocked
        result2 = await safe_writer.write_order(msg_id, "orders", data)
        assert result2 is False
        
        # Verify only one order exists
        orders_result = await db_session.execute(select(Order))
        orders = orders_result.scalars().all()
        assert len(orders) == 1
        
        # Verify only one ProcessedEvent exists
        events_result = await db_session.execute(select(ProcessedEvent))
        events = events_result.scalars().all()
        assert len(events) == 1
        assert events[0].msg_id == msg_id
    
    @pytest.mark.asyncio
    async def test_different_msg_ids_allowed(self, safe_writer, test_strategy, db_session):
        """Different message IDs should create separate orders."""
        from api.core.models import Order
        
        data1 = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "idem-test-2",
            "metadata": {}
        }
        
        data2 = {
            "strategy_id": str(test_strategy.id),
            "symbol": "MSFT",
            "side": "buy",
            "order_type": "market",
            "quantity": 5,
            "idempotency_key": "idem-test-3",
            "metadata": {}
        }
        
        # Both should succeed
        result1 = await safe_writer.write_order("msg-2", "orders", data1)
        result2 = await safe_writer.write_order("msg-3", "orders", data2)
        
        assert result1 is True
        assert result2 is True
        
        # Verify two orders exist
        orders_result = await db_session.execute(select(Order))
        orders = orders_result.scalars().all()
        assert len(orders) == 2


class TestAtomicTransactions:
    """Test atomic transaction behavior."""
    
    @pytest.mark.asyncio
    async def test_order_rollback_on_error(self, safe_writer, test_strategy, db_session):
        """If validation fails, NOTHING should be written."""
        from api.core.models import Order, ProcessedEvent
        
        # Missing required fields
        bad_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            # missing side, order_type, quantity
        }
        
        msg_id = "msg-error-1"
        
        # Should raise ValueError
        with pytest.raises(ValueError):
            await safe_writer.write_order(msg_id, "orders", bad_data)
        
        # Verify NOTHING was written
        orders_result = await db_session.execute(select(Order))
        orders = orders_result.scalars().all()
        assert len(orders) == 0
        
        events_result = await db_session.execute(select(ProcessedEvent))
        events = events_result.scalars().all()
        assert len(events) == 0
    
    @pytest.mark.asyncio
    async def test_execution_requires_existing_order(self, safe_writer, test_strategy, db_session):
        """Execution must fail if order doesn't exist."""
        from api.core.models import Position
        
        execution_data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "order_id": "non-existent-order-id",
            "filled_quantity": 10,
            "filled_price": 150.00,
            "new_quantity": 10,
            "new_avg_cost": 150.00,
            "market_value": 1500.00,
            "unrealized_pnl": 0
        }
        
        msg_id = "msg-exec-1"
        
        # Should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_execution(msg_id, "executions", execution_data)
        
        assert "not found" in str(exc_info.value).lower()
        
        # Verify position wasn't created
        positions_result = await db_session.execute(select(Position))
        positions = positions_result.scalars().all()
        assert len(positions) == 0


class TestIdempotencyKey:
    """Test idempotency key enforcement."""
    
    @pytest.mark.asyncio
    async def test_missing_idempotency_key_fails(self, safe_writer, test_strategy):
        """Order without idempotency_key should fail."""
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            # missing idempotency_key
        }
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_order("msg-no-idem", "orders", data)
        
        assert "idempotency_key" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_duplicate_idempotency_key_blocked(self, safe_writer, test_strategy, db_session):
        """Same idempotency_key should not create duplicate orders."""
        from api.core.models import Order
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "duplicate-idem"
        }
        
        # First write succeeds
        result1 = await safe_writer.write_order("msg-10", "orders", data)
        assert result1 is True
        
        # Try same idempotency key with different message
        result2 = await safe_writer.write_order("msg-11", "orders", data)
        
        # Second should be blocked
        assert result2 is False
        
        # Verify only one order
        orders_result = await db_session.execute(select(Order))
        orders = orders_result.scalars().all()
        assert len(orders) == 1


class TestPayloadValidation:
    """Test payload validation."""
    
    @pytest.mark.vector
    @pytest.mark.asyncio
    async def test_invalid_embedding_size_rejected(self, safe_writer, db_session):
        """Embedding must be exactly 1536 floats."""
        # Skip if pgvector not available
        if not has_pgvector(db_session):
            pytest.skip("pgvector not installed")
        
        data = {
            "content": "test content",
            "content_type": "note",
            "embedding": [1.0, 2.0, 3.0]  # WRONG SIZE - should be 1536
        }
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_vector_memory("msg-vector-1", "vector", data)
        
        assert "1536" in str(exc_info.value)
    
    @pytest.mark.vector
    @pytest.mark.asyncio
    async def test_non_numeric_embedding_rejected(self, safe_writer, db_session):
        """Embedding must contain only numeric values."""
        # Skip if pgvector not available
        if not has_pgvector(db_session):
            pytest.skip("pgvector not installed")
        
        data = {
            "content": "test content",
            "content_type": "note",
            "embedding": ["not", "a", "number"] + [0.0] * 1533  # Wrong type
        }
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_vector_memory("msg-vector-2", "vector", data)
        
        assert "non-numeric" in str(exc_info.value).lower() or "embedding" in str(exc_info.value).lower()
    
    @pytest.mark.vector
    @pytest.mark.asyncio
    async def test_valid_embedding_accepted(self, safe_writer, db_session):
        """Valid 1536-dim embedding should be accepted."""
        from api.core.models import VectorMemory
        
        # Skip if pgvector not available
        if not has_pgvector(db_session):
            pytest.skip("pgvector not installed")
        
        # Create valid 1536-dim embedding
        valid_embedding = [float(i) for i in range(1536)]
        
        data = {
            "content": "test content",
            "content_type": "note",
            "embedding": valid_embedding,
            "metadata": {}
        }
        
        result = await safe_writer.write_vector_memory("msg-vector-3", "vector", data)
        assert result is True
        
        # Verify it was written
        vectors_result = await db_session.execute(select(VectorMemory))
        vectors = vectors_result.scalars().all()
        assert len(vectors) == 1
    
    @pytest.mark.asyncio
    async def test_missing_required_fields_rejected(self, safe_writer, test_strategy):
        """Missing required fields should be rejected."""
        
        # Missing symbol
        data = {
            "strategy_id": str(test_strategy.id),
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "test-missing"
        }
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_order("msg-missing", "orders", data)
        
        assert "symbol" in str(exc_info.value).lower()


class TestConcurrency:
    """Test concurrent write behavior."""
    
    @pytest.mark.asyncio
    async def test_concurrent_same_idempotency(self, safe_writer, test_strategy, db_session):
        """Only one of concurrent writes with same idempotency_key should succeed."""
        from api.core.models import Order
        
        data = {
            "strategy_id": str(test_strategy.id),
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 10,
            "idempotency_key": "concurrent-idem"
        }
        
        async def try_write(msg_suffix):
            return await safe_writer.write_order(f"msg-concurrent-{msg_suffix}", "orders", data)
        
        # Try 5 concurrent writes
        results = await asyncio.gather(*[try_write(i) for i in range(5)])
        
        # Exactly one should succeed
        success_count = sum(1 for r in results if r)
        assert success_count == 1
        
        # Verify only one order
        orders_result = await db_session.execute(select(Order))
        orders = orders_result.scalars().all()
        assert len(orders) == 1
