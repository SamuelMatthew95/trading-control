"""
Tests for stream processing logic - pure unit tests without infrastructure.
"""

import pytest
from api.core.stream_logic import MessageProcessor, BackpressureController
from api.core.schemas import ProcessResult


class TestMessageProcessor:
    """Test pure message processing logic."""
    
    def test_validate_message_success(self):
        processor = MessageProcessor()
        
        # Valid message
        data = {'msg_id': 'test-123', 'symbol': 'AAPL'}
        result = processor.validate_message(data)
        
        assert result.success is True
        assert result.retryable is False
    
    def test_validate_message_missing_fields(self):
        processor = MessageProcessor()
        
        # Missing msg_id
        data = {'symbol': 'AAPL'}
        result = processor.validate_message(data)
        
        assert result.success is False
        assert result.retryable is False
        assert 'Missing required field' in result.message
    
    def test_process_order_message_success(self):
        processor = MessageProcessor()
        
        # Valid order
        data = {
            'msg_id': 'test-123',
            'symbol': 'AAPL',
            'side': 'buy',
            'quantity': '100'
        }
        result = processor.process_order_message('test-123', data)
        
        assert result.success is True
        assert processor.processed_count == 1
    
    def test_process_order_message_invalid_side(self):
        processor = MessageProcessor()
        
        # Invalid side
        data = {
            'msg_id': 'test-123',
            'symbol': 'AAPL',
            'side': 'invalid',
            'quantity': '100'
        }
        result = processor.process_order_message('test-123', data)
        
        assert result.success is False
        assert result.retryable is False
        assert 'Invalid side' in result.message
    
    def test_process_order_message_invalid_quantity(self):
        processor = MessageProcessor()
        
        # Invalid quantity
        data = {
            'msg_id': 'test-123',
            'symbol': 'AAPL',
            'side': 'buy',
            'quantity': 'invalid'
        }
        result = processor.process_order_message('test-123', data)
        
        assert result.success is False
        assert result.retryable is False
        assert 'Invalid quantity' in result.message
    
    def test_create_dlq_entry(self):
        processor = MessageProcessor()
        
        message = {
            'stream': 'orders',
            'message_id': '123',
            'data': {'test': 'data'}
        }
        
        dlq_entry = processor.create_dlq_entry(message, 'Test error')
        
        assert dlq_entry['original_stream'] == 'orders'
        assert dlq_entry['original_id'] == '123'
        assert dlq_entry['error'] == 'Test error'
        assert 'timestamp' in dlq_entry


class TestBackpressureController:
    """Test pure backpressure logic."""
    
    def test_should_apply_backpressure_db_error(self):
        controller = BackpressureController()
        
        # DB connection error
        error = Exception("Connection timeout")
        assert controller.should_apply_backpressure(error) is True
    
    def test_should_apply_backpressure_validation_error(self):
        controller = BackpressureController()
        
        # Validation error
        error = ValueError("Invalid data")
        assert controller.should_apply_backpressure(error) is False
    
    def test_record_error_with_backpressure(self):
        controller = BackpressureController()
        
        # Record DB error
        error = Exception("Connection timeout")
        backoff = controller.record_error(error)
        
        assert backoff > 1.0  # Should increase
        assert controller.consecutive_db_errors == 1
    
    def test_circuit_breaker_opens(self):
        controller = BackpressureController()
        controller.circuit_breaker_threshold = 2
        
        # Record enough errors to trigger circuit breaker
        for i in range(2):
            controller.record_error(Exception("Connection timeout"))
        
        assert controller.is_circuit_breaker_open() is True
    
    def test_reset_clears_errors(self):
        controller = BackpressureController()
        
        # Record some errors
        controller.record_error(Exception("Connection timeout"))
        assert controller.error_count > 0
        
        # Reset
        controller.reset()
        assert controller.error_count == 0
        assert controller.consecutive_db_errors == 0
        assert controller.backoff_seconds == 1.0


if __name__ == "__main__":
    pytest.main([__file__])
