from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text

from api.config import get_cors_origins, parse_csv_env, settings
from api.core.models import ErrorResponse
from api.database import Base, get_settings_info, init_database, test_database_connection
from api.db import AsyncSessionFactory, engine
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.main_state import set_services
from api.observability import (
    configure_logging,
    log_structured,
    metrics_store,
    request_id_ctx,
)
from api.redis_client import close_redis, get_redis
from api.routes.analyze import router as analyze_router
from api.routes.dashboard import router as dashboard_router
from api.routes.dlq import router as dlq_router
from api.routes.feedback import router as feedback_router
from api.routes.health import router as health_router
from api.routes.monitoring import router as monitoring_router
from api.routes.trades import router as trades_router
from api.routes.ws import router as ws_router
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.execution.reconciler import OrderReconciler
from api.services.feedback import FeedbackLearningService
from api.services.learning import (
    AgentLearningService,
    ICUpdater,
    ReflectionService,
    TradeEvaluator,
)
from api.services.market_ingestor import MarketIngestor
from api.services.memory import AgentMemoryService
from api.services.run_lifecycle import RunLifecycleService
from api.services.trading import TradingService

configure_logging(settings.LOG_LEVEL)
ENABLE_SIGNAL_SCHEDULER = os.getenv("ENABLE_SIGNAL_SCHEDULER", "true").lower() == "true"

try:
    from multi_agent_orchestrator import MultiAgentOrchestrator

    ORCHESTRATOR_AVAILABLE = True
except ImportError:
    MultiAgentOrchestrator = None
    ORCHESTRATOR_AVAILABLE = False


class BackgroundServiceTask:
    def __init__(self, task: asyncio.Task[None]):
        self.task = task

    async def stop(self) -> None:
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task


def initialize_services() -> None:
    if ORCHESTRATOR_AVAILABLE and MultiAgentOrchestrator:
        orchestrator = MultiAgentOrchestrator(settings.ANTHROPIC_API_KEY)
        trading_service = TradingService(orchestrator)
        log_structured("info", "MultiAgentOrchestrator loaded successfully")
    else:
        trading_service = TradingService(None)
        log_structured(
            "warning",
            "MOCK MODE: MultiAgentOrchestrator not available - using mock trading service",
        )

    learning_service = AgentLearningService()
    memory_service = AgentMemoryService()
    feedback_service = FeedbackLearningService()
    run_lifecycle_service = RunLifecycleService(
        learning_service, memory_service, feedback_service
    )
    set_services(
        trading_service,
        learning_service,
        memory_service,
        feedback_service,
        run_lifecycle_service,
    )

    for agent in ["SIGNAL_AGENT", "RISK_AGENT", "CONSENSUS_AGENT", "SIZING_AGENT"]:
        metrics_store.update_agent(agent, "idle", health="ok", last_task="none")


async def _retry_loop(stop_event: asyncio.Event) -> None:
    from api.main_state import get_run_lifecycle_service

    while not stop_event.is_set():
        try:
            await get_run_lifecycle_service().requeue_failed_scores_and_corrections()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Score retry loop failed", error=str(exc))
        try:
            await asyncio.wait(
                [asyncio.create_task(asyncio.sleep(3600)),
                 asyncio.create_task(stop_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            break


async def _record_system_metric(
    bus: EventBus,
    metric_name: str,
    value: float,
    labels: dict[str, Any] | None = None,
) -> None:
    labels = labels or {}
    payload = {
        "type": "system_metric",
        "metric_name": metric_name,
        "value": value,
        "labels": labels,
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(
                text(
                    "INSERT INTO system_metrics (id, metric_name, value, labels, timestamp) "
                    "VALUES (:id, :metric_name, :value, CAST(:labels AS JSONB), :timestamp)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "metric_name": metric_name,
                    "value": value,
                    "labels": json.dumps(labels, default=str),
                    "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
                },
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log_structured(
            "warning",
            "Unable to persist system metric",
            metric_name=metric_name,
            error=str(exc),
        )
    await bus.publish("system_metrics", payload)


async def collect_consumer_lag_metrics(bus: EventBus) -> None:
    stream_info = await bus.get_stream_info()
    for stream, info in stream_info.items():
        lag = float(info.get("lag", 0))
        labels = {
            "stream": stream,
            "length": int(info.get("length", 0)),
            "groups": int(info.get("groups", 0)),
        }
        await _record_system_metric(bus, f"stream_lag:{stream}", lag, labels)
        if lag > settings.MAX_CONSUMER_LAG_ALERT:
            await bus.publish(
                "risk_alerts",
                {
                    "type": "consumer_lag",
                    "stream": stream,
                    "lag": lag,
                    "limit": settings.MAX_CONSUMER_LAG_ALERT,
                    "message": f"Consumer lag elevated for {stream}",
                },
            )


async def monitor_consumer_lag(bus: EventBus, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await collect_consumer_lag_metrics(bus)
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Consumer lag monitor failed", error=str(exc))
        try:
            await asyncio.wait(
                [asyncio.create_task(asyncio.sleep(30)),
                 asyncio.create_task(stop_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            break


async def collect_llm_cost_metric(bus: EventBus, redis_client) -> None:
    today = date.today().isoformat()
    cost = float(await redis_client.get(f"llm:cost:{today}") or 0.0)
    await _record_system_metric(bus, "llm_cost_usd", cost, {"date": today})
    if cost >= settings.ANTHROPIC_COST_ALERT_USD:
        await bus.publish(
            "risk_alerts",
            {
                "type": "llm_cost",
                "cost": cost,
                "limit": settings.ANTHROPIC_COST_ALERT_USD,
                "message": "Anthropic daily cost alert threshold reached",
            },
        )


async def monitor_llm_cost(bus: EventBus, redis_client, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await collect_llm_cost_metric(bus, redis_client)
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "LLM cost monitor failed", error=str(exc))
        try:
            await asyncio.wait(
                [asyncio.create_task(asyncio.sleep(60)),
                 asyncio.create_task(stop_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    retry_task: asyncio.Task[None] | None = None
    market_ingestor: MarketIngestor | None = None
    execution_engine: ExecutionEngine | None = None
    order_reconciler: OrderReconciler | None = None
    reasoning_agent: ReasoningAgent | None = None
    trade_evaluator: TradeEvaluator | None = None
    reflection_service: ReflectionService | None = None
    ic_updater: ICUpdater | None = None
    consumer_lag_monitor: BackgroundServiceTask | None = None
    llm_cost_monitor_service: BackgroundServiceTask | None = None
    app.state.redis_client = None
    app.state.event_bus = None
    app.state.dlq_manager = None
    app.state.market_ingestor = None
    app.state.execution_engine = None
    app.state.order_reconciler = None
    app.state.reasoning_agent = None
    app.state.trade_evaluator = None
    app.state.reflection_service = None
    app.state.ic_updater = None
    app.state.db_engine = engine

    # Create stop event for graceful shutdown
    stop_event = asyncio.Event()

    try:
        db_ok = await test_database_connection()
        if not db_ok and settings.NODE_ENV == "production" and settings.DATABASE_URL:
            raise RuntimeError("Database connection failed - check DATABASE_URL")

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log_structured("info", "Database tables verified/created")

        try:
            redis_client = await get_redis()
        except Exception as exc:  # noqa: BLE001
            redis_client = None
            log_structured(
                "warning", "Redis unavailable during startup", error=str(exc)
            )
        app.state.redis_client = redis_client
        if redis_client is not None:
            event_bus = EventBus(redis_client)
            await event_bus.create_groups()
            dlq_manager = DLQManager(redis_client, event_bus)
            paper_broker = PaperBroker(redis_client)
            app.state.event_bus = event_bus
            app.state.dlq_manager = dlq_manager

            market_ingestor = MarketIngestor(event_bus)
            await market_ingestor.start()
            app.state.market_ingestor = market_ingestor

            reasoning_agent = ReasoningAgent(event_bus, dlq_manager, redis_client)
            await reasoning_agent.start()
            app.state.reasoning_agent = reasoning_agent

            trade_evaluator = TradeEvaluator(event_bus, dlq_manager, redis_client)
            await trade_evaluator.start()
            app.state.trade_evaluator = trade_evaluator

            reflection_service = ReflectionService(event_bus, redis_client)
            await reflection_service.start()
            app.state.reflection_service = reflection_service

            ic_updater = ICUpdater(redis_client)
            await ic_updater.start()
            app.state.ic_updater = ic_updater

            consumer_lag_monitor = BackgroundServiceTask(
                asyncio.create_task(
                    monitor_consumer_lag(event_bus, stop_event), name="consumer-lag-monitor"
                )
            )
            llm_cost_monitor_service = BackgroundServiceTask(
                asyncio.create_task(
                    monitor_llm_cost(event_bus, redis_client, stop_event),
                    name="llm-cost-monitor",
                )
            )

            if settings.BROKER_MODE == "paper":
                execution_engine = ExecutionEngine(
                    event_bus, dlq_manager, redis_client, paper_broker
                )
                await execution_engine.start()
                app.state.execution_engine = execution_engine

                order_reconciler = OrderReconciler(paper_broker)
                await order_reconciler.start()
                app.state.order_reconciler = order_reconciler

        initialize_services()
        if ENABLE_SIGNAL_SCHEDULER:
            retry_task = asyncio.create_task(_retry_loop(stop_event))

        log_structured(
            "info",
            "API startup complete",
            environment=settings.NODE_ENV,
            config_source=get_settings_info().get("config_source"),
        )
        yield
    finally:
        # Signal all background tasks to stop
        stop_event.set()
        
        if llm_cost_monitor_service is not None:
            await llm_cost_monitor_service.stop()
        if consumer_lag_monitor is not None:
            await consumer_lag_monitor.stop()
        if ic_updater is not None:
            await ic_updater.stop()
        if reflection_service is not None:
            await reflection_service.stop()
        if trade_evaluator is not None:
            await trade_evaluator.stop()
        if reasoning_agent is not None:
            await reasoning_agent.stop()
        if execution_engine is not None:
            await execution_engine.stop()
        if order_reconciler is not None:
            await order_reconciler.stop()
        if market_ingestor is not None:
            await market_ingestor.stop()
        if retry_task is not None:
            retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await retry_task
        await close_redis()
        await engine.dispose()


app = FastAPI(
    title="Trading Bot API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_origin_regex=r"https://trading-control-.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=parse_csv_env(settings.ALLOWED_HOSTS) or ["*"]
)

app.include_router(health_router)
app.include_router(health_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")
app.include_router(trades_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")
app.include_router(dlq_router, prefix="/api")
app.include_router(ws_router)


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/dashboard", status_code=307)


@app.middleware("http")
async def telemetry_and_security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request_id_ctx.set(request_id)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000
        metrics_store.register_request(elapsed, is_error=True)
        metrics_store.log_event(
            "request_failed",
            method=request.method,
            path=request.url.path,
            latency_ms=round(elapsed, 2),
        )
        raise

    elapsed = (time.perf_counter() - started) * 1000
    is_error = response.status_code >= 500
    metrics_store.register_request(elapsed, is_error=is_error)
    metrics_store.log_event(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=round(elapsed, 2),
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log_structured(
        "error", "Unhandled API exception", path=request.url.path, error=str(exc)
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal Server Error",
            detail="Unexpected server error",
            timestamp=datetime.now(timezone.utc),
        ).model_dump(),
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
