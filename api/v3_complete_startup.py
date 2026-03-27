#!/usr/bin/env python3
"""Startup manager for the complete v3 event-driven agent pipeline."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from contextlib import suppress
from typing import Any

from redis.asyncio import Redis

from api.agents.v3_complete_system import (
    start_complete_v3_system,
    stop_complete_v3_system,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.redis_client import get_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PIPELINE_STREAMS: tuple[str, ...] = (
    "market_ticks",
    "signals",
    "orders",
    "executions",
    "trade_performance",
    "agent_grades",
    "ic_weights",
    "reflections",
    "proposals",
    "historical_insights",
    "notifications",
)

PIPELINE_FLOW_DESCRIPTION: tuple[str, ...] = (
    "market_ticks -> SignalGenerator -> signals",
    "signals -> ReasoningAgent -> orders",
    "orders -> ExecutionAgent -> executions",
    "executions -> TradePerformanceAgent -> trade_performance",
    "trade_performance -> GradeAgent -> agent_grades",
    "trade_performance -> ICUpdaterAgent -> ic_weights",
    "trade_performance -> ReflectionAgent -> reflections",
    "reflections -> StrategyProposerAgent -> proposals",
    "trade_performance -> HistoryAgent -> historical_insights",
    "all streams -> NotificationAgent -> notifications",
)


class CompleteV3SystemManager:
    """Manage lifecycle for the complete v3 system."""

    def __init__(self) -> None:
        self.bus: EventBus | None = None
        self.dlq: DLQManager | None = None
        self.redis: Redis | None = None
        self.agents: list[Any] = []
        self.running = False
        self.shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the complete v3 system and wait for shutdown."""
        try:
            logger.info("Starting complete v3 system")
            await self._initialize_runtime_dependencies()
            await self._create_streams()
            self.agents = await start_complete_v3_system(self.bus, self.dlq, self.redis)
            self.running = True
            self._install_signal_handlers()
            logger.info("Complete v3 system started with %s agents", len(self.agents))
            for flow_line in PIPELINE_FLOW_DESCRIPTION:
                logger.info("Pipeline: %s", flow_line)
            await self._run_forever()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Complete v3 system startup failed")
            log_structured("error", "v3_system_startup_failed", error=str(exc))
            raise

    async def _initialize_runtime_dependencies(self) -> None:
        self.redis = get_redis()
        await self.redis.ping()
        logger.info("Connected to Redis")
        self.bus = EventBus(self.redis)
        self.dlq = DLQManager(self.redis)

    async def _create_streams(self) -> None:
        if self.bus is None:
            raise RuntimeError("Event bus must be initialized before stream creation")

        logger.info("Creating %s streams", len(PIPELINE_STREAMS))
        for stream_name in PIPELINE_STREAMS:
            try:
                await self.bus.create_stream(stream_name)
                logger.info("Stream ready: %s", stream_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Stream creation failed for %s: %s", stream_name, exc)

    async def stop(self) -> None:
        """Stop all agents and close Redis resources."""
        logger.info("Stopping complete v3 system")
        self.running = False
        self.shutdown_event.set()

        if self.agents:
            await stop_complete_v3_system(self.agents)
            self.agents.clear()

        if self.redis is not None:
            await self.redis.close()

        logger.info("Complete v3 system stopped")

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

    def _signal_handler(self, signum: int, frame: object | None) -> None:
        del frame
        logger.info("Shutdown signal received: %s", signum)
        self.shutdown_event.set()

    async def _run_forever(self) -> None:
        """Keep process alive until a shutdown signal is received."""
        try:
            while self.running and not self.shutdown_event.is_set():
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("Complete v3 system cancelled")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Runtime error in complete v3 system")
            log_structured("error", "v3_system_runtime_error", error=str(exc))
        finally:
            await self.stop()


async def send_complete_test_events(redis_client: Redis) -> None:
    """Send representative test events across schema versions."""
    logger.info("Sending complete v3 test events")

    v3_market_tick = {
        "schema_version": "v3",
        "msg_id": "test-v3-tick-001",
        "trace_id": "trace-complete-001",
        "symbol": "AAPL",
        "price": 150.25,
        "volume": 1000,
        "timestamp": "2026-03-25T13:40:00Z",
        "source": "test_market",
    }
    await redis_client.xadd("market_ticks", v3_market_tick)
    logger.info("Sent v3 event %s", v3_market_tick["msg_id"])

    v2_event = {
        "schema_version": "v2",
        "msg_id": "test-v2-001",
        "symbol": "GOOGL",
        "price": 2500.50,
        "source": "old_system",
    }
    await redis_client.xadd("market_ticks", v2_event)
    logger.info("Sent v2 event %s", v2_event["msg_id"])

    missing_trace_event = {
        "schema_version": "v3",
        "msg_id": "test-no-trace-001",
        "symbol": "MSFT",
        "price": 300.75,
        "source": "test_no_trace",
    }
    await redis_client.xadd("market_ticks", missing_trace_event)
    logger.info("Sent no-trace event %s", missing_trace_event["msg_id"])


async def verify_complete_pipeline(redis_client: Redis) -> dict[str, int | str]:
    """Return stream message counts for pipeline verification."""
    logger.info("Verifying complete pipeline")
    await asyncio.sleep(2.0)

    results: dict[str, int | str] = {}
    for stream_name in PIPELINE_STREAMS:
        try:
            messages = await redis_client.xrange(stream_name)
            results[stream_name] = len(messages)
            logger.info("%s: %s messages", stream_name, len(messages))
        except Exception as exc:  # noqa: BLE001
            results[stream_name] = f"Error: {exc}"
            logger.warning("Failed to inspect stream %s: %s", stream_name, exc)

    try:
        dlq_messages = await redis_client.xrange("dlq:market_ticks")
        logger.info("dlq:market_ticks contains %s messages", len(dlq_messages))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to inspect DLQ stream: %s", exc)

    return results


async def main() -> None:
    """CLI entrypoint for launching the complete v3 system."""
    system_manager = CompleteV3SystemManager()
    redis = get_redis()

    try:
        await system_manager.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as exc:  # noqa: BLE001
        logger.error("System error: %s", exc)
        sys.exit(1)
    finally:
        await system_manager.stop()
        with suppress(Exception):
            await redis.close()


if __name__ == "__main__":
    logger.info("Launching complete v3 event-driven agent system")
    asyncio.run(main())
