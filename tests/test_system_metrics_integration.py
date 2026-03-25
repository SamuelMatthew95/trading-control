"""
Integration Tests - SystemMetrics Duplicate Message Handling.

Tests the end-to-end behavior with duplicate Redis messages.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock
from sqlalchemy import select


class TestSystemMetricsDuplicateHandling:
    """Test duplicate message handling in SystemMetrics pipeline."""
    
    @pytest.mark.asyncio
    async def test_duplicate_redis_messages_idempotent(self, db_session):
        """Duplicate Redis messages should not create duplicate DB records."""
        from api.services.system_metrics_consumer import SystemMetricsConsumer
        from api.events.bus import EventBus
        from api.events.dlq import DLQManager
        from api.core.models import SystemMetrics
        
        # Mock dependencies
        bus = Mock(spec=EventBus)
        dlq = Mock(spec=DLQManager)
        redis_client = Mock()
        redis_client.get.return_value = None  # Kill switch off
        
        # Create consumer
        consumer = SystemMetricsConsumer(bus, dlq, redis_client)
        
        # Test data with same msg_id
        test_data = {
            "msg_id": "duplicate-test-1",
            "metric_name": "memory_usage",
            "value": 60.0,
            "unit": "percent",
            "tags": {"host": "server1"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Process same message twice
        await consumer.process(test_data)
        await consumer.process(test_data)  # Duplicate
        
        # Verify only one record exists
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 1
        assert str(metrics[0].id) == "duplicate-test-1"
    
    @pytest.mark.asyncio
    async def test_duplicate_messages_different_content_same_id(self, db_session):
        """Same msg_id with different content should still be idempotent."""
        from api.services.system_metrics_consumer import SystemMetricsConsumer
        from api.events.bus import EventBus
        from api.events.dlq import DLQManager
        from api.core.models import SystemMetrics
        
        # Mock dependencies
        bus = Mock(spec=EventBus)
        dlq = Mock(spec=DLQManager)
        redis_client = Mock()
        redis_client.get.return_value = None
        
        # Create consumer
        consumer = SystemMetricsConsumer(bus, dlq, redis_client)
        
        # First message
        test_data1 = {
            "msg_id": "duplicate-test-2",
            "metric_name": "cpu_usage",
            "value": 50.0,
            "unit": "percent",
            "tags": {"host": "server1"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Second message with same msg_id but different content
        test_data2 = {
            "msg_id": "duplicate-test-2",  # Same ID
            "metric_name": "cpu_usage",
            "value": 75.0,  # Different value
            "unit": "percent",
            "tags": {"host": "server1"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Process both messages
        await consumer.process(test_data1)
        await consumer.process(test_data2)
        
        # Verify only one record exists (first write wins)
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 1
        assert str(metrics[0].id) == "duplicate-test-2"
        # Should have the first value (50.0), not the second (75.0)
        assert metrics[0].metric_value == 50.0
    
    @pytest.mark.asyncio
    async def test_concurrent_duplicate_messages(self, db_session):
        """Concurrent processing of duplicate messages should be safe."""
        import asyncio
        from api.services.system_metrics_consumer import SystemMetricsConsumer
        from api.events.bus import EventBus
        from api.events.dlq import DLQManager
        from api.core.models import SystemMetrics
        
        # Mock dependencies
        bus = Mock(spec=EventBus)
        dlq = Mock(spec=DLQManager)
        redis_client = Mock()
        redis_client.get.return_value = None
        
        # Create consumer
        consumer = SystemMetricsConsumer(bus, dlq, redis_client)
        
        # Test data
        test_data = {
            "msg_id": "concurrent-duplicate-1",
            "metric_name": "disk_io",
            "value": 1000.0,
            "unit": "iops",
            "tags": {"host": "server1"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Process same message concurrently
        async def process_message():
            await consumer.process(test_data)
        
        # Run 5 concurrent processes
        await asyncio.gather(*[process_message() for _ in range(5)])
        
        # Verify only one record exists
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 1
        assert str(metrics[0].id) == "concurrent-duplicate-1"
    
    @pytest.mark.asyncio
    async def test_no_retries_on_duplicate(self, db_session):
        """Duplicate messages should not trigger retries or DLQ."""
        from api.services.system_metrics_consumer import SystemMetricsConsumer
        from api.events.bus import EventBus
        from api.events.dlq import DLQManager
        
        # Mock dependencies
        bus = Mock(spec=EventBus)
        dlq = Mock(spec=DLQManager)
        redis_client = Mock()
        redis_client.get.return_value = None
        
        # Create consumer
        consumer = SystemMetricsConsumer(bus, dlq, redis_client)
        
        # Test data
        test_data = {
            "msg_id": "no-retry-test-1",
            "metric_name": "network_throughput",
            "value": 100.0,
            "unit": "mbps",
            "tags": {"host": "server1"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Process same message twice
        await consumer.process(test_data)
        await consumer.process(test_data)  # Duplicate
        
        # Verify DLQ was not called
        dlq.send_to_dlq.assert_not_called()
        
        # Verify no exceptions were raised
        # (If there were issues, they would have been raised)
    
    @pytest.mark.asyncio
    async def test_generated_msg_id_uniqueness(self, db_session):
        """Messages without msg_id should get unique generated IDs."""
        from api.services.system_metrics_consumer import SystemMetricsConsumer
        from api.events.bus import EventBus
        from api.events.dlq import DLQManager
        from api.core.models import SystemMetrics
        
        # Mock dependencies
        bus = Mock(spec=EventBus)
        dlq = Mock(spec=DLQManager)
        redis_client = Mock()
        redis_client.get.return_value = None
        
        # Create consumer
        consumer = SystemMetricsConsumer(bus, dlq, redis_client)
        
        # Test data without msg_id
        test_data1 = {
            "metric_name": "temperature",
            "value": 45.0,
            "unit": "celsius",
            "tags": {"sensor": "cpu"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        test_data2 = {
            "metric_name": "temperature", 
            "value": 50.0,
            "unit": "celsius",
            "tags": {"sensor": "gpu"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Process both messages (should generate different UUIDs)
        await consumer.process(test_data1)
        await consumer.process(test_data2)
        
        # Verify two records exist with different IDs
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 2
        
        # IDs should be different
        id1, id2 = str(metrics[0].id), str(metrics[1].id)
        assert id1 != id2
        assert id1 != "unknown"
        assert id2 != "unknown"
