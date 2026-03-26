#!/usr/bin/env python3
"""
V3 Event-Driven Agent System Startup

Starts the complete v3 system with:
- All 9 agents communicating via Redis streams
- SafeWriter v3 for atomic Postgres writes
- Full traceability with msg_id + trace_id
- Schema enforcement (reject v2 events)
- Event-driven processing (no sleeps)
"""

import asyncio
import logging
import signal
import sys
from contextlib import suppress

from redis.asyncio import Redis

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.redis_client import get_redis
from api.agents.v3_agent_system import start_v3_agent_system, stop_v3_agent_system
from api.observability import log_structured

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class V3SystemManager:
    """Manages the V3 agent system lifecycle."""
    
    def __init__(self):
        self.bus = None
        self.dlq = None
        self.redis = None
        self.agents = []
        self.running = False
        self.shutdown_event = asyncio.Event()
    
    async def start(self):
        """Start the V3 system."""
        try:
            log_structured("info", "v3_system_starting")
            
            # Initialize Redis
            self.redis = get_redis()
            await self.redis.ping()
            log_structured("info", "redis_connected")
            
            # Initialize EventBus and DLQ
            self.bus = EventBus(self.redis)
            self.dlq = DLQManager(self.redis)
            
            # Create streams (idempotent)
            streams = [
                "market_ticks", "signals", "orders", "executions",
                "trade_performance", "agent_grades", "ic_weights",
                "reflections", "proposals", "historical_insights",
                "notifications"
            ]
            
            for stream in streams:
                try:
                    await self.bus.create_stream(stream)
                    log_structured("info", "stream_created", stream=stream)
                except Exception as e:
                    log_structured("warning", "stream_creation_failed", stream=stream, error=str(e))
            
            # Start all agents
            self.agents = await start_v3_agent_system(self.bus, self.dlq, self.redis)
            self.running = True
            
            log_structured("info", "v3_system_started", agent_count=len(self.agents))
            
            # Setup signal handlers
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._signal_handler)
            
            # Keep system running
            await self._run_forever()
            
        except Exception as e:
            log_structured("error", "v3_system_startup_failed", error=str(e))
            raise
    
    async def stop(self):
        """Stop the V3 system."""
        log_structured("info", "v3_system_stopping")
        
        self.running = False
        self.shutdown_event.set()
        
        # Stop all agents
        if self.agents:
            await stop_v3_agent_system(self.agents)
            self.agents.clear()
        
        # Close Redis connection
        if self.redis:
            await self.redis.close()
        
        log_structured("info", "v3_system_stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        log_structured("info", "shutdown_signal_received", signal=signum)
        self.shutdown_event.set()
    
    async def _run_forever(self):
        """Keep the system running until shutdown."""
        try:
            while self.running and not self.shutdown_event.is_set():
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            log_structured("info", "v3_system_cancelled")
        except Exception as e:
            log_structured("error", "v3_system_runtime_error", error=str(e))
        finally:
            await self.stop()


async def send_test_events(redis_client):
    """Send test events to demonstrate the V3 system."""
    log_structured("info", "sending_test_events")
    
    # Test market tick
    market_tick = {
        "schema_version": "v3",
        "msg_id": "test-tick-001",
        "trace_id": "test-trace-001",
        "symbol": "AAPL",
        "price": 150.25,
        "volume": 1000,
        "timestamp": "2026-03-25T13:39:00Z",
        "source": "market_data"
    }
    
    await redis_client.xadd("market_ticks", market_tick)
    log_structured("info", "test_market_tick_sent", msg_id=market_tick["msg_id"])
    
    # Test v2 event (should be sent to DLQ)
    v2_event = {
        "schema_version": "v2",
        "msg_id": "test-v2-001",
        "symbol": "GOOGL",
        "price": 2500.50,
        "source": "old_system"
    }
    
    await redis_client.xadd("market_ticks", v2_event)
    log_structured("info", "test_v2_event_sent", msg_id=v2_event["msg_id"])


async def main():
    """Main entry point."""
    system = V3SystemManager()
    
    try:
        # Start the system
        await system.start()
    except KeyboardInterrupt:
        log_structured("info", "keyboard_interrupt")
    except Exception as e:
        log_structured("error", "system_error", error=str(e))
        sys.exit(1)
    finally:
        await system.stop()


if __name__ == "__main__":
    # Run the V3 system
    asyncio.run(main())
