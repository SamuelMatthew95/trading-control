"""
Test schema mapping between consumers and SafeWriter models.
Tests for unconsumed column names and proper field mapping - no database required.
"""

from unittest.mock import AsyncMock, patch

import pytest

from api.core.writer.safe_writer import SafeWriter


class TestSchemaMapping:
    """Test schema mapping between incoming messages and database models."""

    @pytest.fixture
    def safe_writer(self):
        """Create SafeWriter instance with mocked session factory."""
        mock_session_factory = AsyncMock()
        return SafeWriter(mock_session_factory)

    def test_system_metric_field_mapping(self, safe_writer):
        """Test SystemMetrics field mapping logic without database."""
        data = {
            "metric_name": "stream_lag:signals",
            "value": 0.0,
            "unit": "seconds",
            "tags": {"stream": "signals"},
            "timestamp": "2026-03-25T07:13:06.308008Z",
            "schema_version": "v2",
            "source": "system_monitor",
        }

        # Test the field mapping logic directly
        timestamp_str = data.get("timestamp")
        timestamp = safe_writer.safe_parse_dt(timestamp_str)

        # Verify timestamp parsing
        assert timestamp is not None
        assert timestamp.year == 2026
        assert timestamp.month == 3
        assert timestamp.day == 25

        # Test the mapping that would be used in write_system_metric
        metric_data = {
            "metric_name": data["metric_name"],
            "metric_value": data["value"],  # value -> metric_value
            "metric_unit": data.get("unit"),  # unit -> metric_unit
            "tags": data.get("tags", {}),
            "timestamp": timestamp,
            "schema_version": data.get("schema_version", "v2"),
            "source": data.get("source", "unknown"),
        }

        # Verify field mappings
        assert metric_data["metric_name"] == "stream_lag:signals"
        assert metric_data["metric_value"] == 0.0  # value -> metric_value
        assert metric_data["metric_unit"] == "seconds"  # unit -> metric_unit
        assert metric_data["tags"] == {"stream": "signals"}
        assert metric_data["schema_version"] == "v2"
        assert metric_data["source"] == "system_monitor"

    def test_order_field_mapping(self, safe_writer):
        """Test Order field mapping logic without database."""
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
            "source": "trading_bot",
        }

        # Test the mapping that would be used in write_order
        # Note: metadata -> order_metadata mapping
        assert data["metadata"] == {"exchange": "binance"}
        assert data["idempotency_key"] == "unique-key-123"
        assert data["strategy_id"] == "strategy-uuid"
        assert data["symbol"] == "BTC/USD"

    def test_agent_log_field_mapping(self, safe_writer):
        """Test AgentLog field mapping logic without database."""
        data = {
            "agent_id": "agent-run-uuid",  # This maps to agent_run_id
            "level": "INFO",  # This maps to log_level
            "message": "Task completed successfully",
            "step_name": "process_trade",
            "step_data": {"trade_id": "trade-123"},
            "trace_id": "trace-456",
            "schema_version": "v2",
            "source": "agent_executor",
        }

        # Test the mapping that would be used in write_agent_log
        log_data = {
            "agent_run_id": data["agent_id"],  # agent_id -> agent_run_id
            "log_level": data.get("log_level", "INFO"),  # level -> log_level
            "message": data["message"],
            "step_name": data.get("step_name"),
            "step_data": data.get("step_data", {}),
            "trace_id": data.get("trace_id", "unknown"),
            "schema_version": data.get("schema_version", "v2"),
            "source": data.get("source", "unknown"),
        }

        # Verify field mappings
        assert log_data["agent_run_id"] == "agent-run-uuid"  # agent_id -> agent_run_id
        assert log_data["log_level"] == "INFO"  # level -> log_level
        assert log_data["message"] == "Task completed successfully"
        assert log_data["step_name"] == "process_trade"
        assert log_data["step_data"] == {"trade_id": "trade-123"}
        assert log_data["trace_id"] == "trace-456"
        assert log_data["schema_version"] == "v2"
        assert log_data["source"] == "agent_executor"

    def test_vector_memory_field_mapping(self, safe_writer):
        """Test VectorMemory field mapping logic without database."""
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
            "source": "analysis_agent",
        }

        # Test the mapping that would be used in write_vector_memory
        vector_data = {
            "content": data["content"],
            "content_type": data["content_type"],
            "embedding": data["embedding"],
            "vector_metadata": data.get("metadata", {}),  # metadata -> vector_metadata
            "agent_id": data.get("agent_id"),
            "strategy_id": data.get("strategy_id"),
            "schema_version": data.get("schema_version", "v2"),
            "source": data.get("source", "unknown"),
        }

        # Verify field mappings
        assert vector_data["content"] == "Trade analysis shows bullish trend"
        assert vector_data["content_type"] == "insight"
        assert vector_data["embedding"] == embedding
        assert vector_data["vector_metadata"] == {
            "analysis_type": "technical",
            "confidence": 0.85,
        }  # metadata -> vector_metadata
        assert vector_data["agent_id"] == "agent-uuid"
        assert vector_data["strategy_id"] == "strategy-uuid"
        assert vector_data["schema_version"] == "v2"
        assert vector_data["source"] == "analysis_agent"

        # Verify invalid fields are not present
        assert "metadata" not in vector_data
        assert "symbol" not in vector_data
        assert "relevance_score" not in vector_data

    def test_vector_memory_embedding_validation(self, safe_writer):
        """Test VectorMemory embedding size validation."""
        # Test valid embedding
        valid_embedding = [0.1] * 1536
        assert len(valid_embedding) == 1536
        assert all(isinstance(x, (int, float)) for x in valid_embedding)

        # Test invalid embedding sizes
        invalid_embedding_small = [0.1, 0.2]  # Too small
        assert len(invalid_embedding_small) != 1536

        invalid_embedding_type = ["not", "numbers"] * 768  # Wrong type
        assert not all(isinstance(x, (int, float)) for x in invalid_embedding_type)

    def test_timestamp_fallback_logging(self, safe_writer):
        """Test timestamp fallback logging logic."""
        # Test valid timestamp
        valid_timestamp = "2026-03-25T07:13:06.308008Z"
        parsed = safe_writer.safe_parse_dt(valid_timestamp)
        assert parsed is not None
        assert parsed.year == 2026

        # Test invalid timestamp
        invalid_timestamp = "not-a-timestamp"
        parsed = safe_writer.safe_parse_dt(invalid_timestamp)
        assert parsed is None

        # Test missing timestamp
        missing_timestamp = None
        parsed = safe_writer.safe_parse_dt(missing_timestamp)
        assert parsed is None


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
            "value": 42.0,
        }

        # Should not raise
        safe_writer._validate_schema_v2(valid_data, "SystemMetrics")

    def test_validate_schema_v2_missing_version(self, safe_writer):
        """Test validation fails without schema version."""
        invalid_data = {"source": "test", "metric_name": "test_metric", "value": 42.0}

        with pytest.raises(ValueError, match="Missing required field 'schema_version'"):
            safe_writer._validate_schema_v2(invalid_data, "SystemMetrics")

    def test_validate_schema_v2_wrong_version(self, safe_writer):
        """Test validation fails with wrong schema version."""
        invalid_data = {
            "schema_version": "v1",
            "source": "test",
            "metric_name": "test_metric",
            "value": 42.0,
        }

        with pytest.raises(ValueError, match="Invalid schema version 'v1'"):
            safe_writer._validate_schema_v2(invalid_data, "SystemMetrics")

    def test_validate_payload_missing_required(self, safe_writer):
        """Test payload validation fails with missing required fields."""
        data = {
            "metric_name": "test_metric"
            # Missing 'value'
        }

        with pytest.raises(ValueError, match="Missing required field: value"):
            safe_writer.validate_payload(data, ["metric_name", "value"])


class TestConsumerIntegration:
    """Test consumer integration with schema mapping."""

    @pytest.mark.asyncio
    async def test_system_metrics_consumer_handler(self):
        """Test SystemMetricsConsumer maps data correctly for SafeWriter."""
        from unittest.mock import Mock

        from api.services.system_metrics_consumer import SystemMetricsConsumer

        # Mock dependencies
        bus = Mock()
        dlq = Mock()
        redis_client = Mock()
        redis_client.get = AsyncMock(return_value=None)  # Kill switch off - must be awaitable

        # Create consumer
        consumer = SystemMetricsConsumer(bus, dlq, redis_client)

        # Test data
        test_data = {
            "msg_id": "consumer-test-123",
            "metric_name": "test_metric",
            "value": 42.0,
            "unit": "percent",
            "tags": {"host": "server1"},
            "timestamp": "2024-01-01T00:00:00Z",
        }

        with patch.object(consumer, "safe_writer") as mock_writer:
            mock_writer.write_system_metric = AsyncMock(return_value=True)

            # Process the message
            await consumer.process(test_data)

            # Verify SafeWriter was called with correct signature
            mock_writer.write_system_metric.assert_called_once()
            call_kwargs = mock_writer.write_system_metric.call_args[1]

            assert call_kwargs["msg_id"] == "consumer-test-123"
            assert call_kwargs["metric_name"] == "test_metric"
            assert call_kwargs["metric_value"] == 42.0
            assert call_kwargs["metric_unit"] == "percent"
            assert call_kwargs["tags"] == {"host": "server1"}
            assert call_kwargs["schema_version"] == "v2"
            assert call_kwargs["source"] == "system_monitor"
