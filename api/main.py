from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text

from api.config import get_cors_origins, parse_csv_env, settings
from api.core.schemas import ErrorResponse
from api.database import engine, get_settings_info, init_database, test_database_connection
from api.events.bus import EventBus, create_redis_groups
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.observability import (
    bind_request_context,
    configure_logging,
    log_structured,
    metrics_store,
)
from api.redis_client import close_redis, get_redis
from api.redis_inspector import router as debug_redis_router
from api.routes.dashboard_v2 import router as dashboard_v2_router
from api.routes.dlq import router as dlq_router
from api.routes.health import router as health_router
from api.routes.ws import router as ws_router
from api.runtime_state import (
    set_db_available,
    set_persistence_mode,
    set_runtime_store,
)
from api.services.agent_state import AGENT_NAMES, AgentStateRegistry
from api.services.agents.pipeline_agents import (
    GradeAgent,
    ICUpdater,
    NotificationAgent,
    ReflectionAgent,
    StrategyProposer,
)
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.event_pipeline import EventPipeline
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.signal_generator import SignalGenerator
from api.services.websocket_broadcaster import get_broadcaster
from api.workers.price_poller import poll_prices

configure_logging(settings.LOG_LEVEL)

_KEEP_ALIVE_INTERVAL = 10 * 60  # 10 minutes — prevents Render spin-down


async def _keep_alive() -> None:
    """Ping own /health endpoint every 10 min so Render never spins us down.

    Render sets RENDER_EXTERNAL_URL automatically on deployed services.
    No-ops in local dev where the env var is absent.
    """
    base_url = settings.RENDER_EXTERNAL_URL
    if not base_url:
        return  # not on Render — nothing to do
    url = f"{base_url.rstrip('/')}/health"
    await asyncio.sleep(60)  # let the app fully start before first ping
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            log_structured("debug", "keep_alive_ping", url=url, status=resp.status_code)
        except Exception:
            log_structured("warning", "keep_alive_ping_failed", url=url, exc_info=True)
        await asyncio.sleep(_KEEP_ALIVE_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_engine = engine
    app.state.in_memory_store = InMemoryStore()
    set_runtime_store(app.state.in_memory_store)
    app.state.db_available = False
    app.state.persistence_mode = settings.PERSISTENCE_MODE
    set_persistence_mode(settings.PERSISTENCE_MODE)
    set_db_available(False)
    app.state.redis_client = None
    app.state.event_bus = None
    app.state.event_pipeline = None
    app.state.dlq_manager = None
    app.state.agent_state = None
    app.state.agents = []

    pipeline: EventPipeline | None = None
    broadcaster = get_broadcaster()
    agent_state = AgentStateRegistry()

    try:
        # Try to initialize database
        try:
            await init_database()
            db_startup_ok = await test_database_connection()
            if db_startup_ok:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                app.state.db_available = True
                set_db_available(True)
                app.state.in_memory_store.last_health = "db_ok"
                log_structured("info", "database_initialized_successfully")
            else:
                # Database connection failed
                set_db_available(False)
                app.state.in_memory_store.last_health = "db_down"
                app.state.in_memory_store.add_notification(
                    "Database connection failed. Running in in-memory fallback mode.",
                    level="warning",
                    notification_type="startup",
                )
                # Dispose engine to prevent retry storms
                try:
                    engine.dispose()
                except Exception:
                    pass  # Best effort cleanup
                log_structured(
                    "warning",
                    "database_connection_failed_using_memory",
                    event_name="database_connection_failed_using_memory",
                )
        except Exception as e:
            # Database initialization failed
            set_db_available(False)
            app.state.in_memory_store.last_health = "db_down"
            app.state.in_memory_store.add_notification(
                f"Database initialization failed: {str(e)}. Running in in-memory fallback mode.",
                level="warning",
                notification_type="startup",
            )
            # Dispose engine to prevent retry storms
            try:
                engine.dispose()
            except Exception:
                pass  # Best effort cleanup
            log_structured(
                "warning",
                "database_initialization_failed_using_memory",
                event_name="database_initialization_failed_using_memory",
                exc_info=True,
            )

        redis_client = await get_redis()
        app.state.redis_client = redis_client
        log_structured(
            "info",
            "redis_connected",
            event_name="redis_connected",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        event_bus = EventBus(redis_client)
        dlq_manager = DLQManager(redis_client, event_bus)
        await create_redis_groups(redis_client)
        await broadcaster.start(redis_client)
        log_structured(
            "info",
            "websocket_started",
            event_name="websocket_started",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        pipeline = EventPipeline(event_bus, broadcaster, dlq_manager, agent_state=agent_state)
        await pipeline.start()

        app.state.event_bus = event_bus
        app.state.event_pipeline = pipeline
        app.state.websocket_broadcaster = broadcaster
        app.state.dlq_manager = dlq_manager
        app.state.agent_state = agent_state

        paper_broker = PaperBroker(redis_client)

        # Start price poller as a background task (replaces standalone worker)
        poller_task = asyncio.create_task(poll_prices(), name="price-poller")
        app.state.poller_task = poller_task
        log_structured("info", "price_poller_started", mode="background_task")

        # Keep-alive: self-ping /health every 10 min so Render never spins down
        keep_alive_task = asyncio.create_task(_keep_alive(), name="keep-alive")
        app.state.keep_alive_task = keep_alive_task

        agents = [
            SignalGenerator(event_bus, dlq_manager),
            ReasoningAgent(event_bus, dlq_manager, redis_client),
            ExecutionEngine(
                event_bus, dlq_manager, redis_client, paper_broker, agent_state=agent_state
            ),
            GradeAgent(event_bus, dlq_manager, agent_state=agent_state),
            ICUpdater(event_bus, dlq_manager, redis_client, agent_state=agent_state),
            ReflectionAgent(event_bus, dlq_manager, agent_state=agent_state),
            StrategyProposer(event_bus, dlq_manager, agent_state=agent_state),
            NotificationAgent(event_bus, dlq_manager, redis_client, agent_state=agent_state),
        ]
        for agent in agents:
            await agent.start()
        app.state.agents = agents

        await broadcaster.broadcast(
            {
                "type": "system",
                "status": "running",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        log_structured(
            "info",
            "system_startup_status",
            event_name="system_startup_status",
            redis="ok",
            pipeline="started",
            websocket="ready",
            agents_connected=len(app.state.agents),
            agents=list(AGENT_NAMES),
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            environment=settings.NODE_ENV,
            config_source=get_settings_info().get("config_source"),
            database_mode="connected" if app.state.db_available else "in_memory_fallback",
            persistence_mode=settings.PERSISTENCE_MODE,
        )
        yield
    except Exception:  # noqa: BLE001
        log_structured(
            "error",
            "startup_failed",
            event_name="startup_failed",
            event_type="system",
            msg_id="none",
            timestamp=datetime.now(timezone.utc).isoformat(),
            exc_info=True,
        )
        raise
    finally:
        for task_name in ("poller_task", "keep_alive_task"):
            task = getattr(app.state, task_name, None)
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        for agent in reversed(getattr(app.state, "agents", [])):
            await agent.stop()
        if pipeline is not None:
            await pipeline.stop()
        await broadcaster.stop()
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
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=parse_csv_env(settings.ALLOWED_HOSTS) or ["*"]
)

app.include_router(health_router)
app.include_router(health_router, prefix="/api")
app.include_router(dlq_router, prefix="/api")
app.include_router(debug_redis_router, prefix="/api")
# Register dashboard at both root and /api prefix so it works regardless of
# whether NEXT_PUBLIC_API_URL includes "/api" or not (matches health_router pattern)
app.include_router(dashboard_v2_router)
app.include_router(dashboard_v2_router, prefix="/api")
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
        raise

    elapsed = (time.perf_counter() - started) * 1000
    metrics_store.register_request(elapsed, is_error=response.status_code >= 500)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log_structured("error", "unhandled_exception", path=request.url.path, exc_info=True)
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
