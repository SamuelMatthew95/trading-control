"""Unit tests for SystemMetricsConsumer."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.system_metrics_consumer import SystemMetricsConsumer


@pytest.fixture
def mock_bus():
    """Mock EventBus."""
    bus = MagicMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    bus.reclaim_stale = AsyncMock(return_value=[])
    return bus


@pytest.fixture
def mock_dlq():
    """Mock DLQManager."""
    dlq = MagicMock()
    dlq.should_dlq = AsyncMock(return_value=False)
    dlq.push = AsyncMock()
    dlq.redis = MagicMock()
    dlq.redis.get = AsyncMock(return_value=None)
    return dlq


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)  # Kill switch off
    return redis


@pytest.fixture
def consumer(mock_bus, mock_dlq, mock_redis):
    """Create SystemMetricsConsumer instance."""
    with patch('api.services.system_metrics_consumer.SafeWriter') as mock_safe_writer:
        mock_writer_instance = AsyncMock()
        mock_safe_writer.return_value = mock_writer_instance
        
        consumer = SystemMetricsConsumer(mock_bus, mock_dlq, mock_redis)
        consumer.safe_writer = mock_writer_instance
        return consumer


class TestSystemMetricsConsumer:
    """Test suite for SystemMetricsConsumer."""

    @pytest.mark.asyncio
    async def test_process_with_msg_id_generates_uuid_if_missing(self, consumer):
        """Test that UUID is generated when msg_id is missing."""
        data = {
            "metric_name": "cpu_usage",
            "value": 75.5,
            "unit": "percent",
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        await consumer.process(data)
        
        # Verify SafeWriter was called
        consumer.safe_writer.write_system_metric.assert_called_once()
        call_args = consumer.safe_writer.write_system_metric.call_args[1]
        
        # Check that msg_id is a UUID string
        assert call_args["msg_id"] is not None
        assert isinstance(call_args["msg_id"], str)
        # Verify it's a valid UUID
        uuid.UUID(call_args["msg_id"])  # Will raise if invalid

    @pytest.mark.asyncio
    async def test_process_uses_existing_msg_id(self, consumer):
        """Test that existing msg_id is used when provided."""
        existing_msg_id = "test-msg-123"
        data = {
            "msg_id": existing_msg_id,
            "metric_name": "memory_usage",
            "value": 1024,
            "unit": "MB"
        }
        
        await consumer.process(data)
        
        # Verify SafeWriter was called with existing msg_id
        consumer.safe_writer.write_system_metric.assert_called_once()
        call_args = consumer.safe_writer.write_system_metric.call_args[1]
        
        assert call_args["msg_id"] == existing_msg_id

    @pytest.mark.asyncio
    async def test_process_maps_fields_correctly(self, consumer):
        """Test that input fields are mapped to correct DB columns."""
        data = {
            "msg_id": "test-123",
            "metric_name": "disk_usage",
            "value": 85.2,
            "unit": "percent",
            "tags": {"device": "/dev/sda1"},
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        await consumer.process(data)
        
        # Verify SafeWriter was called with correct field mapping
        consumer.safe_writer.write_system_metric.assert_called_once()
        call_args = consumer.safe_writer.write_system_metric.call_args[1]
        
        assert call_args["metric_name"] == "disk_usage"
        assert call_args["metric_value"] == 85.2
        assert call_args["metric_unit"] == "percent"
        assert call_args["tags"] == {"device": "/dev/sda1"}
        assert call_args["schema_version"] == "v2"
        assert call_args["source"] == "system_monitor"
        assert isinstance(call_args["timestamp"], datetime)

    @pytest.mark.asyncio
    async def test_process_handles_missing_optional_fields(self, consumer):
        """Test that missing optional fields are handled gracefully."""
        data = {
            "metric_name": "network_latency",
            "value": 25.3
            # Missing unit, tags, timestamp
        }
        
        await consumer.process(data)
        
        # Verify SafeWriter was called with defaults
        consumer.safe_writer.write_system_metric.assert_called_once()
        call_args = consumer.safe_writer.write_system_metric.call_args[1]
        
        assert call_args["metric_name"] == "network_latency"
        assert call_args["metric_value"] == 25.3
        assert call_args["metric_unit"] is None
        assert call_args["tags"] == {}
        assert call_args["schema_version"] == "v2"
        assert call_args["source"] == "system_monitor"
        # Timestamp should be recent (fallback to now)
        assert isinstance(call_args["timestamp"], datetime)

    @pytest.mark.asyncio
    async def test_process_timestamp_fallback(self, consumer):
        """Test timestamp parsing and fallback behavior."""
        # Test with valid timestamp
        data_valid = {
            "metric_name": "cpu_temp",
            "value": 65.0,
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        await consumer.process(data_valid)
        call_args = consumer.safe_writer.write_system_metric.call_args[1]
        
        expected_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert call_args["timestamp"] == expected_time

    @pytest.mark.asyncio
    async def test_process_timestamp_invalid_fallback(self, consumer):
        """Test timestamp fallback with invalid timestamp."""
        data_invalid = {
            "metric_name": "cpu_temp",
            "value": 65.0,
            "timestamp": "invalid-timestamp"
        }
        
        await consumer.process(data_invalid)
        call_args = consumer.safe_writer.write_system_metric.call_args[1]
        
        # Should fallback to current time
        assert isinstance(call_args["timestamp"], datetime)
        # Should be recent (within last few seconds)
        now = datetime.now(timezone.utc)
        assert abs((call_args["timestamp"] - now).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_process_kill_switch_active(self, consumer):
        """Test that processing stops when kill switch is active."""
        # Mock kill switch active
        consumer.redis.get.return_value = "1"
        
        data = {
            "metric_name": "test_metric",
            "value": 42.0
        }
        
        with pytest.raises(RuntimeError, match="KillSwitchActive"):
            await consumer.process(data)
        
        # SafeWriter should not be called
        consumer.safe_writer.write_system_metric.assert_not_called()

    @pytest.mark.asyncio
    async def test_safe_parse_dt_valid(self, consumer):
        """Test safe_parse_dt with valid ISO string."""
        result = consumer.safe_parse_dt("2024-01-01T12:00:00Z")
        expected = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    @pytest.mark.asyncio
    async def test_safe_parse_dt_invalid(self, consumer):
        """Test safe_parse_dt with invalid string."""
        result = consumer.safe_parse_dt("invalid-date")
        assert result is None

    @pytest.mark.asyncio
    async def test_safe_parse_dt_none(self, consumer):
        """Test safe_parse_dt with None."""
        result = consumer.safe_parse_dt(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_safe_parse_dt_with_milliseconds(self, consumer):
        """Test safe_parse_dt with milliseconds."""
        result = consumer.safe_parse_dt("2024-01-01T12:00:00.123Z")
        expected = datetime(2024, 1, 1, 12, 0, 0, 123000, tzinfo=timezone.utc)
        assert result == expected

    @pytest.mark.asyncio
    async def test_process_logging(self, consumer):
        """Test that processing is logged correctly."""
        data = {
            "metric_name": "test_metric",
            "value": 42.0
        }
        
        with patch.object(consumer.logger, 'info') as mock_log:
            await consumer.process(data)
            
            # Verify logging was called
            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            assert args[0] == "Processed system metric"
            assert "extra" in kwargs
            assert kwargs["extra"]["metric_name"] == "test_metric"
            assert "msg_id" in kwargs["extra"]
