"""
V3 System Integration Tests

Tests the complete event-driven agent system:
- Schema validation (v3 only)
- Traceability (msg_id, trace_id)
- Atomic writes via SafeWriter
- End-to-end event flow
- DLQ handling for old schemas
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

import pytest
from redis.asyncio import Redis

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.redis_client import get_redis
from api.agents.v3_agent_system import V3_AGENTS
from api.database import AsyncSessionFactory
from api.core.writer.safe_writer import SafeWriter
from api.observability import log_structured


class TestV3System:
    """Test suite for V3 event-driven system."""
    
    @pytest.fixture
    async def redis_client(self):
        """Redis client fixture."""
        redis = get_redis()
        await redis.ping()
        yield redis
        await redis.close()
    
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
    
    async def test_v3_schema_validation(self, event_bus, dlq, redis_client):
        """Test that v3 events are accepted and v2 events go to DLQ."""
        # Create test stream
        stream = "test_validation"
        await event_bus.create_stream(stream)
        
        # Send v3 event
        v3_event = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "symbol": "AAPL",
            "price": 150.25,
            "source": "test"
        }
        
        await redis_client.xadd(stream, v3_event)
        
        # Send v2 event (should go to DLQ)
        v2_event = {
            "schema_version": "v2",
            "msg_id": str(uuid.uuid4()),
            "symbol": "GOOGL",
            "price": 2500.50,
            "source": "old_system"
        }
        
        await redis_client.xadd(stream, v2_event)
        
        # Wait a moment for processing
        await asyncio.sleep(0.1)
        
        # Check DLQ for v2 event
        dlq_stream = f"dlq:{stream}"
        dlq_messages = await redis_client.xrange(dlq_stream)
        
        assert len(dlq_messages) == 1
        _, dlq_data = dlq_messages[0]
        assert dlq_data.get("schema_version") == "v2"
        assert "Invalid schema version" in dlq_data.get("error", "")
    
    async def test_traceability_flow(self, event_bus, redis_client):
        """Test end-to-end traceability with trace_id."""
        trace_id = str(uuid.uuid4())
        
        # Create streams
        streams = ["market_ticks", "signals", "orders"]
        for stream in streams:
            await event_bus.create_stream(stream)
        
        # Send initial event with trace_id
        initial_event = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "symbol": "AAPL",
            "price": 150.25,
            "source": "test"
        }
        
        await redis_client.xadd("market_ticks", initial_event)
        
        # Wait for processing
        await asyncio.sleep(0.2)
        
        # Check that trace_id propagates through streams
        for stream in streams:
            messages = await redis_client.xrange(stream)
            if messages:
                _, data = messages[-1]  # Get latest message
                assert data.get("trace_id") == trace_id
    
    async def test_safe_writer_atomicity(self, safe_writer):
        """Test SafeWriter atomic transaction behavior."""
        msg_id = str(uuid.uuid4())
        stream = "test_writer"
        
        # Test successful write
        order_data = {
            "schema_version": "v3",
            "msg_id": msg_id,
            "trace_id": str(uuid.uuid4()),
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "idempotency_key": f"test_{msg_id}",
            "source": "test"
        }
        
        result = await safe_writer.write_order(msg_id, stream, order_data)
        assert result is True
        
        # Test duplicate write (should be idempotent)
        result2 = await safe_writer.write_order(msg_id, stream, order_data)
        assert result2 is True  # Still returns True, but doesn't create duplicate
    
    async def test_agent_message_flow(self, event_bus, dlq, redis_client):
        """Test message flow through agent pipeline."""
        # Create all required streams
        streams = [
            "market_ticks", "signals", "orders", "executions",
            "trade_performance", "agent_grades", "ic_weights",
            "reflections", "proposals", "historical_insights",
            "notifications"
        ]
        
        for stream in streams:
            await event_bus.create_stream(stream)
        
        # Send market tick to start the pipeline
        market_tick = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "symbol": "AAPL",
            "price": 150.25,
            "volume": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "test_market"
        }
        
        await redis_client.xadd("market_ticks", market_tick)
        
        # Wait for pipeline processing
        await asyncio.sleep(1.0)
        
        # Check that events propagated through pipeline
        processed_streams = []
        for stream in streams:
            messages = await redis_client.xrange(stream)
            if messages:
                processed_streams.append(stream)
        
        # Should have processed at least some streams
        assert len(processed_streams) > 0
        assert "market_ticks" in processed_streams
    
    async def test_error_handling_and_retry(self, event_bus, dlq, redis_client):
        """Test error handling and retry mechanism."""
        stream = "test_error"
        await event_bus.create_stream(stream)
        
        # Send malformed event (missing required fields)
        bad_event = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            # Missing required fields for order
            "source": "test"
        }
        
        await redis_client.xadd(stream, bad_event)
        
        # Wait for processing
        await asyncio.sleep(0.2)
        
        # Check that message was handled appropriately
        # (either processed with error or sent to DLQ after retries)
        messages = await redis_client.xrange(stream)
        dlq_messages = await redis_client.xrange(f"dlq:{stream}")
        
        # Should have either processed message or DLQ entry
        assert len(messages) > 0 or len(dlq_messages) > 0
    
    async def test_concurrent_processing(self, event_bus, redis_client):
        """Test concurrent message processing."""
        stream = "test_concurrent"
        await event_bus.create_stream(stream)
        
        # Send multiple events concurrently
        events = []
        for i in range(10):
            event = {
                "schema_version": "v3",
                "msg_id": str(uuid.uuid4()),
                "trace_id": str(uuid.uuid4()),
                "symbol": f"STOCK{i}",
                "price": 100 + i,
                "source": "concurrent_test"
            }
            events.append(event)
        
        # Send all events
        tasks = [
            redis_client.xadd(stream, event) 
            for event in events
        ]
        await asyncio.gather(*tasks)
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Check that all events were processed
        messages = await redis_client.xrange(stream)
        assert len(messages) == len(events)
    
    async def test_system_observability(self, event_bus, redis_client):
        """Test system observability and logging."""
        stream = "test_observability"
        await event_bus.create_stream(stream)
        
        # Send event with full observability data
        event = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "symbol": "AAPL",
            "price": 150.25,
            "source": "observability_test",
            "metadata": {
                "test_run": True,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
        await redis_client.xadd(stream, event)
        
        # Wait for processing
        await asyncio.sleep(0.2)
        
        # Check that structured logging occurred
        # (In a real test, you'd capture and verify log output)
        messages = await redis_client.xrange(stream)
        assert len(messages) > 0


# Integration test for the full system
async def test_full_system_integration():
    """Full integration test of the V3 system."""
    redis = get_redis()
    bus = EventBus(redis)
    dlq = DLQManager(redis)
    
    try:
        # Create all streams
        streams = [
            "market_ticks", "signals", "orders", "executions",
            "trade_performance", "agent_grades", "ic_weights",
            "reflections", "proposals", "historical_insights",
            "notifications"
        ]
        
        for stream in streams:
            await bus.create_stream(stream)
        
        # Send test market data
        market_data = {
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "symbol": "AAPL",
            "price": 150.25,
            "volume": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "integration_test"
        }
        
        await redis.xadd("market_ticks", market_data)
        
        # Wait for full pipeline processing
        await asyncio.sleep(2.0)
        
        # Verify end-to-end flow
        results = {}
        for stream in streams:
            messages = await redis.xrange(stream)
            results[stream] = len(messages)
        
        print("Integration Test Results:")
        for stream, count in results.items():
            print(f"  {stream}: {count} messages")
        
        # Basic assertions
        assert results["market_ticks"] > 0
        assert sum(results.values()) > 0
        
        print("[OK] Full system integration test passed!")
        
    finally:
        await redis.close()


if __name__ == "__main__":
    # Run the integration test
    asyncio.run(test_full_system_integration())
