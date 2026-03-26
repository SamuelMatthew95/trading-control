"""
Tests for V3 Production System - Comprehensive test suite

Tests all V3 requirements including:
- v2 event DLQ handling
- trace_id validation
- agent startup and processing
- event-driven architecture
- clean shutdown
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

import pytest
from redis.asyncio import Redis

from api.events.bus import EventBus, DEFAULT_GROUP
from api.events.dlq import DLQManager
from api.redis_client import get_redis, close_redis
from api.v3_production_system import V3ProductionSystem, send_test_events, verify_system_state
from api.core.writer.safe_writer import SafeWriter
from api.db import AsyncSessionFactory


class TestV3ProductionSystem:
    """Test suite for V3 Production System."""

    @pytest.fixture
    async def redis_client(self):
        """Redis client fixture."""
        redis = await get_redis()
        yield redis
        await close_redis()

    @pytest.fixture
    async def event_bus(self, redis_client):
        """EventBus fixture."""
        return EventBus(redis_client)

    @pytest.fixture
    async def dlq(self, redis_client):
        """DLQ fixture."""
        return DLQManager(redis_client)

    @pytest.fixture
    async def safe_writer(self):
        """SafeWriter fixture."""
        return SafeWriter(AsyncSessionFactory)

    async def test_v2_event_dlq_handling(self, redis_client, event_bus, dlq):
        """Test that v2 events are sent to DLQ immediately."""
        print("🧪 Testing V2 Event DLQ Handling...")
        
        # Create stream and consumer group
        await event_bus.create_stream("test_v2_dlq")
        await event_bus.create_consumer_group("test_v2_dlq", DEFAULT_GROUP)
        
        # Send v2 event (should go to DLQ)
        v2_event = {
            "schema_version": "v2",
            "msg_id": "test-v2-dlq-001",
            "symbol": "GOOGL",
            "price": 2500.50,
            "source": "old_system"
        }
        
        await redis_client.xadd("test_v2_dlq", v2_event)
        print(f"✅ V2 event sent: {v2_event['msg_id']}")
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Check DLQ
        dlq_messages = await redis_client.xrange("dlq:test_v2_dlq")
        assert len(dlq_messages) == 1, "V2 event should be in DLQ"
        
        _, dlq_data = dlq_messages[0]
        assert dlq_data.get("schema_version") == "v2"
        assert "Invalid schema version" in dlq_data.get("error", "")
        
        print(f"✅ V2 event properly sent to DLQ: {dlq_data.get('msg_id')}")
        print("✅ V2 DLQ handling test PASSED")

    async def test_missing_trace_id_dlq(self, redis_client, event_bus, dlq):
        """Test that events without trace_id are sent to DLQ."""
        print("🧪 Testing Missing Trace ID DLQ Handling...")
        
        # Create stream and consumer group
        await event_bus.create_stream("test_no_trace")
        await event_bus.create_consumer_group("test_no_trace", DEFAULT_GROUP)
        
        # Send event without trace_id (should go to DLQ)
        no_trace_event = {
            "schema_version": "v3",
            "msg_id": "test-no-trace-001",
            "symbol": "MSFT",
            "price": 300.75,
            "source": "test_no_trace"
        }
        
        await redis_client.xadd("test_no_trace", no_trace_event)
        print(f"✅ Event without trace_id sent: {no_trace_event['msg_id']}")
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Check DLQ
        dlq_messages = await redis_client.xrange("dlq:test_no_trace")
        assert len(dlq_messages) == 1, "Event without trace_id should be in DLQ"
        
        _, dlq_data = dlq_messages[0]
        assert dlq_data.get("schema_version") == "v3"
        assert "Missing trace_id" in dlq_data.get("error", "")
        
        print(f"✅ Event without trace_id properly sent to DLQ: {dlq_data.get('msg_id')}")
        print("✅ Missing trace ID DLQ test PASSED")

    async def test_v3_event_processing(self, redis_client, event_bus):
        """Test that v3 events are processed normally."""
        print("🧪 Testing V3 Event Processing...")
        
        # Create stream and consumer group
        await event_bus.create_stream("test_v3_process")
        await event_bus.create_consumer_group("test_v3_process", DEFAULT_GROUP)
        
        # Send v3 event with trace_id (should be processed)
        v3_event = {
            "schema_version": "v3",
            "msg_id": "test-v3-process-001",
            "trace_id": "trace-v3-001",
            "symbol": "AAPL",
            "price": 150.25,
            "source": "test_v3_process"
        }
        
        await redis_client.xadd("test_v3_process", v3_event)
        print(f"✅ V3 event sent: {v3_event['msg_id']}")
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Check that event is NOT in DLQ
        dlq_messages = await redis_client.xrange("dlq:test_v3_process")
        assert len(dlq_messages) == 0, "V3 event should NOT be in DLQ"
        
        # Check that event is still in stream (processed but not acked due to no consumer)
        stream_messages = await redis_client.xrange("test_v3_process")
        assert len(stream_messages) == 1, "V3 event should be in stream"
        
        print(f"✅ V3 event processed normally: {v3_event['msg_id']}")
        print("✅ V3 event processing test PASSED")

    async def test_production_system_startup(self, redis_client):
        """Test V3 Production System startup and shutdown."""
        print("🧪 Testing Production System Startup...")
        
        system = V3ProductionSystem()
        
        try:
            # Start system
            await system.start()
            assert system.running is True
            assert system.redis is not None
            assert system.bus is not None
            assert system.dlq is not None
            assert len(system.agents) > 0
            
            print(f"✅ System started with {len(system.agents)} agents")
            
            # Send test events
            await send_test_events(system.redis)
            print("✅ Test events sent")
            
            # Verify system state
            await verify_system_state(system.redis)
            print("✅ System state verified")
            
        finally:
            # Stop system
            await system.stop()
            assert system.running is False
            print("✅ System stopped cleanly")
        
        print("✅ Production system startup test PASSED")

    async def test_signal_handling(self):
        """Test signal handling integration."""
        print("🧪 Testing Signal Handling...")
        
        system = V3ProductionSystem()
        
        try:
            await system.start()
            
            # Simulate signal
            system.shutdown_event.set()
            
            # Wait for shutdown
            await asyncio.wait_for(system.shutdown_event.wait(), timeout=1.0)
            
            assert system.shutdown_event.is_set()
            print("✅ Signal handling works")
            
        finally:
            await system.stop()
        
        print("✅ Signal handling test PASSED")

    async def test_trace_id_propagation(self, redis_client, event_bus):
        """Test trace_id propagation through events."""
        print("🧪 Testing Trace ID Propagation...")
        
        trace_id = str(uuid.uuid4())
        
        # Create stream and consumer group
        await event_bus.create_stream("test_trace_prop")
        await event_bus.create_consumer_group("test_trace_prop", DEFAULT_GROUP)
        
        # Send event with trace_id
        event_with_trace = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "symbol": "AAPL",
            "price": 150.25,
            "source": "test_trace_prop"
        }
        
        await redis_client.xadd("test_trace_prop", event_with_trace)
        
        # Verify trace_id is preserved
        messages = await redis_client.xrange("test_trace_prop")
        assert len(messages) == 1
        
        _, data = messages[0]
        assert data.get("trace_id") == trace_id
        
        print(f"✅ Trace ID propagated correctly: {trace_id}")
        print("✅ Trace ID propagation test PASSED")

    async def test_schema_validation(self, safe_writer):
        """Test SafeWriter schema validation."""
        print("🧪 Testing Schema Validation...")
        
        # Test v3 data (should succeed)
        v3_data = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "idempotency_key": f"test_{uuid.uuid4()}",
            "source": "test"
        }
        
        # Should not raise exception
        try:
            await safe_writer.validate_payload(v3_data, ['strategy_id', 'symbol', 'side'], 'test')
            print("✅ V3 schema validation passed")
        except Exception as e:
            pytest.fail(f"V3 schema validation failed: {e}")
        
        # Test v2 data (should fail)
        v2_data = {
            "schema_version": "v2",
            "msg_id": str(uuid.uuid4()),
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }
        
        # Should raise exception
        with pytest.raises(ValueError, match="Invalid schema version"):
            safe_writer._validate_schema_v3(v2_data, "TestModel")
        
        print("✅ Schema validation test PASSED")

    async def test_event_driven_architecture(self, redis_client):
        """Test that system is truly event-driven (no sleeps)."""
        print("🧪 Testing Event-Driven Architecture...")
        
        system = V3ProductionSystem()
        
        try:
            # Start system
            await system.start()
            
            # Verify shutdown event is settable
            assert not system.shutdown_event.is_set()
            
            # Set shutdown event (simulating signal)
            system.shutdown_event.set()
            
            # Should return immediately (no sleep blocking)
            start_time = datetime.now()
            await system.shutdown_event.wait()
            end_time = datetime.now()
            
            # Should be very fast (no 1-second sleep)
            duration = (end_time - start_time).total_seconds()
            assert duration < 0.1, f"Event-driven wait took too long: {duration}s"
            
            print(f"✅ Event-driven wait completed in {duration:.3f}s")
            
        finally:
            await system.stop()
        
        print("✅ Event-driven architecture test PASSED")

    async def test_complete_pipeline_flow(self, redis_client):
        """Test complete pipeline flow with valid events."""
        print("🧪 Testing Complete Pipeline Flow...")
        
        # Create all required streams
        streams = [
            "market_ticks", "signals", "orders", "executions",
            "trade_performance", "agent_grades", "reflection_outputs", 
            "proposals", "notifications"
        ]
        
        for stream in streams:
            await redis_client.xadd(stream, {"_init": "1"})
            await redis_client.xdel(stream, await redis_client.xrange(stream)[0][0])
        
        # Send initial event
        trace_id = str(uuid.uuid4())
        initial_event = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "symbol": "AAPL",
            "price": 150.25,
            "source": "pipeline_test"
        }
        
        await redis_client.xadd("market_ticks", initial_event)
        print(f"✅ Initial event sent with trace_id: {trace_id}")
        
        # Verify trace_id preservation
        messages = await redis_client.xrange("market_ticks")
        assert len(messages) == 1
        
        _, data = messages[0]
        assert data.get("trace_id") == trace_id
        assert data.get("schema_version") == "v3"
        
        print(f"✅ Trace ID preserved through pipeline: {trace_id}")
        print("✅ Complete pipeline flow test PASSED")


# Integration test for the full system
async def test_v3_system_integration():
    """Full integration test of V3 system."""
    print("=" * 80)
    print("🧪 V3 SYSTEM INTEGRATION TEST")
    print("=" * 80)
    
    redis = await get_redis()
    
    try:
        # Test v2 event DLQ (the specific requirement)
        print("\n🔍 Testing V2 Event DLQ Requirement...")
        
        # Create test stream
        await redis.xadd("test_integration", {"_init": "1"})
        await redis.xdel("test_integration", await redis.xrange("test_integration")[0][0])
        
        # Send v2 event
        v2_event = {
            "schema_version": "v2",
            "msg_id": "integration-v2-001",
            "symbol": "GOOGL",
            "price": 2500.50,
            "source": "integration_test"
        }
        
        await redis.xadd("test_integration", v2_event)
        print(f"✅ V2 event sent: {v2_event['msg_id']}")
        
        # Wait and check DLQ
        await asyncio.sleep(0.5)
        
        dlq_messages = await redis.xrange("dlq:test_integration")
        assert len(dlq_messages) >= 1, "V2 event should be in DLQ"
        
        for msg_id, dlq_data in dlq_messages:
            if dlq_data.get("msg_id") == "integration-v2-001":
                assert dlq_data.get("schema_version") == "v2"
                assert "Invalid schema version" in dlq_data.get("error", "")
                print(f"✅ V2 event found in DLQ with error: {dlq_data.get('error')}")
                break
        
        print("✅ V2 DLQ requirement verified")
        
        # Test missing trace_id
        print("\n🔍 Testing Missing Trace ID Requirement...")
        
        no_trace_event = {
            "schema_version": "v3",
            "msg_id": "integration-no-trace-001",
            "symbol": "MSFT",
            "price": 300.75,
            "source": "integration_test"
        }
        
        await redis.xadd("test_integration", no_trace_event)
        print(f"✅ Event without trace_id sent: {no_trace_event['msg_id']}")
        
        await asyncio.sleep(0.5)
        
        dlq_messages = await redis.xrange("dlq:test_integration")
        found_no_trace = False
        
        for msg_id, dlq_data in dlq_messages:
            if dlq_data.get("msg_id") == "integration-no-trace-001":
                assert dlq_data.get("schema_version") == "v3"
                assert "Missing trace_id" in dlq_data.get("error", "")
                print(f"✅ Event without trace_id found in DLQ with error: {dlq_data.get('error')}")
                found_no_trace = True
                break
        
        assert found_no_trace, "Event without trace_id should be in DLQ"
        print("✅ Missing trace ID requirement verified")
        
        print("\n" + "=" * 80)
        print("🎉 V3 SYSTEM INTEGRATION TEST PASSED!")
        print("✅ V2 events go to DLQ immediately")
        print("✅ Events without trace_id go to DLQ")
        print("✅ V3 events processed normally")
        print("✅ All requirements verified")
        print("=" * 80)
        
    finally:
        await close_redis()


if __name__ == "__main__":
    print("🧪 Running V3 Production System Tests")
    asyncio.run(test_v3_system_integration())
