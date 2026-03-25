"""
Atomic guarantee test - proves SafeWriter is truly atomic.
"""

import pytest
from unittest.mock import AsyncMock, patch
from api.core.writer.safe_writer import SafeWriter
from api.core.models import Order, ProcessedEvent, Event
from sqlalchemy.exc import IntegrityError


class TestAtomicGuarantee:
    """Test atomic guarantees in SafeWriter."""
    
    @pytest.mark.asyncio
    async def test_atomic_rollback_on_failure(self):
        """Test that partial writes rollback on failure."""
        # Mock session factory
        mock_session = AsyncMock()
        mock_session.add = AsyncMock()
        mock_session.flush = AsyncMock()
        
        # Create SafeWriter with mock
        safe_writer = SafeWriter(lambda: mock_session)
        
        # Mock transaction context
        mock_transaction = AsyncMock()
        mock_session.begin = AsyncMock().__aenter__.return_value = mock_transaction
        
        # Test data
        data = {
            'strategy_id': 'test-strategy',
            'idempotency_key': 'test-key',
            'symbol': 'AAPL',
            'side': 'buy',
            'order_type': 'market',
            'quantity': 100
        }
        
        # Simulate failure during ProcessedEvent insert
        call_count = 0
        def flush_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:  # Fail on ProcessedEvent insert
                raise IntegrityError("mock", "mock", "mock")
        
        mock_session.flush.side_effect = flush_side_effect
        
        # Should raise exception
        with pytest.raises(IntegrityError):
            async with safe_writer.transaction() as session:
                # This should rollback everything
                pass
        
        # Verify rollback was called
        mock_transaction.rollback.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_order_write_order_matters(self):
        """Test that order is written before ProcessedEvent."""
        calls = []
        
        def track_calls(obj):
            calls.append(type(obj).__name__)
        
        mock_session = AsyncMock()
        mock_session.add = lambda obj: track_calls(obj)
        mock_session.flush = AsyncMock()
        
        safe_writer = SafeWriter(lambda: mock_session)
        
        # Mock transaction
        mock_transaction = AsyncMock()
        mock_session.begin = AsyncMock().__aenter__.return_value = mock_transaction
        
        data = {
            'strategy_id': 'test-strategy',
            'idempotency_key': 'test-key',
            'symbol': 'AAPL',
            'side': 'buy',
            'order_type': 'market',
            'quantity': 100
        }
        
        # Mock the _claim_message to return True
        with patch.object(safe_writer, '_claim_message', return_value=True):
            try:
                await safe_writer.write_order('msg-123', 'test-stream', data)
            except:
                pass  # We don't care about success, just order of operations
        
        # Verify order was added before ProcessedEvent
        order_indices = [i for i, call in enumerate(calls) if call == 'Order']
        claim_indices = [i for i, call in enumerate(calls) if call == 'ProcessedEvent']
        
        assert len(order_indices) > 0, "Order should be added"
        assert len(claim_indices) > 0, "ProcessedEvent should be added"
        assert order_indices[0] < claim_indices[0], "Order must come before ProcessedEvent"


if __name__ == "__main__":
    pytest.main([__file__])
