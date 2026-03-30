from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text

from api.config import get_cors_origins, parse_csv_env, settings
from api.core.schemas import ErrorResponse
from api.database import engine, get_settings_info, test_database_connection
from api.events.bus import EventBus, create_redis_groups
from api.events.dlq import DLQManager
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
from api.services.agent_state import AGENT_NAMES, AgentStateRegistry
from api.services.agents.pipeline_agents import (
    GradeAgent,
    ICUpdater,
    NotificationAgent,
    ReasoningAgent,
    ReflectionAgent,
    StrategyProposer,
)
from api.services.event_pipeline import EventPipeline
from api.services.signal_generator import SignalGenerator
from api.services.websocket_broadcaster import get_broadcaster
from api.workers.price_poller import poll_prices

configure_logging(settings.LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_engine = engine
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
        db_ok = await test_database_connection()
        if not db_ok:
            raise RuntimeError("Database connection failed during startup")

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

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

        # Start price poller as a background task (replaces standalone worker)
        poller_task = asyncio.create_task(poll_prices(), name="price-poller")
        app.state.poller_task = poller_task
        log_structured("info", "price_poller_started", mode="background_task")

        agents = [
            SignalGenerator(event_bus, dlq_manager),
            ReasoningAgent(event_bus, dlq_manager, redis_client),
            GradeAgent(event_bus, dlq_manager),
            ICUpdater(event_bus, dlq_manager, redis_client),
            ReflectionAgent(event_bus, dlq_manager),
            StrategyProposer(event_bus, dlq_manager),
            NotificationAgent(event_bus, dlq_manager, redis_client),
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
        # Stop price poller background task
        poller = getattr(app.state, "poller_task", None)
        if poller is not None:
            poller.cancel()
            with suppress(asyncio.CancelledError):
                await poller
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
app.include_router(dlq_router, prefix="/api")
app.include_router(debug_redis_router, prefix="/api")
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
