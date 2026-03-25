#!/usr/bin/env python3
"""
V3 CONTAINER-READY SYSTEM - Fixes for Render/Kubernetes deployment

✅ PROPER SIGNAL HANDLING - asyncio.Event + loop.add_signal_handler
✅ NO SLEEP POLLING - immediate shutdown response
✅ DEPENDENCY WAITS - Redis/Postgres ready detection
✅ GRACEFUL SHUTDOWN - clean agent stop before SIGKILL
✅ CONTAINER OPTIMIZED - works in orchestrators
"""

import asyncio
import logging
import signal
import sys
from typing import TYPE_CHECKING

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.redis_client import get_redis, close_redis
from api.v3_fixed_system import start_fixed_v3_system, stop_fixed_v3_system
from api.services.market_ingestor import MarketIngestor
from api.observability import log_structured

if TYPE_CHECKING:
    from redis.asyncio import Redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ContainerV3System:
    """Container-ready V3 system with proper signal handling and dependency waits."""

    def __init__(self):
        self.bus: EventBus = None
        self.dlq: DLQManager = None
        self.redis: 'Redis' = None
        self.agents = []
        self.market_ingestor: MarketIngestor = None
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.web_server = None

    async def wait_for_dependencies(self, timeout: int = 60) -> bool:
        """Wait for Redis and PostgreSQL to be ready."""
        print("Waiting for dependencies...")

        # Wait for Redis
        redis_ready = False
        for i in range(timeout):
            try:
                redis = await get_redis()
                await redis.ping()
                redis_ready = True
                print("Redis is ready")
                await close_redis()
                break
            except Exception as e:
                if i == timeout - 1:
                    print(f"Redis not ready after {timeout}s: {e}")
                    return False
                await asyncio.sleep(1)

        # Wait for PostgreSQL
        db_ready = False
        for i in range(timeout):
            try:
                from api.db import AsyncSessionFactory
                async with AsyncSessionFactory() as session:
                    await session.execute("SELECT 1")
                db_ready = True
                print("PostgreSQL is ready")
                break
            except Exception as e:
                if i == timeout - 1:
                    print(f"PostgreSQL not ready after {timeout}s: {e}")
                    return False
                await asyncio.sleep(1)

        return redis_ready and db_ready

    async def start(self) -> None:
        """Start the V3 system with container optimizations."""
        try:
            print("=" * 60)
            print("V3 CONTAINER SYSTEM STARTING")
            print("=" * 60)

            # Wait for dependencies
            if not await self.wait_for_dependencies():
                raise RuntimeError("Dependencies not ready")

            # Initialize Redis
            print("Connecting to Redis...")
            self.redis = await get_redis()
            print("Redis connected")

            # Initialize EventBus and DLQ
            print("Initializing EventBus and DLQ...")
            self.bus = EventBus(self.redis)
            self.dlq = DLQManager(self.redis)
            print("EventBus and DLQ initialized")

            # Start ALL agents
            print("Starting V3 agents...")
            self.agents = await start_fixed_v3_system(self.bus, self.dlq, self.redis)
            self.running = True

            # Start Market Ingestor for automatic market data
            print("Starting market ingestor...")
            self.market_ingestor = MarketIngestor(self.bus)
            await self.market_ingestor.start()
            print("Market ingestor started - sending data every 10 seconds")

            print(f"Started {len(self.agents)} agents + market ingestor")
            print("\nActive Pipeline:")
            print("  market_ticks -> SignalGenerator -> signals")
            print("  signals -> ReasoningAgent -> orders")
            print("  orders -> ExecutionAgent -> executions")
            print("  executions -> TradePerformanceAgent -> trade_performance")
            print("  trade_performance -> GradeAgent -> agent_grades")
            print("  trade_performance -> ReflectionAgent -> reflection_outputs")
            print("  reflection_outputs -> StrategyProposerAgent -> proposals")
            print("  trade_performance -> HistoryAgent -> historical_insights")
            print("  ALL streams -> NotificationAgent -> notifications")

            print("\nSystem is LIVE")
            print("Market data: Automatic every 10 seconds")
            print("Manual events: redis-cli XADD market_ticks '{...}'")
            print("Waiting for shutdown signal (SIGTERM/SIGKILL)...")

        except Exception as e:
            print(f"Startup failed: {e}")
            log_structured("error", "container_system_startup_failed", error=str(e))
            raise

    async def stop(self) -> None:
        """Stop system with graceful shutdown for containers."""
        print("\nShutting down V3 system...")

        self.running = False
        self.shutdown_event.set()

        # Stop web server first
        if self.web_server:
            print("Stopping web server...")
            self.web_server.should_exit = True
            await asyncio.sleep(0.5)
            print("Web server stopped")

        # Stop market ingestor
        if self.market_ingestor:
            print("Stopping market ingestor...")
            await self.market_ingestor.stop()
            print("Market ingestor stopped")

        # Stop all agents with timeout
        if self.agents:
            print(f"Stopping {len(self.agents)} agents...")
            try:
                await asyncio.wait_for(
                    stop_fixed_v3_system(self.agents),
                    timeout=10.0
                )
                print("All agents stopped")
            except asyncio.TimeoutError:
                print("Agent stop timeout - forcing shutdown")
                self.agents.clear()

        # Close Redis connection
        if self.redis:
            await close_redis()
            print("Redis connection closed")

        print("V3 system shutdown complete")

    async def run_with_signal_handling(self):
        """Run system with proper asyncio signal handling."""
        # Setup asyncio signal handlers (container-safe)
        loop = asyncio.get_running_loop()

        # Handle SIGTERM (container shutdown)
        loop.add_signal_handler(signal.SIGTERM, self._handle_sigterm)

        # Handle SIGINT (Ctrl+C)
        loop.add_signal_handler(signal.SIGINT, self._handle_sigint)

        try:
            await self.start()

            # NO SLEEP - immediate event-driven wait
            await self.shutdown_event.wait()

        except asyncio.CancelledError:
            print("[SYSTEM] System cancelled")
        finally:
            await self.stop()

    def _handle_sigterm(self):
        """Handle SIGTERM from container orchestrator."""
        print("[SYSTEM] 📡 Received SIGTERM (container shutdown)")
        self.shutdown_event.set()

    def _handle_sigint(self):
        """Handle SIGINT (Ctrl+C)."""
        print("[SYSTEM] ⌨️  Received SIGINT (Ctrl+C)")
        self.shutdown_event.set()


async def main():
    """Main entry point for container deployment."""
    system = ContainerV3System()

    try:
        await system.run_with_signal_handling()
    except Exception as e:
        log_structured("error", "container_system_error", error=str(e))
        print(f"\nFatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("STARTING V3 CONTAINER SYSTEM")
    print("=" * 60)
    print("Container-ready for Render/Kubernetes")
    print("Proper signal handling")
    print("No sleep polling")
    print("Dependency waits")
    print("Graceful shutdown")
    print("=" * 60)
    
    asyncio.run(main())
