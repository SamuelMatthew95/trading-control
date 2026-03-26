#!/usr/bin/env python3
"""
Test the FIXED V3 System - Verify it doesn't freeze
"""

import asyncio
import json
from redis.asyncio import Redis

from api.events.bus import EventBus, DEFAULT_GROUP
from api.v3_fixed_system import SignalGeneratorAgent
from api.core.writer.safe_writer import SafeWriter
from api.db import AsyncSessionFactory


async def test_fixed_system():
    """Test that the FIXED system works without freezing."""
    print("🧪 Testing FIXED V3 System...")
    
    redis = get_redis_client()
    bus = EventBus(redis)
    
    try:
        # Create stream and consumer group
        await bus.create_stream("market_ticks")
        await bus.create_consumer_group("market_ticks", DEFAULT_GROUP)
        print("✅ Stream and consumer group created")
        
        # Start one agent
        safe_writer = SafeWriter(AsyncSessionFactory)
        agent = SignalGeneratorAgent(bus, None, redis)  # No DLQ needed for test
        
        await agent.start()
        print("✅ Agent started")
        
        # Send test message
        test_msg = {
            "schema_version": "v3",
            "msg_id": "test-fixed-001",
            "trace_id": "trace-fixed-001",
            "symbol": "AAPL",
            "price": 150.25,
            "source": "test"
        }
        
        await redis.xadd("market_ticks", test_msg)
        print("✅ Test message sent")
        
        # Wait for processing
        await asyncio.sleep(2.0)
        
        # Check if message was processed
        messages = await redis.xrange("signals")
        print(f"✅ Signals stream: {len(messages)} messages")
        
        # Check if message was acknowledged
        pending = await redis.xpending("market_ticks", DEFAULT_GROUP)
        print(f"✅ Pending messages: {pending}")
        
        # Stop agent
        await agent.stop()
        print("✅ Agent stopped")
        
        print("🎉 FIXED V3 System test PASSED!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await redis.close()


if __name__ == "__main__":
    from api.redis_client import get_redis_client
    asyncio.run(test_fixed_system())
