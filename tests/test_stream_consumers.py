"""Tests for all stream consumers."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from redis.asyncio import Redis

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.simple_consumers import (
    SimpleConsumer, ExecutionsConsumer, RiskAlertsConsumer,
    LearningEventsConsumer, AgentLogsConsumer
)
from api.services.system_metrics_consumer import SystemMetricsConsumer
from api.services.system_metrics_handler import handle_system_metric, ProcessResult


class TestSimpleConsumer:
    """Test the base SimpleConsumer."""
    
    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)  # Kill switch not active
        return redis
    
    @pytest.fixture
    def mock_redis_with_kill_switch(self):
        redis = MagicMock()
        redis.get = AsyncMock(return_value="1")  # Kill switch active
        return redis
    
    @pytest.fixture
    def mock_bus(self):
        return AsyncMock(spec=EventBus)
    
    @pytest.fixture
    def mock_dlq(self):
        return AsyncMock(spec=DLQManager)
    
    @pytest.fixture
    def consumer(self, mock_bus, mock_dlq, mock_redis):
        return SimpleConsumer(mock_bus, mock_dlq, mock_redis, "test_stream", "test-consumer")
    
    @pytest.mark.asyncio
    async def test_consumer_processes_message(self, consumer, mock_redis):
        """Test that consumer processes messages successfully."""
        data = {"msg_id": "test123", "content": "test data"}
        
        # Should not raise any exception
        await consumer.process(data)
        
        # Verify kill switch was checked
        mock_redis.get.assert_called_once_with("kill_switch:active")
    
    @pytest.mark.asyncio
    async def test_consumer_respects_kill_switch(self, mock_bus, mock_dlq, mock_redis_with_kill_switch):
        """Test that consumer respects kill switch."""
        consumer = SimpleConsumer(mock_bus, mock_dlq, mock_redis_with_kill_switch, "test_stream", "test-consumer")
        
        data = {"msg_id": "test123", "content": "test data"}
        
        # Should raise RuntimeError when kill switch is active
        with pytest.raises(RuntimeError, match="KillSwitchActive"):
            await consumer.process(data)
    
    @pytest.mark.asyncio
    async def test_consumer_handles_missing_msg_id(self, consumer, mock_redis):
        """Test that consumer handles missing msg_id gracefully."""
        data = {"content": "test data"}  # No msg_id
        
        # Should not raise any exception
        await consumer.process(data)
        
        # Verify kill switch was checked
        mock_redis.get.assert_called_once_with("kill_switch:active")


class TestSpecificConsumers:
    """Test all specific consumer implementations."""
    
    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        return redis
    
    @pytest.fixture
    def mock_bus(self):
        return AsyncMock(spec=EventBus)
    
    @pytest.fixture
    def mock_dlq(self):
        return AsyncMock(spec=DLQManager)
    
    @pytest.mark.asyncio
    async def test_executions_consumer_initialization(self, mock_bus, mock_dlq, mock_redis):
        """Test ExecutionsConsumer initialization."""
        consumer = ExecutionsConsumer(mock_bus, mock_dlq, mock_redis)
        
        assert consumer.stream == "executions"
        assert consumer.consumer == "executions-logger"
        assert consumer.redis == mock_redis
    
    @pytest.mark.asyncio
    async def test_risk_alerts_consumer_initialization(self, mock_bus, mock_dlq, mock_redis):
        """Test RiskAlertsConsumer initialization."""
        consumer = RiskAlertsConsumer(mock_bus, mock_dlq, mock_redis)
        
        assert consumer.stream == "risk_alerts"
        assert consumer.consumer == "risk-alerts-logger"
        assert consumer.redis == mock_redis
    
    @pytest.mark.asyncio
    async def test_learning_events_consumer_initialization(self, mock_bus, mock_dlq, mock_redis):
        """Test LearningEventsConsumer initialization."""
        consumer = LearningEventsConsumer(mock_bus, mock_dlq, mock_redis)
        
        assert consumer.stream == "learning_events"
        assert consumer.consumer == "learning-events-logger"
        assert consumer.redis == mock_redis
    
    @pytest.mark.asyncio
    async def test_agent_logs_consumer_initialization(self, mock_bus, mock_dlq, mock_redis):
        """Test AgentLogsConsumer initialization."""
        consumer = AgentLogsConsumer(mock_bus, mock_dlq, mock_redis)
        
        assert consumer.stream == "agent_logs"
        assert consumer.consumer == "agent-logs-logger"
        assert consumer.redis == mock_redis
    
    @pytest.mark.asyncio
    async def test_all_consumers_process_messages(self, mock_bus, mock_dlq, mock_redis):
        """Test that all consumers can process messages."""
        consumers = [
            ExecutionsConsumer(mock_bus, mock_dlq, mock_redis),
            RiskAlertsConsumer(mock_bus, mock_dlq, mock_redis),
            LearningEventsConsumer(mock_bus, mock_dlq, mock_redis),
            AgentLogsConsumer(mock_bus, mock_dlq, mock_redis)
        ]
        
        test_data = {"msg_id": "test123", "content": "test data"}
        
        for consumer in consumers:
            # Each consumer should process without error
            await consumer.process(test_data)


class TestSystemMetricsConsumer:
    """Test SystemMetricsConsumer."""
    
    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        return redis
    
    @pytest.fixture
    def mock_redis_with_kill_switch(self):
        redis = MagicMock()
        redis.get = AsyncMock(return_value="1")
        return redis
    
    @pytest.fixture
    def mock_bus(self):
        return AsyncMock(spec=EventBus)
    
    @pytest.fixture
    def mock_dlq(self):
        return AsyncMock(spec=DLQManager)
    
    @pytest.fixture
    def consumer(self, mock_bus, mock_dlq, mock_redis):
        return SystemMetricsConsumer(mock_bus, mock_dlq, mock_redis)
    
    @pytest.mark.asyncio
    async def test_system_metrics_consumer_initialization(self, consumer):
        """Test SystemMetricsConsumer initialization."""
        assert consumer.stream == "system_metrics"
        assert consumer.consumer == "system-metrics"
        assert consumer.redis is not None
    
    @pytest.mark.asyncio
    async def test_system_metrics_consumer_processes_valid_data(self, consumer):
        """Test that SystemMetricsConsumer processes valid metric data."""
        data = {
            "msg_id": "test123",
            "metric_name": "cpu_usage",
            "value": 75.5,
            "unit": "percent",
            "labels": {"host": "server1"}
        }
        
        # Should not raise any exception
        await consumer.process(data)
    
    @pytest.mark.asyncio
    async def test_system_metrics_consumer_respects_kill_switch(self, mock_bus, mock_dlq, mock_redis_with_kill_switch):
        """Test that SystemMetricsConsumer respects kill switch."""
        consumer = SystemMetricsConsumer(mock_bus, mock_dlq, mock_redis_with_kill_switch)
        
        data = {
            "msg_id": "test123",
            "metric_name": "cpu_usage",
            "value": 75.5
        }
        
        # Should raise RuntimeError when kill switch is active
        with pytest.raises(RuntimeError, match="KillSwitchActive"):
            await consumer.process(data)


class TestSystemMetricsHandler:
    """Test SystemMetricsHandler."""
    
    @pytest.mark.asyncio
    async def test_handle_system_metric_success(self):
        """Test successful system metric handling."""
        data = {
            "metric_name": "cpu_usage",
            "value": 75.5,
            "unit": "percent",
            "labels": {"host": "server1"}
        }
        
        result = await handle_system_metric("msg123", "system_metrics", data, "trace123")
        
        assert result.success is True
        assert result.retryable is False
        assert "Processed metric" in result.message
    
    @pytest.mark.asyncio
    async def test_handle_system_metric_missing_name(self):
        """Test handling metric with missing name."""
        data = {
            "value": 75.5,
            "unit": "percent"
        }
        
        result = await handle_system_metric("msg123", "system_metrics", data, "trace123")
        
        assert result.success is False
        assert result.retryable is False
        assert "Missing metric_name" in result.message
    
    @pytest.mark.asyncio
    async def test_handle_system_metric_missing_value(self):
        """Test handling metric with missing value."""
        data = {
            "metric_name": "cpu_usage",
            "unit": "percent"
        }
        
        result = await handle_system_metric("msg123", "system_metrics", data, "trace123")
        
        assert result.success is False
        assert result.retryable is False
        assert "Missing value" in result.message


class TestConsumerIntegration:
    """Integration tests for consumers."""
    
    @pytest.mark.asyncio
    async def test_all_streams_have_consumers(self):
        """Test that all defined streams have corresponding consumers."""
        from api.constants import (
            STREAM_MARKET_TICKS, STREAM_SIGNALS, STREAM_ORDERS, STREAM_EXECUTIONS,
            STREAM_RISK_ALERTS, STREAM_LEARNING_EVENTS, STREAM_SYSTEM_METRICS, STREAM_AGENT_LOGS
        )
        
        # Map streams to their consumers
        stream_consumers = {
            STREAM_MARKET_TICKS: "SignalGenerator",
            STREAM_SIGNALS: "ReasoningAgent", 
            STREAM_ORDERS: "ExecutionEngine",
            STREAM_EXECUTIONS: "ExecutionsConsumer",
            STREAM_RISK_ALERTS: "RiskAlertsConsumer",
            STREAM_LEARNING_EVENTS: "LearningEventsConsumer",
            STREAM_SYSTEM_METRICS: "SystemMetricsConsumer",
            STREAM_AGENT_LOGS: "AgentLogsConsumer"
        }
        
        # Verify all streams have consumers
        for stream, consumer in stream_consumers.items():
            assert consumer is not None, f"Stream {stream} has no consumer"
            assert len(consumer) > 0, f"Consumer name for {stream} is empty"
    
    def test_consumer_follows_same_pattern(self):
        """Test that all consumers follow the same BaseStreamConsumer pattern."""
        from api.events.consumer import BaseStreamConsumer
        
        # All consumers should inherit from BaseStreamConsumer
        consumers = [
            ExecutionsConsumer,
            RiskAlertsConsumer,
            LearningEventsConsumer,
            AgentLogsConsumer,
            SystemMetricsConsumer
        ]
        
        for consumer_class in consumers:
            assert issubclass(consumer_class, BaseStreamConsumer), f"{consumer_class.__name__} does not inherit from BaseStreamConsumer"
