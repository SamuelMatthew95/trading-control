#!/usr/bin/env python3
"""Container-friendly startup flow for the v3 trading system."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.redis_client import close_redis, get_redis
from api.services.market_ingestor import MarketIngestor
from api.v3_fixed_system import start_fixed_v3_system, stop_fixed_v3_system

if TYPE_CHECKING:
    from redis.asyncio import Redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PIPELINE_STEPS: tuple[str, ...] = (
    "market_ticks -> SignalGenerator -> signals",
    "signals -> ReasoningAgent -> orders",
    "orders -> ExecutionAgent -> executions",
    "executions -> TradePerformanceAgent -> trade_performance",
    "trade_performance -> GradeAgent -> agent_grades",
    "trade_performance -> ReflectionAgent -> reflection_outputs",
    "reflection_outputs -> StrategyProposerAgent -> proposals",
    "trade_performance -> HistoryAgent -> historical_insights",
    "all streams -> NotificationAgent -> notifications",
)


class ContainerV3System:
    """Run the v3 system with dependency checks and graceful shutdown."""

    def __init__(self) -> None:
        self.bus: EventBus | None = None
        self.dlq: DLQManager | None = None
        self.redis: Redis | None = None
        self.agents: list[Any] = []
        self.market_ingestor: MarketIngestor | None = None
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.web_server: Any = None

    async def wait_for_dependencies(self, timeout_seconds: int = 60) -> bool:
        """Wait for Redis and PostgreSQL to become available."""
        logger.info("Waiting for external dependencies")

        redis_ready = await self._wait_for_redis(timeout_seconds)
        db_ready = await self._wait_for_postgres(timeout_seconds)
        return redis_ready and db_ready

    async def _wait_for_redis(self, timeout_seconds: int) -> bool:
        for attempt in range(timeout_seconds):
            try:
                redis = await get_redis()
                await redis.ping()
                logger.info("Redis is ready")
                await close_redis()
                return True
            except Exception as exc:  # noqa: BLE001
                if attempt == timeout_seconds - 1:
                    logger.error("Redis not ready after %ss: %s", timeout_seconds, exc)
                    return False
                await asyncio.sleep(1)
        return False

    async def _wait_for_postgres(self, timeout_seconds: int) -> bool:
        from api.database import AsyncSessionFactory

        for attempt in range(timeout_seconds):
            try:
                async with AsyncSessionFactory() as session:
                    await session.execute(text("SELECT 1"))
                logger.info("PostgreSQL is ready")
                return True
            except Exception as exc:  # noqa: BLE001
                if attempt == timeout_seconds - 1:
                    logger.error("PostgreSQL not ready after %ss: %s", timeout_seconds, exc)
                    return False
                await asyncio.sleep(1)
        return False

    async def start(self) -> None:
        """Start all core runtime components."""
        try:
            logger.info("Starting v3 container system")
            if not await self.wait_for_dependencies():
                raise RuntimeError("Dependencies were not ready before startup")

            self.redis = await get_redis()
            logger.info("Connected to Redis")

            self.bus = EventBus(self.redis)
            self.dlq = DLQManager(self.redis, self.bus)
            self.agents = await start_fixed_v3_system(self.bus, self.dlq, self.redis)
            self.running = True

            self.market_ingestor = MarketIngestor(self.bus)
            await self.market_ingestor.start()

            logger.info("Started %s agents and market ingestor", len(self.agents))
            for step in PIPELINE_STEPS:
                logger.info("Pipeline: %s", step)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Container startup failed")
            log_structured("error", "container_system_startup_failed", exc_info=True)
            raise

    async def stop(self) -> None:
        """Shutdown all runtime services."""
        logger.info("Shutting down v3 container system")
        self.running = False
        self.shutdown_event.set()

        if self.web_server is not None:
            logger.info("Stopping web server")
            self.web_server.should_exit = True
            await asyncio.sleep(0.5)

        if self.market_ingestor is not None:
            logger.info("Stopping market ingestor")
            await self.market_ingestor.stop()

        if self.agents:
            try:
                await asyncio.wait_for(stop_fixed_v3_system(self.agents), timeout=10.0)
                logger.info("All agents stopped")
            except asyncio.TimeoutError:
                logger.warning("Timed out stopping agents; forcing shutdown")
                self.agents.clear()

        if self.redis is not None:
            await close_redis()
            logger.info("Redis connection closed")

        logger.info("v3 container system shutdown complete")

    async def run_with_signal_handling(self) -> None:
        """Run system with container-safe signal handlers."""
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, self._handle_sigterm)
        loop.add_signal_handler(signal.SIGINT, self._handle_sigint)

        try:
            await self.start()
            await self.shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("System cancelled")
        finally:
            await self.stop()

    def _handle_sigterm(self) -> None:
        logger.info("Received SIGTERM")
        self.shutdown_event.set()

    def _handle_sigint(self) -> None:
        logger.info("Received SIGINT")
        self.shutdown_event.set()


async def main() -> None:
    """Entry point for container deployment."""
    system = ContainerV3System()
    try:
        await system.run_with_signal_handling()
    except Exception as exc:  # noqa: BLE001
        log_structured("error", "container_system_error", exc_info=True)
        logger.error("Fatal error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    logger.info("Starting v3 container system entrypoint")
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
