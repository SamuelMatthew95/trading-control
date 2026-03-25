"""
Test schema mapping between consumers and SafeWriter models.
Tests for unconsumed column names and proper field mapping.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any

from api.core.writer.safe_writer import SafeWriter
from api.core.models import SystemMetrics, Order, AgentLog, VectorMemory
from api.services.system_metrics_consumer import SystemMetricsConsumer
from api.services.system_metrics_handler import handle_system_metric
from api.core.schemas import ProcessResult


pytestmark = pytest.mark.timeout(10)


class TestSchemaMapping:
    """Test schema mapping between incoming messages and database models."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory for SafeWriter."""
        return AsyncMock()
    
    @pytest.fixture
    def safe_writer(self, mock_session_factory):
        """Create SafeWriter instance."""
        return SafeWriter(mock_session_factory)
    
    @pytest.fixture
    def mock_session(self, mock_session_factory):
        """Mock database session."""
        session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = session
        mock_session_factory.return_value.__aexit__.return_value = None
        return session


class TestSystemMetricsMapping:
    """Test SystemMetrics schema mapping."""
    
    @pytest.mark.asyncio
    async def test_system_metric_valid_message(self, safe_writer, mock_session):
        """Test valid system metric message maps correctly."""
        msg_id = "test-msg-123"
        stream = "system_metrics"
        
        # Valid incoming message (from production logs)
        data = {
            "type": "system_metric",
            "metric_name": "stream_lag:signals",
            "value": 0.0,
            "unit": "seconds",
            "tags": {"stream": "signals"},
            "timestamp": "2026-03-25T07:13:06.308008Z",
            "schema_version": "v2",
            "source": "system_monitor"
        }
        
        # Mock successful database operations
        mock_session.execute.return_value = None
        mock_session.flush.return_value = None
        
        with patch.object(safe_writer, '_claim_message', return_value=True):
            result = await safe_writer.write_system_metric(msg_id, stream, data)
            
            assert result is True
            
            # Verify the data was mapped correctly
            call_args = mock_session.execute.call_args[0][0]
            inserted_data = call_args.compile().params
            
            # Check field mappings
            assert inserted_data['metric_name'] == "stream_lag:signals"
            assert inserted_data['metric_value'] == 0.0  # value -> metric_value
            assert inserted_data['metric_unit'] == "seconds"  # unit -> metric_unit
            assert inserted_data['tags'] == {"stream": "signals"}
            assert inserted_data['schema_version'] == "v2"
            assert inserted_data['source'] == "system_monitor"
    
    @pytest.mark.asyncio
    async def test_system_metric_extra_keys_ignored(self, safe_writer, mock_session):
        """Test that extra keys in message are ignored, not passed to model."""
        msg_id = "test-msg-456"
        stream = "system_metrics"
        
        # Message with extra keys that shouldn't reach the model
        data = {
            "metric_name": "cpu_usage",
            "value": 75.5,
            "extra_field": "should_be_ignored",
            "another_extra": {"nested": "data"},
            "schema_version": "v2",
            "source": "monitor"
        }
        
        mock_session.execute.return_value = None
        mock_session.flush.return_value = None
        
        with patch.object(safe_writer, '_claim_message', return_value=True):
            result = await safe_writer.write_system_metric(msg_id, stream, data)
            
            assert result is True
            
            # Verify only valid fields were passed to model
            call_args = mock_session.execute.call_args[0][0]
            inserted_data = call_args.compile().params
            
            # Should have only valid model fields
            assert 'metric_name' in inserted_data
            assert 'metric_value' in inserted_data
            assert 'extra_field' not in inserted_data
            assert 'another_extra' not in inserted_data
    
    @pytest.mark.asyncio
    async def test_system_metric_missing_required_field(self, safe_writer):
        """Test missing required field raises error."""
        msg_id = "test-msg-789"
        stream = "system_metrics"
        
        # Missing required 'value' field
        data = {
            "metric_name": "memory_usage",
            "schema_version": "v2",
            "source": "monitor"
        }
        
        with pytest.raises(ValueError, match="Missing required field: value"):
            await safe_writer.write_system_metric(msg_id, stream, data)
    
    @pytest.mark.asyncio
    async def test_system_metric_handler_integration(self):
        """Test system_metrics_handler maps data correctly for SafeWriter."""
        msg_id = "handler-test-123"
        stream = "system_metrics"
        data = {
            "metric_name": "test_metric",
            "value": 42.0,
            "unit": "percent"
        }
        
        with patch('api.services.system_metrics_handler.SafeWriter') as mock_writer_class:
            mock_writer = AsyncMock()
            mock_writer_class.return_value = mock_writer
            mock_writer.write_system_metric.return_value = True
            
            result = await handle_system_metric(msg_id, stream, data, "trace-123")
            
            assert result.success is True
            assert "Processed metric: test_metric" in result.message
            
            # Verify the data passed to SafeWriter is correctly mapped
            call_args = mock_writer.write_system_metric.call_args[0]
            passed_msg_id, passed_stream, passed_data = call_args
            
            assert passed_msg_id == msg_id
            assert passed_stream == stream
            assert passed_data['metric_name'] == "test_metric"
            assert passed_data['value'] == 42.0  # Handler keeps 'value' for SafeWriter to map


class TestOrderMapping:
    """Test Order schema mapping."""
    
    @pytest.mark.asyncio
    async def test_order_valid_message(self, safe_writer, mock_session):
        """Test valid order message maps correctly."""
        msg_id = "order-123"
        stream = "orders"
        
        data = {
            "strategy_id": "strategy-uuid",
            "symbol": "BTC/USD",
            "side": "buy",
            "order_type": "limit",
            "quantity": "1.5",
            "price": "50000",
            "metadata": {"exchange": "binance"},
            "idempotency_key": "unique-key-123",
            "schema_version": "v2",
            "source": "trading_bot"
        }
        
        # Mock the order creation and claim
        mock_order = MagicMock()
        mock_order.id = "order-uuid"
        
        with patch('api.core.writer.safe_writer.Order') as mock_order_class, \
             patch.object(safe_writer, '_claim_message', return_value=True):
            
            mock_order_class.return_value = mock_order
            mock_session.add.return_value = None
            mock_session.flush.return_value = None
            mock_session.execute.return_value = None
            
            result = await safe_writer.write_order(msg_id, stream, data)
            
            assert result is True
            
            # Verify Order was created with correct field mapping
            mock_order_class.assert_called_once()
            call_kwargs = mock_order_class.call_args[1]
            
            assert call_kwargs['metadata'] == {"exchange": "binance"}  # metadata -> order_metadata
            assert call_kwargs['strategy_id'] == "strategy-uuid"
            assert call_kwargs['symbol'] == "BTC/USD"
            assert call_kwargs['idempotency_key'] == "unique-key-123"


class TestAgentLogMapping:
    """Test AgentLog schema mapping."""
    
    @pytest.mark.asyncio
    async def test_agent_log_valid_message(self, safe_writer, mock_session):
        """Test valid agent log message maps correctly."""
        msg_id = "log-123"
        stream = "agent_logs"
        
        data = {
            "agent_id": "agent-run-uuid",  # This maps to agent_run_id
            "level": "INFO",
            "message": "Task completed successfully",
            "step_name": "process_trade",
            "step_data": {"trade_id": "trade-123"},
            "trace_id": "trace-456",
            "schema_version": "v2",
            "source": "agent_executor"
        }
        
        mock_session.execute.return_value = None
        mock_session.flush.return_value = None
        
        with patch.object(safe_writer, '_claim_message', return_value=True):
            result = await safe_writer.write_agent_log(msg_id, stream, data)
            
            assert result is True
            
            # Verify the data was mapped correctly
            call_args = mock_session.execute.call_args[0][0]
            inserted_data = call_args.compile().params
            
            # Check field mappings
            assert inserted_data['agent_run_id'] == "agent-run-uuid"  # agent_id -> agent_run_id
            assert inserted_data['log_level'] == "INFO"  # level -> log_level
            assert inserted_data['message'] == "Task completed successfully"
            assert inserted_data['step_name'] == "process_trade"
            assert inserted_data['step_data'] == {"trade_id": "trade-123"}
            assert inserted_data['trace_id'] == "trace-456"
            assert inserted_data['schema_version'] == "v2"
            assert inserted_data['source'] == "agent_executor"


class TestVectorMemoryMapping:
    """Test VectorMemory schema mapping."""
    
    @pytest.mark.asyncio
    async def test_vector_memory_valid_message(self, safe_writer, mock_session):
        """Test valid vector memory message maps correctly."""
        msg_id = "vector-123"
        stream = "vector_memory"
        
        # Create 1536-dimension embedding
        embedding = [0.1] * 1536
        
        data = {
            "content": "Trade analysis shows bullish trend",
            "content_type": "insight",
            "embedding": embedding,
            "metadata": {"analysis_type": "technical", "confidence": 0.85},
            "agent_id": "agent-uuid",
            "strategy_id": "strategy-uuid",
            "schema_version": "v2",
            "source": "analysis_agent"
        }
        
        mock_session.execute.return_value = None
        mock_session.flush.return_value = None
        
        with patch.object(safe_writer, '_claim_message', return_value=True):
            result = await safe_writer.write_vector_memory(msg_id, stream, data)
            
            assert result is True
            
            # Verify the data was mapped correctly
            call_args = mock_session.execute.call_args[0][0]
            inserted_data = call_args.compile().params
            
            # Check field mappings
            assert inserted_data['content'] == "Trade analysis shows bullish trend"
            assert inserted_data['content_type'] == "insight"
            assert inserted_data['embedding'] == embedding
            assert inserted_data['vector_metadata'] == {"analysis_type": "technical", "confidence": 0.85}  # metadata -> vector_metadata
            assert inserted_data['agent_id'] == "agent-uuid"
            assert inserted_data['strategy_id'] == "strategy-uuid"
            assert inserted_data['schema_version'] == "v2"
            assert inserted_data['source'] == "analysis_agent"
            
            # Verify invalid fields are not present
            assert 'metadata' not in inserted_data
            assert 'symbol' not in inserted_data
            assert 'relevance_score' not in inserted_data
    
    @pytest.mark.asyncio
    async def test_vector_memory_invalid_embedding(self, safe_writer):
        """Test invalid embedding raises error."""
        msg_id = "vector-bad-123"
        stream = "vector_memory"
        
        data = {
            "content": "Test content",
            "content_type": "memory",
            "embedding": [0.1, 0.2],  # Wrong size
            "schema_version": "v2",
            "source": "test"
        }
        
        with pytest.raises(ValueError, match="embedding must be 1536-length list"):
            await safe_writer.write_vector_memory(msg_id, stream, data)


class TestConsumerIntegration:
    """Test consumer integration with schema mapping."""
    
    @pytest.fixture
    def mock_bus(self):
        """Mock event bus."""
        return AsyncMock()
    
    @pytest.fixture
    def mock_dlq(self):
        """Mock DLQ manager."""
        return AsyncMock()
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis = AsyncMock()
        redis.get.return_value = None  # Kill switch not active
        return redis
    
    @pytest.mark.asyncio
    async def test_system_metrics_consumer_integration(self, mock_bus, mock_dlq, mock_redis):
        """Test SystemMetricsConsumer handles messages correctly."""
        consumer = SystemMetricsConsumer(mock_bus, mock_dlq, mock_redis)
        
        # Test data that previously caused "Unconsumed column names: value"
        data = {
            "type": "system_metric",
            "metric_name": "stream_lag:signals",
            "value": 0.0,
            "unit": "seconds",
            "tags": {"stream": "signals"},
            "timestamp": "2026-03-25T07:13:06.308008Z"
        }
        
        with patch('api.services.system_metrics_consumer.handle_system_metric') as mock_handler:
            mock_handler.return_value = ProcessResult(
                success=True,
                retryable=False,
                message="Processed metric: stream_lag:signals"
            )
            
            # Should not raise an exception
            await consumer.process(data)
            
            # Verify handler was called with correct data
            mock_handler.assert_called_once()
            call_args = mock_handler.call_args[0]
            msg_id, stream, passed_data, trace_id = call_args
            
            assert msg_id == "unknown"
            assert stream == "system_metrics"
            assert passed_data['value'] == 0.0
            assert passed_data['metric_name'] == "stream_lag:signals"


class TestSchemaValidation:
    """Test schema validation and error handling."""
    
    @pytest.fixture
    def safe_writer(self):
        """Create SafeWriter with mock session factory."""
        mock_session_factory = AsyncMock()
        return SafeWriter(mock_session_factory)
    
    def test_validate_schema_v2_success(self, safe_writer):
        """Test successful V2 schema validation."""
        valid_data = {
            "schema_version": "v2",
            "source": "test",
            "metric_name": "test_metric",
            "value": 42.0
        }
        
        # Should not raise
        safe_writer._validate_schema_v2(valid_data, 'SystemMetrics')
    
    def test_validate_schema_v2_missing_version(self, safe_writer):
        """Test validation fails without schema version."""
        invalid_data = {
            "source": "test",
            "metric_name": "test_metric",
            "value": 42.0
        }
        
        with pytest.raises(ValueError, match="Missing required field 'schema_version'"):
            safe_writer._validate_schema_v2(invalid_data, 'SystemMetrics')
    
    def test_validate_schema_v2_wrong_version(self, safe_writer):
        """Test validation fails with wrong schema version."""
        invalid_data = {
            "schema_version": "v1",
            "source": "test",
            "metric_name": "test_metric",
            "value": 42.0
        }
        
        with pytest.raises(ValueError, match="Invalid schema version 'v1'"):
            safe_writer._validate_schema_v2(invalid_data, 'SystemMetrics')
    
    def test_validate_payload_missing_required(self, safe_writer):
        """Test payload validation fails with missing required fields."""
        data = {
            "metric_name": "test_metric"
            # Missing 'value'
        }
        
        with pytest.raises(ValueError, match="Missing required field: value"):
            safe_writer.validate_payload(data, ['metric_name', 'value'])


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
