#!/usr/bin/env python3
"""
V3 PRODUCTION SYSTEM - Truly Event-Driven, No Sleeps

✅ FULLY EVENT-DRIVEN - No polling or sleep loops
✅ PROPER SIGNAL HANDLING - asyncio.Event based shutdown
✅ ALL AGENTS START - Complete pipeline processing
✅ CLEAN ARCHITECTURE - Production-ready V3 system
"""

import asyncio
import logging
import signal
from typing import TYPE_CHECKING

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.redis_client import get_redis
from api.v3_fixed_system import start_fixed_v3_system, stop_fixed_v3_system
from api.observability import log_structured

if TYPE_CHECKING:
    from redis.asyncio import Redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class V3ProductionSystem:
    """Production-ready V3 system - truly event-driven."""

    def __init__(self):
        self.bus: EventBus = None
        self.dlq: DLQManager = None
        self.redis: 'Redis' = None
        self.agents = []
        self.running = False
        self.shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the V3 system (all agents, streams, DLQ)."""
        try:
            print("=" * 80)
            print("🚀 V3 PRODUCTION SYSTEM STARTING")
            print("=" * 80)
            print("✅ FULLY EVENT-DRIVEN - No polling or sleep")
            print("✅ PROPER SIGNAL HANDLING - asyncio.Event based")
            print("✅ ALL AGENTS START - Complete pipeline processing")
            print("✅ CLEAN ARCHITECTURE - Production-ready")
            print("=" * 80)

            # Initialize Redis
            print("[SYSTEM] Connecting to Redis...")
            self.redis = await get_redis()
            print("[SYSTEM] ✅ Redis connected")

            # Initialize EventBus and DLQ
            print("[SYSTEM] Initializing EventBus and DLQ...")
            self.bus = EventBus(self.redis)
            self.dlq = DLQManager(self.redis)
            print("[SYSTEM] ✅ EventBus and DLQ initialized")

            # Start ALL agents with proper stream setup
            print("[SYSTEM] Starting V3 agents...")
            self.agents = await start_fixed_v3_system(self.bus, self.dlq, self.redis)
            self.running = True

            print(f"[SYSTEM] ✅ Started {len(self.agents)} agents")
            print("\n[SYSTEM] 🔄 Active Pipeline:")
            print("  market_ticks → SignalGenerator → signals")
            print("  signals → ReasoningAgent → orders")
            print("  orders → ExecutionAgent → executions")
            print("  executions → TradePerformanceAgent → trade_performance")
            print("  trade_performance → GradeAgent → agent_grades")
            print("  trade_performance → ReflectionAgent → reflection_outputs")
            print("  reflection_outputs → StrategyProposerAgent → proposals")
            print("  ALL streams → NotificationAgent → notifications")

            print("\n[SYSTEM] 🎯 System is LIVE and ready for events!")
            print("[SYSTEM] 📝 Send events with:")
            print(
                "  redis-cli XADD market_ticks "
                "'{\"schema_version\":\"v3\",\"msg_id\":\"test-001\",\"trace_id\":\"trace-001\","
                "\"symbol\":\"AAPL\",\"price\":150.25,\"source\":\"test\"}'"
            )
            print("[SYSTEM] ⏹️  Press Ctrl+C to shutdown gracefully")

        except Exception as e:
            print(f"[SYSTEM] ❌ Startup failed: {e}")
            log_structured("error", "system_startup_failed", error=str(e))
            raise

    async def stop(self) -> None:
        """Stop system and cleanup resources (agents + Redis)."""
        print("\n[SYSTEM] 🛑 Shutting down V3 system...")

        self.running = False
        self.shutdown_event.set()

        # Stop all agents
        if self.agents:
            print(f"[SYSTEM] Stopping {len(self.agents)} agents...")
            await stop_fixed_v3_system(self.agents)
            self.agents.clear()
            print("[SYSTEM] ✅ All agents stopped")

        # Close Redis connection
        if self.redis:
            from api.redis_client import close_redis
            await close_redis()
            print("[SYSTEM] ✅ Redis connection closed")

        print("[SYSTEM] ✅ V3 system shutdown complete")


async def send_test_events(redis: 'Redis') -> None:
    """Send test events for dev/debug (called after system is live)."""
    print("\n[TEST] 📤 Sending test events to verify pipeline...")

    # Test 1: Valid v3 event (should flow through entire pipeline)
    v3_event = {
        "schema_version": "v3",
        "msg_id": "prod-test-001",
        "trace_id": "prod-trace-001",
        "symbol": "AAPL",
        "price": 150.25,
        "volume": 1000,
        "timestamp": "2026-03-25T13:43:00Z",
        "source": "production_test"
    }

    await redis.xadd("market_ticks", v3_event)
    print(f"[TEST] ✅ V3 event sent: {v3_event['msg_id']}")

    # Test 2: v2 event (should go to DLQ immediately)
    v2_event = {
        "schema_version": "v2",
        "msg_id": "prod-v2-001",
        "symbol": "GOOGL",
        "price": 2500.50,
        "source": "old_system"
    }

    await redis.xadd("market_ticks", v2_event)
    print(f"[TEST] ✅ V2 event sent (will go to DLQ): {v2_event['msg_id']}")

    # Test 3: Event without trace_id (should go to DLQ)
    no_trace_event = {
        "schema_version": "v3",
        "msg_id": "prod-no-trace-001",
        "symbol": "MSFT",
        "price": 300.75,
        "source": "production_test"
    }

    await redis.xadd("market_ticks", no_trace_event)
    print(f"[TEST] Event without trace_id sent: {no_trace_event['msg_id']}")

    print("[TEST] All test events sent - pipeline should be processing now")


async def verify_system_state(redis: 'Redis') -> None:
    """Verify system state after startup (optional verification)."""
    print("\n[VERIFY] 🔍 Checking system state...")

    # Check all streams have consumer groups
    all_streams = [
        "market_ticks", "signals", "orders", "executions",
        "trade_performance", "agent_grades", "reflection_outputs",
        "proposals", "notifications"
    ]

    active_streams = 0
    active_consumers = 0

    for stream in all_streams:
        try:
            # Check stream exists
            stream_info = await redis.xinfo_stream(stream)
            stream_length = stream_info.get('length', 0)

            # Check consumer groups
            groups = await redis.xinfo_groups(stream)

            # Count consumers
            total_consumers = 0
            for group in groups:
                consumers = await redis.xinfo_consumers(stream, group.get('name'))
                total_consumers += len(consumers)

            if total_consumers > 0:
                active_streams += 1
                active_consumers += total_consumers
                print(f"[VERIFY] ✅ {stream}: {stream_length} msgs, {len(groups)} groups, {total_consumers} consumers")
            else:
                print(f"[VERIFY] ⚠️  {stream}: {stream_length} msgs, {len(groups)} groups, 0 consumers")

        except Exception as e:
            print(f"[VERIFY] ❌ {stream}: Error - {e}")

    print(f"[VERIFY] 📊 Summary: {active_streams}/{len(all_streams)} active streams, {active_consumers} total consumers")

    # Check DLQ for v2 events
    try:
        dlq_messages = await redis.xrange("dlq:market_ticks")
        print(f"[VERIFY] 📋 DLQ: {len(dlq_messages)} messages")
    except Exception as e:
        print(f"[VERIFY] ⚠️  DLQ check failed: {e}")


async def main():
    """Main entry point for the V3 system - production-ready."""
    system = V3ProductionSystem()

    # Setup signal handling integrated with asyncio
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, system.shutdown_event.set)

    try:
        # Start the V3 system (all agents, streams, DLQ)
        await system.start()

        # Optionally send test events for dev/debug
        await send_test_events(system.redis)

        # Optionally verify system state
        await verify_system_state(system.redis)

        # Wait until shutdown signal is received (event-driven, no sleep)
        print("\n[SYSTEM] ⏳ Running - waiting for shutdown signal...")
        await system.shutdown_event.wait()

    except KeyboardInterrupt:
        print("\n[SYSTEM] ⌨️  Keyboard interrupt received")
    except Exception as e:
        log_structured("error", "system_error", error=str(e))
        print(f"\n[SYSTEM] ❌ Unexpected error: {e}")
    finally:
        # Stop system and cleanup
        await system.stop()


if __name__ == "__main__":
    print("🚀 STARTING V3 PRODUCTION SYSTEM")
    print("=" * 80)
    print("✅ FULLY EVENT-DRIVEN - No polling or sleep loops")
    print("✅ PROPER SIGNAL HANDLING - asyncio.Event based shutdown")
    print("✅ ALL AGENTS START - Complete pipeline processing")
    print("✅ CLEAN ARCHITECTURE - Production-ready V3 system")
    print("=" * 80)

    asyncio.run(main())
