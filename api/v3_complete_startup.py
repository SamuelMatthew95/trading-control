#!/usr/bin/env python3
"""Startup manager for the complete v3 event-driven agent pipeline."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from typing import Any

from redis.asyncio import Redis

from api.v3_fixed_system import (
    start_fixed_v3_system as start_complete_v3_system,
    stop_fixed_v3_system as stop_complete_v3_system,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.redis_client import get_redis

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
        self.agents: dict[str, Any] = {}
        self.running = False
        self.shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the complete v3 system and wait for shutdown."""
        try:
            log_structured("info", "v3_startup_begin")
            await self._initialize_runtime_dependencies()
            bus, dlq, redis = self._validate_runtime_dependencies()
            await self._create_streams()
            self.agents = await start_complete_v3_system(bus, dlq, redis)
            self.running = True
            self._install_signal_handlers()
            log_structured("info", "v3_startup_ready", agent_count=len(self.agents))
            for flow_line in PIPELINE_FLOW_DESCRIPTION:
                log_structured("info", "v3_pipeline_step", step=flow_line)
            await self._run_forever()
        except Exception as exc:  # noqa: BLE001
            del exc
            log_structured("error", "v3_system_startup_failed", exc_info=True)
            raise

    async def _initialize_runtime_dependencies(self) -> None:
        """Initialize runtime dependencies required before agent startup."""
        self.redis = await get_redis()
        await self.redis.ping()
        log_structured("info", "v3_redis_connected")
        self.bus = EventBus(self.redis)
        self.dlq = DLQManager(self.redis, self.bus)

    def _validate_runtime_dependencies(self) -> tuple[EventBus, DLQManager, Redis]:
        """Return initialized runtime dependencies or raise a clear startup error."""
        if self.bus is None or self.dlq is None or self.redis is None:
            raise RuntimeError("Runtime dependencies were not initialized before startup")
        return self.bus, self.dlq, self.redis

    async def _create_streams(self) -> None:
        bus, _, _ = self._validate_runtime_dependencies()

        log_structured("info", "v3_stream_creation_begin", stream_count=len(PIPELINE_STREAMS))
        for stream_name in PIPELINE_STREAMS:
            try:
                await bus.create_stream(stream_name)
                log_structured("info", "v3_stream_ready", stream=stream_name)
            except Exception as exc:  # noqa: BLE001
                del exc
                log_structured(
                    "warning",
                    "v3_stream_create_failed",
                    stream=stream_name,
                    exc_info=True,
                )

    async def stop(self) -> None:
        """Stop all agents and close Redis resources."""
        log_structured("info", "v3_shutdown_begin")
        self.running = False
        self.shutdown_event.set()

        if self.agents:
            await stop_complete_v3_system(self.agents)
            self.agents.clear()

        if self.redis is not None:
            await self.redis.close()

        log_structured("info", "v3_shutdown_complete")

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

    def _signal_handler(self, signum: int, frame: object | None) -> None:
        del frame
        log_structured("info", "v3_shutdown_signal", signal=signum)
        self.shutdown_event.set()

    async def _run_forever(self) -> None:
        """Keep process alive until a shutdown signal is received."""
        try:
            while self.running and not self.shutdown_event.is_set():
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            log_structured("info", "v3_runtime_cancelled")
        except Exception as exc:  # noqa: BLE001
            log_structured("error", "v3_system_runtime_error", exc_info=True)
        finally:
            await self.stop()


async def send_complete_test_events(redis_client: Redis) -> None:
    """Send representative test events across schema versions."""
    log_structured("info", "v3_test_events_begin")

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
    log_structured("info", "v3_test_event_sent", msg_id=v3_market_tick["msg_id"])

    v2_event = {
        "schema_version": "v2",
        "msg_id": "test-v2-001",
        "symbol": "GOOGL",
        "price": 2500.50,
        "source": "old_system",
    }
    await redis_client.xadd("market_ticks", v2_event)
    log_structured("info", "v3_test_event_sent", msg_id=v2_event["msg_id"])

    missing_trace_event = {
        "schema_version": "v3",
        "msg_id": "test-no-trace-001",
        "symbol": "MSFT",
        "price": 300.75,
        "source": "test_no_trace",
    }
    await redis_client.xadd("market_ticks", missing_trace_event)
    log_structured("info", "v3_test_event_sent", msg_id=missing_trace_event["msg_id"])


async def verify_complete_pipeline(redis_client: Redis) -> dict[str, int | str]:
    """Return stream message counts for pipeline verification."""
    log_structured("info", "v3_pipeline_verify_begin")
    await asyncio.sleep(2.0)

    results: dict[str, int | str] = {}
    for stream_name in PIPELINE_STREAMS:
        try:
            messages = await redis_client.xrange(stream_name)
            results[stream_name] = len(messages)
            log_structured("info", "v3_pipeline_stream_count", stream=stream_name, count=len(messages))
        except Exception as exc:  # noqa: BLE001
            results[stream_name] = f"Error: {exc}"
            log_structured(
                "warning",
                "v3_pipeline_stream_read_failed",
                stream=stream_name,
                exc_info=True,
            )

    try:
        dlq_messages = await redis_client.xrange("dlq:market_ticks")
        log_structured("info", "v3_pipeline_dlq_count", count=len(dlq_messages))
    except Exception as exc:  # noqa: BLE001
        log_structured("warning", "v3_pipeline_dlq_read_failed", exc_info=True)

    return results

def start_complete_v3_background() -> tuple[CompleteV3SystemManager, asyncio.Task[None]]:
    """Start the complete v3 manager as a background task for app lifespan usage."""
    manager = CompleteV3SystemManager()
    task = asyncio.create_task(manager.start(), name="complete-v3-system")
    return manager, task


async def stop_complete_v3_background(
    manager: CompleteV3SystemManager | None,
    task: asyncio.Task[None] | None,
) -> None:
    """Stop and cleanup a background complete v3 manager task."""
    if manager is not None:
        await manager.stop()
    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
