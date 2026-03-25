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
from api.core.schemas import ErrorResponse
from api.database import (
    Base,
    get_settings_info,
    test_database_connection,
)
from api.db import AsyncSessionFactory, engine
from api.events.bus import EventBus, create_redis_groups
from api.events.dlq import DLQManager
from api.main_state import set_services
from api.observability import (
    bind_request_context,
    configure_logging,
    log_structured,
    metrics_store,
)
from api.redis_client import close_redis, get_redis
from api.routes.analyze import router as analyze_router
from api.routes.dlq import router as dlq_router
from api.routes.health import router as health_router
from api.routes.monitoring import router as monitoring_router
from api.routes.trades import router as trades_router
from api.routes.ws import router as ws_router
from api.routes.dashboard_v2 import router as dashboard_router
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.brokers.alpaca import AlpacaBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.execution.reconciler import OrderReconciler
from api.services.signal_generator import SignalGenerator
from api.services.system_metrics_consumer import SystemMetricsConsumer
from api.services.simple_consumers import (
    ExecutionsConsumer, RiskAlertsConsumer, LearningEventsConsumer, AgentLogsConsumer
)
from api.services.trading import TradingService
from api.services.websocket_broadcaster import get_broadcaster

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
        log_structured("info", "multi_agent_orchestrator_loaded")
    else:
        trading_service = TradingService(None)
        log_structured(
            "warning",
            "MOCK MODE: MultiAgentOrchestrator not available - using mock trading service",
        )

    set_services(
        trading_service,
    )

    for agent in ["SIGNAL_AGENT", "RISK_AGENT", "CONSENSUS_AGENT", "SIZING_AGENT"]:
        metrics_store.update_agent(agent, "idle", health="ok", last_task="none")




async def _record_system_metric(
    bus: EventBus,
    metric_name: str,
    value: float,
    labels: dict[str, Any] | None = None,
) -> None:
    labels = labels or {}
    # Generate msg_id ONCE at producer layer
    msg_id = str(uuid.uuid4())
    payload = {
        "msg_id": msg_id,  # ✅ CRITICAL: Add msg_id at producer layer
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
                    "id": msg_id,
                    "metric_name": metric_name,
                    "value": value,
                    "labels": json.dumps(labels, default=str),
                    "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
                },
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001
        # Only log ERROR if DB insert actually fails
        log_structured(
            "error",
            "System metric database write failed",
            metric_name=metric_name,
            error=str(e),
            msg_id=msg_id
        )
        # Still publish to stream - let consumer handle it
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
        await _record_system_metric(bus, "stream_lag", lag, {"stream": stream})
        if lag > settings.MAX_CONSUMER_LAG_ALERT:
            await bus.publish(
                "risk_alerts",
                {
                    "msg_id": str(uuid.uuid4()),  # ✅ Add msg_id at producer layer
                    "type": "consumer_lag",
                    "stream": stream,
                    "lag": lag,
                    "limit": settings.MAX_CONSUMER_LAG_ALERT,
                    "message": f"Consumer lag elevated for {stream}",
                },
            )


# Event-driven monitoring state
_consumer_lag_update = asyncio.Event()
_llm_cost_update = asyncio.Event()


async def on_message_processed(bus: EventBus, stream: str, lag: float) -> None:
    """Triggered when a message is processed - updates consumer lag immediately."""
    if lag > settings.MAX_CONSUMER_LAG_ALERT:
        await _record_system_metric(
            bus, "stream_lag", lag,
            {"stream": stream, "alert": "high"}
        )
        await bus.publish(
            "risk_alerts",
            {
                "msg_id": str(uuid.uuid4()),  # ✅ Add msg_id at producer layer
                "type": "consumer_lag",
                "stream": stream,
                "lag": lag,
                "limit": settings.MAX_CONSUMER_LAG_ALERT,
                "message": f"Consumer lag elevated for {stream}",
            },
        )
    # Signal that lag was updated
    _consumer_lag_update.set()


async def on_llm_cost_updated(bus: EventBus, redis_client, cost: float) -> None:
    """Triggered when LLM cost changes - updates immediately."""
    today = date.today().isoformat()
    await _record_system_metric(bus, "llm_cost_usd", cost, {"date": today})
    if cost >= settings.ANTHROPIC_COST_ALERT_USD:
        await bus.publish(
            "risk_alerts",
            {
                "msg_id": str(uuid.uuid4()),  # ✅ Add msg_id at producer layer
                "type": "llm_cost",
                "cost": cost,
                "limit": settings.ANTHROPIC_COST_ALERT_USD,
                "message": "Anthropic daily cost alert threshold reached",
            },
        )
    # Signal that cost was updated
    _llm_cost_update.set()


async def collect_llm_cost_metric(bus: EventBus, redis_client) -> None:
    """Collect LLM cost metric - called by event trigger or fallback."""
    today = date.today().isoformat()
    cost = float(await redis_client.get(f"llm:cost:{today}") or 0.0)
    await on_llm_cost_updated(bus, redis_client, cost)


async def monitor_consumer_lag(bus: EventBus, stop_event: asyncio.Event) -> None:
    """Event-driven consumer lag monitoring - no polling needed."""
    while not stop_event.is_set():
        try:
            # Wait for either lag update or stop event or timeout (fallback)
            await asyncio.wait_for(
                _consumer_lag_update.wait(),
                timeout=30  # Fallback check every 30s
            )
            _consumer_lag_update.clear()  # Reset for next update
        except asyncio.TimeoutError:
            # Fallback: collect current lag (in case we missed events)
            await collect_consumer_lag_metrics(bus)
        except Exception:  # noqa: BLE001
            log_structured("error", "Consumer lag monitor failed")


async def monitor_llm_cost(bus: EventBus, redis_client, stop_event: asyncio.Event) -> None:
    """Event-driven LLM cost monitoring - no polling needed."""
    while not stop_event.is_set():
        try:
            # Wait for either cost update or stop event or timeout (fallback)
            await asyncio.wait_for(
                _llm_cost_update.wait(),
                timeout=60  # Fallback check every 60s
            )
            _llm_cost_update.clear()  # Reset for next update
        except asyncio.TimeoutError:
            # Fallback: collect current cost (in case we missed events)
            await collect_llm_cost_metric(bus, redis_client)
        except Exception:  # noqa: BLE001
            log_structured("error", "LLM cost monitor failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    execution_engine: ExecutionEngine | None = None
    order_reconciler: OrderReconciler | None = None
    reasoning_agent: ReasoningAgent | None = None
    signal_generator: SignalGenerator | None = None
    system_metrics_consumer: SystemMetricsConsumer | None = None
    executions_consumer: ExecutionsConsumer | None = None
    risk_alerts_consumer: RiskAlertsConsumer | None = None
    learning_events_consumer: LearningEventsConsumer | None = None
    agent_logs_consumer: AgentLogsConsumer | None = None
    consumer_lag_monitor: BackgroundServiceTask | None = None
    llm_cost_monitor_service: BackgroundServiceTask | None = None
    app.state.redis_client = None
    app.state.event_bus = None
    app.state.dlq_manager = None
    app.state.execution_engine = None
    app.state.order_reconciler = None
    app.state.reasoning_agent = None
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
        log_structured("info", "database_initialized")

        # Run Alembic migrations to ensure database schema is up to date
        try:
            import subprocess
            import sys
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                cwd="api"
            )
            if result.returncode != 0:
                log_structured(
                    "warning", "alembic_migration_failed",
                    stderr=result.stderr, returncode=result.returncode
                )
            else:
                log_structured("info", "alembic_migration_completed")
        except Exception:  # noqa: BLE001
            log_structured("warning", "Alembic migration failed")

        try:
            redis_client = await get_redis()
        except Exception:  # noqa: BLE001
            redis_client = None
            log_structured("warning", "Redis unavailable during startup")
        app.state.redis_client = redis_client
        app.state.websocket_broadcaster = get_broadcaster()
        if redis_client is not None:
            # Trim market_ticks backlog on startup
            await redis_client.xtrim("market_ticks", maxlen=1000, approximate=True)
            log_structured("info", "market_ticks_stream_trimmed")
            
            # Ensure all Redis streams and consumer groups exist before starting any workers
            event_bus = EventBus(redis_client)
            await create_redis_groups(redis_client)

            # Start the WebSocket broadcaster
            await app.state.websocket_broadcaster.start(redis_client)

            dlq_manager = DLQManager(redis_client, event_bus)
            
            # Choose broker based on config
            if (
                settings.BROKER_MODE == "paper" 
                or not settings.ALPACA_API_KEY
            ):
                broker = PaperBroker(redis_client)
                log_structured("info", "paper_broker_enabled")
            else:
                broker = AlpacaBroker()
                log_structured(
                    "info", 
                    "alpaca_broker_enabled", 
                    paper=settings.ALPACA_PAPER, 
                    base_url=settings.ALPACA_BASE_URL
                )
            
            app.state.event_bus = event_bus
            app.state.dlq_manager = dlq_manager

            signal_generator = SignalGenerator(event_bus, dlq_manager)
            await signal_generator.start()
            app.state.signal_generator = signal_generator

            reasoning_agent = ReasoningAgent(event_bus, dlq_manager, redis_client)
            await reasoning_agent.start()
            app.state.reasoning_agent = reasoning_agent

            # Start system metrics consumer to clear backlog
            system_metrics_consumer = SystemMetricsConsumer(event_bus, dlq_manager, redis_client)
            await system_metrics_consumer.start()
            app.state.system_metrics_consumer = system_metrics_consumer

            # Start simple consumers for all remaining streams
            executions_consumer = ExecutionsConsumer(event_bus, dlq_manager, redis_client)
            await executions_consumer.start()
            app.state.executions_consumer = executions_consumer

            risk_alerts_consumer = RiskAlertsConsumer(event_bus, dlq_manager, redis_client)
            await risk_alerts_consumer.start()
            app.state.risk_alerts_consumer = risk_alerts_consumer

            learning_events_consumer = LearningEventsConsumer(event_bus, dlq_manager, redis_client)
            await learning_events_consumer.start()
            app.state.learning_events_consumer = learning_events_consumer

            agent_logs_consumer = AgentLogsConsumer(event_bus, dlq_manager, redis_client)
            await agent_logs_consumer.start()
            app.state.agent_logs_consumer = agent_logs_consumer

            consumer_lag_monitor = BackgroundServiceTask(
                asyncio.create_task(
                    monitor_consumer_lag(event_bus, stop_event),
                    name="consumer-lag-monitor",
                )
            )
            llm_cost_monitor_service = BackgroundServiceTask(
                asyncio.create_task(
                    monitor_llm_cost(event_bus, redis_client, stop_event),
                    name="llm-cost-monitor",
                )
            )

            execution_engine = ExecutionEngine(
                event_bus, dlq_manager, redis_client, broker
            )
            await execution_engine.start()
            app.state.execution_engine = execution_engine

            order_reconciler = OrderReconciler(broker)
            await order_reconciler.start()
            app.state.order_reconciler = order_reconciler

        initialize_services()

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
        if reasoning_agent is not None:
            await reasoning_agent.stop()
        if system_metrics_consumer is not None:
            await system_metrics_consumer.stop()
        if executions_consumer is not None:
            await executions_consumer.stop()
        if risk_alerts_consumer is not None:
            await risk_alerts_consumer.stop()
        if learning_events_consumer is not None:
            await learning_events_consumer.stop()
        if agent_logs_consumer is not None:
            await agent_logs_consumer.stop()
        if execution_engine is not None:
            await execution_engine.stop()
        if order_reconciler is not None:
            await order_reconciler.stop()
        if signal_generator is not None:
            await signal_generator.stop()

        # Stop WebSocket broadcaster
        if (
            hasattr(app.state, "websocket_broadcaster")
            and app.state.websocket_broadcaster is not None
        ):
            await app.state.websocket_broadcaster.stop()

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
app.include_router(monitoring_router, prefix="/api")
app.include_router(dlq_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(ws_router)


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/api/health", status_code=307)


@app.middleware("http")
async def telemetry_and_security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    bind_request_context(request_id)
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
    log_structured("error", "Unhandled API exception", path=request.url.path, exc_info=True)
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
