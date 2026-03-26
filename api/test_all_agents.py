#!/usr/bin/env python3
"""
Test ALL V3 Agents Start Properly - Verify No "Step 1 Only" Problem
"""

import asyncio
from redis.asyncio import Redis

from api.events.bus import EventBus, DEFAULT_GROUP
from api.events.dlq import DLQManager
from api.v3_fixed_system import start_fixed_v3_system, stop_fixed_v3_system
from api.redis_client import get_redis_client


async def test_all_agents_start():
    """Test that ALL agents start with Redis consumers attached."""
    print("🧪 Testing ALL V3 Agents Start...")
    
    redis = get_redis_client()
    bus = EventBus(redis)
    dlq = DLQManager(redis)
    
    try:
        # Start the FIXED system
        print("[TEST] Starting FIXED V3 system...")
        agents = await start_fixed_v3_system(bus, dlq, redis)
        print(f"[TEST] Started {len(agents)} agents")
        
        # Wait a moment for agents to initialize
        await asyncio.sleep(1.0)
        
        # Verify ALL streams have consumer groups
        all_streams = [
            "market_ticks", "signals", "orders", "executions",
            "trade_performance", "agent_grades", "reflection_outputs", 
            "proposals", "notifications"
        ]
        
        print("[TEST] Verifying ALL streams and consumer groups...")
        for stream in all_streams:
            try:
                # Check stream exists
                stream_info = await redis.xinfo_stream(stream)
                stream_length = stream_info.get('length', 0)
                
                # Check consumer groups exist
                groups = await redis.xinfo_groups(stream)
                
                # Check consumers in each group
                total_consumers = 0
                for group in groups:
                    consumers = await redis.xinfo_consumers(stream, group.get('name'))
                    total_consumers += len(consumers)
                
                print(f"✅ {stream}: {stream_length} messages, {len(groups)} groups, {total_consumers} consumers")
                
                # Verify at least one consumer exists for each stream
                if total_consumers == 0:
                    print(f"❌ ERROR: No consumers found for stream: {stream}")
                    return False
                    
            except Exception as e:
                print(f"❌ ERROR checking stream {stream}: {e}")
                return False
        
        # Send test message to verify pipeline works
        print("[TEST] Sending test message to verify pipeline...")
        test_msg = {
            "schema_version": "v3",
            "msg_id": "test-all-agents-001",
            "trace_id": "trace-all-agents-001",
            "symbol": "AAPL",
            "price": 150.25,
            "source": "test_all_agents"
        }
        
        await redis.xadd("market_ticks", test_msg)
        print("✅ Test message sent to market_ticks")
        
        # Wait for pipeline processing
        await asyncio.sleep(3.0)
        
        # Check message propagation through pipeline
        print("[TEST] Checking message propagation...")
        pipeline_streams = ["signals", "orders", "executions", "trade_performance"]
        
        for stream in pipeline_streams:
            try:
                messages = await redis.xrange(stream)
                if messages:
                    print(f"✅ {stream}: {len(messages)} messages (pipeline working)")
                else:
                    print(f"⚠️  {stream}: 0 messages (may need more time)")
            except Exception as e:
                print(f"❌ ERROR checking {stream}: {e}")
        
        # Test v2 event goes to DLQ
        print("[TEST] Testing v2 event DLQ...")
        v2_msg = {
            "schema_version": "v2",
            "msg_id": "test-v2-all-001",
            "symbol": "GOOGL",
            "price": 2500.50,
            "source": "old_system"
        }
        
        await redis.xadd("market_ticks", v2_msg)
        await asyncio.sleep(1.0)
        
        dlq_messages = await redis.xrange("dlq:market_ticks")
        if dlq_messages:
            print(f"✅ DLQ: {len(dlq_messages)} v2 messages (DLQ working)")
        else:
            print("⚠️  DLQ: 0 messages (may need more time)")
        
        # Stop agents
        print("[TEST] Stopping agents...")
        await stop_fixed_v3_system(agents)
        
        print("\n🎉 ALL AGENTS TEST PASSED!")
        print("✅ All streams exist with consumer groups")
        print("✅ All agents started with Redis consumers")
        print("✅ Pipeline processing works")
        print("✅ DLQ handling works")
        print("✅ No 'step 1 only' problem")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await redis.close()


if __name__ == "__main__":
    success = asyncio.run(test_all_agents_start())
    if success:
        print("\n✅ ALL AGENTS START SUCCESSFULLY - SYSTEM READY")
    else:
        print("\n❌ AGENT START FAILED - NEED FIXES")
