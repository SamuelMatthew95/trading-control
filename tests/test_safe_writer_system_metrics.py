"""
SystemMetrics SafeWriter Tests - Idempotency and msg_id handling.

Tests the critical fixes for SystemMetrics:
1. msg_id used as primary identifier
2. Idempotent writes via PostgreSQL UPSERT
3. Proper logging without 'unknown'
4. Validation of required msg_id
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from decimal import Decimal


class TestSystemMetricsIdempotency:
    """Test SystemMetrics idempotent write behavior."""
    
    @pytest.mark.asyncio
    async def test_write_system_metric_with_msg_id(self, safe_writer, db_session):
        """SystemMetrics should use msg_id as primary identifier."""
        from api.core.models import SystemMetrics
        
        msg_id = "test-metric-1"
        timestamp = datetime.now(timezone.utc)
        
        # First write should succeed
        result1 = await safe_writer.write_system_metric(
            msg_id=msg_id,
            metric_name="cpu_usage",
            metric_value=75.5,
            metric_unit="percent",
            tags={"host": "server1"},
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        
        assert result1 is True
        
        # Verify the metric was written with msg_id as primary key
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 1
        assert str(metrics[0].id) == msg_id
        assert metrics[0].metric_name == "cpu_usage"
        assert metrics[0].metric_value == Decimal("75.5")
    
    @pytest.mark.asyncio
    async def test_duplicate_msg_id_idempotent(self, safe_writer, db_session):
        """Duplicate msg_id should not create duplicate records."""
        from api.core.models import SystemMetrics
        
        msg_id = "test-metric-duplicate"
        timestamp = datetime.now(timezone.utc)
        
        # First write
        result1 = await safe_writer.write_system_metric(
            msg_id=msg_id,
            metric_name="memory_usage",
            metric_value=60.0,
            metric_unit="percent",
            tags={"host": "server1"},
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        assert result1 is True
        
        # Second write with same msg_id should be idempotent
        result2 = await safe_writer.write_system_metric(
            msg_id=msg_id,  # Same msg_id
            metric_name="memory_usage",  # Same data
            metric_value=60.0,
            metric_unit="percent",
            tags={"host": "server1"},
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        assert result2 is True  # Still returns True, but no duplicate created
        
        # Verify only one record exists
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 1
        assert str(metrics[0].id) == msg_id
    
    @pytest.mark.asyncio
    async def test_different_msg_ids_create_separate_records(self, safe_writer, db_session):
        """Different msg_ids should create separate records."""
        from api.core.models import SystemMetrics
        
        timestamp = datetime.now(timezone.utc)
        
        # First metric
        result1 = await safe_writer.write_system_metric(
            msg_id="metric-1",
            metric_name="cpu_usage",
            metric_value=50.0,
            metric_unit="percent",
            tags={"host": "server1"},
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        
        # Second metric with different msg_id
        result2 = await safe_writer.write_system_metric(
            msg_id="metric-2",
            metric_name="cpu_usage",
            metric_value=75.0,
            metric_unit="percent",
            tags={"host": "server1"},
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        
        assert result1 is True
        assert result2 is True
        
        # Verify two records exist
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 2
        
        # Verify they have different IDs
        metric_ids = [str(m.id) for m in metrics]
        assert "metric-1" in metric_ids
        assert "metric-2" in metric_ids
    
    @pytest.mark.asyncio
    async def test_missing_msg_id_raises_error(self, safe_writer):
        """Missing msg_id should raise ValueError."""
        timestamp = datetime.now(timezone.utc)
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_system_metric(
                msg_id="",  # Empty msg_id
                metric_name="cpu_usage",
                metric_value=50.0,
                metric_unit="percent",
                tags={},
                schema_version="v2",
                source="system_monitor",
                timestamp=timestamp,
            )
        
        assert "msg_id is required" in str(exc_info.value)
        
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_system_metric(
                msg_id=None,  # None msg_id
                metric_name="cpu_usage",
                metric_value=50.0,
                metric_unit="percent",
                tags={},
                schema_version="v2",
                source="system_monitor",
                timestamp=timestamp,
            )
        
        assert "msg_id is required" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_system_metrics_processed_event_tracking(self, safe_writer, db_session):
        """SystemMetrics writes should track ProcessedEvent for exactly-once."""
        from api.core.models import SystemMetrics, ProcessedEvent
        
        msg_id = "test-metric-processed"
        timestamp = datetime.now(timezone.utc)
        
        # Write metric
        result = await safe_writer.write_system_metric(
            msg_id=msg_id,
            metric_name="disk_usage",
            metric_value=85.5,
            metric_unit="percent",
            tags={"host": "server1", "disk": "/dev/sda1"},
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        
        assert result is True
        
        # Verify ProcessedEvent was created
        events_result = await db_session.execute(select(ProcessedEvent))
        events = events_result.scalars().all()
        assert len(events) == 1
        assert events[0].msg_id == msg_id
        assert events[0].stream == "system_metrics"
    
    @pytest.mark.asyncio
    async def test_system_metrics_with_optional_fields(self, safe_writer, db_session):
        """SystemMetrics should handle optional fields correctly."""
        from api.core.models import SystemMetrics
        
        msg_id = "test-metric-optional"
        timestamp = datetime.now(timezone.utc)
        
        # Write with minimal required fields
        result = await safe_writer.write_system_metric(
            msg_id=msg_id,
            metric_name="network_latency",
            metric_value=25.5,
            metric_unit=None,  # Optional field
            tags={},  # Empty tags
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        
        assert result is True
        
        # Verify metric was written correctly
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 1
        assert metrics[0].metric_unit is None
        assert metrics[0].tags == {}
        assert str(metrics[0].id) == msg_id


class TestSystemMetricsIntegration:
    """Integration tests for SystemMetrics with consumer."""
    
    @pytest.mark.asyncio
    async def test_consumer_writer_integration(self, db_session):
        """Test SystemMetricsConsumer integration with new writer signature."""
        from api.services.system_metrics_consumer import SystemMetricsConsumer
        from api.events.bus import EventBus
        from api.events.dlq import DLQManager
        from unittest.mock import Mock
        
        # Mock dependencies
        bus = Mock(spec=EventBus)
        dlq = Mock(spec=DLQManager)
        redis_client = Mock()
        redis_client.get.return_value = None  # Kill switch off
        
        # Create consumer
        consumer = SystemMetricsConsumer(bus, dlq, redis_client)
        
        # Test data
        test_data = {
            "msg_id": "integration-test-1",
            "metric_name": "cpu_usage",
            "value": 75.5,
            "unit": "percent",
            "tags": {"host": "server1"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Process the message
        await consumer.process(test_data)
        
        # Verify metric was written
        from api.core.models import SystemMetrics
        metrics_result = await db_session.execute(select(SystemMetrics))
        metrics = metrics_result.scalars().all()
        assert len(metrics) == 1
        assert str(metrics[0].id) == "integration-test-1"
        assert metrics[0].metric_name == "cpu_usage"
        assert metrics[0].metric_value == Decimal("75.5")
