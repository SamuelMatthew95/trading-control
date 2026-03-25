"""Unit tests for SimpleConsumer and its subclasses."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.simple_consumers import (
    SimpleConsumer, ExecutionsConsumer, RiskAlertsConsumer,
    LearningEventsConsumer, AgentLogsConsumer
)


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
def simple_consumer(mock_bus, mock_dlq, mock_redis):
    """Create SimpleConsumer instance."""
    return SimpleConsumer(mock_bus, mock_dlq, mock_redis, "test_stream", "test-consumer")


class TestSimpleConsumer:
    """Test suite for SimpleConsumer."""

    @pytest.mark.asyncio
    async def test_process_generates_uuid_if_missing(self, simple_consumer):
        """Test that UUID is generated when msg_id is missing."""
        data = {
            "some_field": "some_value"
        }
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await simple_consumer.process(data)
            
            # Verify logging was called with UUID
            mock_log.assert_called_once_with(
                "debug",
                "message_processed",
                stream="test_stream",
                msg_id=mock_log.call_args[1]["msg_id"],
                consumer="test-consumer"
            )
            
            # Verify msg_id is a UUID string
            msg_id = mock_log.call_args[1]["msg_id"]
            assert isinstance(msg_id, str)
            # Verify it's a valid UUID
            uuid.UUID(msg_id)  # Will raise if invalid

    @pytest.mark.asyncio
    async def test_process_uses_existing_msg_id(self, simple_consumer):
        """Test that existing msg_id is used when provided."""
        existing_msg_id = "test-msg-123"
        data = {
            "msg_id": existing_msg_id,
            "some_field": "some_value"
        }
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await simple_consumer.process(data)
            
            # Verify logging was called with existing msg_id
            mock_log.assert_called_once_with(
                "debug",
                "message_processed",
                stream="test_stream",
                msg_id=existing_msg_id,
                consumer="test-consumer"
            )

    @pytest.mark.asyncio
    async def test_process_kill_switch_active(self, simple_consumer):
        """Test that processing stops when kill switch is active."""
        # Mock kill switch active
        simple_consumer.redis.get.return_value = "1"
        
        data = {"some_field": "value"}
        
        with pytest.raises(RuntimeError, match="KillSwitchActive"):
            await simple_consumer.process(data)
        
        # Logging should not be called
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            try:
                await simple_consumer.process(data)
            except RuntimeError:
                pass
            mock_log.assert_not_called()


class TestSubclassConsumers:
    """Test suite for SimpleConsumer subclasses."""

    @pytest.mark.asyncio
    async def test_executions_consumer_inherits_uuid_behavior(self, mock_bus, mock_dlq, mock_redis):
        """Test that ExecutionsConsumer inherits UUID-safe behavior."""
        consumer = ExecutionsConsumer(mock_bus, mock_dlq, mock_redis)
        data = {"execution_data": "test"}
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await consumer.process(data)
            
            # Verify UUID generation
            msg_id = mock_log.call_args[1]["msg_id"]
            assert isinstance(msg_id, str)
            uuid.UUID(msg_id)  # Will raise if invalid
            assert mock_log.call_args[1]["stream"] == "executions"
            assert mock_log.call_args[1]["consumer"] == "executions-logger"

    @pytest.mark.asyncio
    async def test_risk_alerts_consumer_inherits_uuid_behavior(self, mock_bus, mock_dlq, mock_redis):
        """Test that RiskAlertsConsumer inherits UUID-safe behavior."""
        consumer = RiskAlertsConsumer(mock_bus, mock_dlq, mock_redis)
        data = {"alert_type": "high_risk"}
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await consumer.process(data)
            
            # Verify UUID generation
            msg_id = mock_log.call_args[1]["msg_id"]
            assert isinstance(msg_id, str)
            uuid.UUID(msg_id)  # Will raise if invalid
            assert mock_log.call_args[1]["stream"] == "risk_alerts"
            assert mock_log.call_args[1]["consumer"] == "risk-alerts-logger"

    @pytest.mark.asyncio
    async def test_learning_events_consumer_inherits_uuid_behavior(self, mock_bus, mock_dlq, mock_redis):
        """Test that LearningEventsConsumer inherits UUID-safe behavior."""
        consumer = LearningEventsConsumer(mock_bus, mock_dlq, mock_redis)
        data = {"learning_event": "model_update"}
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await consumer.process(data)
            
            # Verify UUID generation
            msg_id = mock_log.call_args[1]["msg_id"]
            assert isinstance(msg_id, str)
            uuid.UUID(msg_id)  # Will raise if invalid
            assert mock_log.call_args[1]["stream"] == "learning_events"
            assert mock_log.call_args[1]["consumer"] == "learning-events-logger"

    @pytest.mark.asyncio
    async def test_agent_logs_consumer_inherits_uuid_behavior(self, mock_bus, mock_dlq, mock_redis):
        """Test that AgentLogsConsumer inherits UUID-safe behavior."""
        consumer = AgentLogsConsumer(mock_bus, mock_dlq, mock_redis)
        data = {"agent_log": "task_completed"}
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await consumer.process(data)
            
            # Verify UUID generation
            msg_id = mock_log.call_args[1]["msg_id"]
            assert isinstance(msg_id, str)
            uuid.UUID(msg_id)  # Will raise if invalid
            assert mock_log.call_args[1]["stream"] == "agent_logs"
            assert mock_log.call_args[1]["consumer"] == "agent-logs-logger"


class TestConsumerConfiguration:
    """Test consumer configuration and stream setup."""

    def test_executions_consumer_configuration(self, mock_bus, mock_dlq, mock_redis):
        """Test ExecutionsConsumer is configured correctly."""
        consumer = ExecutionsConsumer(mock_bus, mock_dlq, mock_redis)
        assert consumer.stream == "executions"
        assert consumer.consumer == "executions-logger"

    def test_risk_alerts_consumer_configuration(self, mock_bus, mock_dlq, mock_redis):
        """Test RiskAlertsConsumer is configured correctly."""
        consumer = RiskAlertsConsumer(mock_bus, mock_dlq, mock_redis)
        assert consumer.stream == "risk_alerts"
        assert consumer.consumer == "risk-alerts-logger"

    def test_learning_events_consumer_configuration(self, mock_bus, mock_dlq, mock_redis):
        """Test LearningEventsConsumer is configured correctly."""
        consumer = LearningEventsConsumer(mock_bus, mock_dlq, mock_redis)
        assert consumer.stream == "learning_events"
        assert consumer.consumer == "learning-events-logger"

    def test_agent_logs_consumer_configuration(self, mock_bus, mock_dlq, mock_redis):
        """Test AgentLogsConsumer is configured correctly."""
        consumer = AgentLogsConsumer(mock_bus, mock_dlq, mock_redis)
        assert consumer.stream == "agent_logs"
        assert consumer.consumer == "agent-logs-logger"


class TestUUIDUniqueness:
    """Test UUID generation uniqueness across multiple calls."""

    @pytest.mark.asyncio
    async def test_uuid_uniqueness_across_calls(self, simple_consumer):
        """Test that different calls generate different UUIDs."""
        data1 = {"field1": "value1"}
        data2 = {"field2": "value2"}
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await simple_consumer.process(data1)
            msg_id1 = mock_log.call_args[1]["msg_id"]
            
            await simple_consumer.process(data2)
            msg_id2 = mock_log.call_args[1]["msg_id"]
            
            # UUIDs should be different
            assert msg_id1 != msg_id2
            # Both should be valid UUIDs
            uuid.UUID(msg_id1)
            uuid.UUID(msg_id2)

    @pytest.mark.asyncio
    async def test_uuid_uniqueness_across_consumers(self, mock_bus, mock_dlq, mock_redis):
        """Test that different consumers generate different UUIDs."""
        consumer1 = SimpleConsumer(mock_bus, mock_dlq, mock_redis, "stream1", "consumer1")
        consumer2 = SimpleConsumer(mock_bus, mock_dlq, mock_redis, "stream2", "consumer2")
        
        data = {"test": "data"}
        
        with patch('api.services.simple_consumers.log_structured') as mock_log:
            await consumer1.process(data)
            # Get the first call's msg_id
            msg_id1 = mock_log.call_args[1]["msg_id"]
            
            await consumer2.process(data)
            # Get the second call's msg_id
            msg_id2 = mock_log.call_args[1]["msg_id"]
            
            # UUIDs should be different
            assert msg_id1 != msg_id2
            # Both should be valid UUIDs
            uuid.UUID(msg_id1)
            uuid.UUID(msg_id2)
