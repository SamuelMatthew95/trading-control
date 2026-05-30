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

from api.config import get_cors_origins, parse_csv_env, settings
from api.constants import FieldName
from api.core.schemas import ErrorResponse
from api.database import engine, get_settings_info, init_database, test_database_connection
from api.events.bus import EventBus, ensure_all_streams_ready
from api.events.dlq import DLQManager
from api.in_memory_store import InMemoryStore
from api.mcp.server import mcp_app, mcp_lifespan_context
from api.observability import (
    bind_request_context,
    configure_logging,
    log_structured,
    metrics_store,
)
from api.redis_client import close_redis, get_redis
from api.redis_inspector import router as debug_redis_router
from api.routes.analyze import router as analyze_router
from api.routes.backtest import router as backtest_router
from api.routes.backtest import run_backtest_refresh_loop
from api.routes.dashboard_v2 import router as dashboard_v2_router
from api.routes.decisions import router as decisions_router
from api.routes.dlq import router as dlq_router
from api.routes.health import router as health_router
from api.routes.learning import router as learning_router
from api.routes.llm_health import router as llm_health_router
from api.routes.monitoring import router as monitoring_router
from api.routes.notifications import router as notifications_router
from api.routes.promotion import router as promotion_router
from api.routes.system import router as system_router
from api.routes.tools import router as tools_router
from api.routes.trades import router as trades_router
from api.routes.ws import router as ws_router
from api.runtime_state import (
    set_db_available,
    set_runtime_store,
)
from api.services.agent_state import AGENT_NAMES, AgentStateRegistry
from api.services.agent_supervisor import AgentSupervisor
from api.services.agents.pipeline_agents import (
    ChallengerAgent,
    GradeAgent,
    ICUpdater,
    NotificationAgent,
    ReflectionAgent,
    StrategyProposer,
)
from api.services.agents.proposal_applier import ProposalApplier
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.agents.risk_guardian import RiskGuardian
from api.services.event_pipeline import EventPipeline
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.lmstudio_provider import (
    _is_lmstudio_effectively_enabled,
)
from api.services.lmstudio_provider import (
    check_health as lm_studio_check_health,
)
from api.services.lmstudio_provider import (
    log_startup_config as lm_studio_log_startup_config,
)
from api.services.redis_store import set_redis_store
from api.services.signal_generator import SignalGenerator
from api.services.websocket_broadcaster import get_broadcaster
from api.workers.price_poller import poll_prices
from backtest.challenger import BASELINE_STRATEGY
from backtest.strategies import STRATEGIES

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

    mcp_lifespan_cm = mcp_lifespan_context()
    await mcp_lifespan_cm.__aenter__()

    try:
        _db_ok = False
        if settings.USE_MEMORY_MODE:
            log_structured(
                "info",
                "database_skipped_use_memory_mode",
                event_name="database_skipped_use_memory_mode",
            )
        else:
            # Try to initialize database with exponential-backoff retry (2s, 4s, 8s)
            _db_delays = [2, 4, 8]
            for _attempt, _delay in enumerate([0] + _db_delays, start=1):
                if _delay > 0:
                    log_structured(
                        "info",
                        "database_init_retry",
                        attempt=_attempt,
                        backoff_seconds=_delay,
                    )
                    await asyncio.sleep(_delay)
                try:
                    await init_database()
                    if await test_database_connection():
                        _db_ok = True
                        break
                except Exception:
                    log_structured(
                        "warning",
                        "database_init_attempt_failed",
                        attempt=_attempt,
                        max_attempts=len(_db_delays) + 1,
                        exc_info=True,
                    )

        if _db_ok:
            app.state.db_available = True
            set_db_available(True)
            app.state.in_memory_store.last_health = "db_ok"
            log_structured("info", "database_initialized_successfully")
        else:
            set_db_available(False)
            app.state.in_memory_store.last_health = "db_down"
            app.state.in_memory_store.add_notification(
                "Database connection failed after retries. Running in in-memory fallback mode.",
                level="warning",
                notification_type="startup",
            )
            try:
                engine.dispose()
            except Exception:
                pass
            log_structured(
                "warning",
                "database_connection_failed_using_memory",
                event_name="database_connection_failed_using_memory",
            )

        redis_client = await get_redis()
        app.state.redis_client = redis_client
        # RedisStore powers the REST notifications / decisions / llm-health
        # endpoints. Works in DB mode too — Redis is a hard dependency.
        from api.services.redis_store import RedisStore  # noqa: PLC0415

        redis_store = RedisStore(redis_client)
        app.state.redis_store = redis_store
        set_redis_store(redis_store)
        log_structured(
            "info",
            "redis_connected",
            event_name="redis_connected",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # LM Studio / LM Link — optional local GPU inference.
        # Non-blocking: failure here does NOT stop startup.
        # Bounded to 10 s so a black-holed Tailscale peer can't hold up startup
        # for the full LM_STUDIO_TIMEOUT_SECONDS (default 90 s).
        if _is_lmstudio_effectively_enabled():
            lm_studio_log_startup_config()
            try:
                _lm_ok = await asyncio.wait_for(lm_studio_check_health(), timeout=10.0)
            except asyncio.TimeoutError:
                _lm_ok = False
            log_structured(
                "info",
                "lmstudio_startup_check",
                lm_studio_enabled=True,
                lm_link_enabled=settings.LM_LINK_ENABLED,
                device_name=settings.LM_LINK_DEVICE_NAME or None,
                model=settings.LM_STUDIO_MODEL or None,
                local_inference_healthy=_lm_ok,
                fallback_provider=settings.LLM_PROVIDER,
                degraded_mode=not _lm_ok,
            )
        else:
            log_structured(
                "info",
                "lmstudio_startup_check",
                lm_studio_enabled=False,
                local_inference_healthy=False,
                fallback_provider=settings.LLM_PROVIDER,
                degraded_mode=False,
            )

        event_bus = EventBus(redis_client)
        dlq_manager = DLQManager(redis_client, event_bus)

        # STARTUP BARRIER: all streams and consumer groups must exist before
        # any consumer (pipeline, agents) starts. ensure_all_streams_ready()
        # creates, verifies, and self-heals any missing groups atomically.
        await ensure_all_streams_ready(redis_client)
        log_structured(
            "info",
            "redis_startup_barrier_passed",
            event_name="redis_startup_barrier_passed",
            event_type="system",
            msg_id="none",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

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

        # Backtest dashboard: warm the cache on boot, then refresh it hourly.
        backtest_refresh_task = asyncio.create_task(
            run_backtest_refresh_loop(), name="backtest-refresh"
        )
        app.state.backtest_refresh_task = backtest_refresh_task

        grade_agent = GradeAgent(event_bus, dlq_manager, agent_state=agent_state)
        reflection_agent = ReflectionAgent(event_bus, dlq_manager, agent_state=agent_state)
        # Inject grader reference so reflection can read the live eval buffer for
        # quant mistake clusters without an extra DB round-trip.
        reflection_agent._grade_agent = grade_agent

        agents = [
            SignalGenerator(event_bus, dlq_manager, agent_state=agent_state),
            ReasoningAgent(event_bus, dlq_manager, redis_client, agent_state=agent_state),
            ExecutionEngine(
                event_bus, dlq_manager, redis_client, paper_broker, agent_state=agent_state
            ),
            grade_agent,
            ICUpdater(event_bus, dlq_manager, redis_client, agent_state=agent_state),
            reflection_agent,
            StrategyProposer(event_bus, dlq_manager, agent_state=agent_state),
            NotificationAgent(event_bus, dlq_manager, redis_client, agent_state=agent_state),
            # One shadow ChallengerAgent per candidate strategy: each consumes the
            # live execution / trade_performance streams, is graded, and places NO
            # orders — it registers at SHADOW in the lifecycle. This is how the
            # non-baseline strategies get "hooked up" without skipping straight to
            # live; see backtest/README.md (Shadow lifecycle).
            *[
                ChallengerAgent(
                    event_bus,
                    dlq_manager,
                    challenger_config={FieldName.STRATEGY: _strategy_name},
                    agent_state=agent_state,
                )
                for _strategy_name in STRATEGIES
                if _strategy_name != BASELINE_STRATEGY
            ],
            # ProposalApplier closes the learning loop — it consumes
            # STREAM_PROPOSALS (written by GradeAgent / ReflectionAgent /
            # StrategyProposer) and applies the actions to Redis control-plane
            # keys that ExecutionEngine and ReasoningAgent read. Without this
            # consumer, low grades become DB rows that nobody acts on.
            ProposalApplier(event_bus, dlq_manager, redis_client, agent_state=agent_state),
        ]
        for agent in agents:
            await agent.start()
            log_structured(
                "info",
                "agent_subscription_ready",
                agent=agent.name,
                stream=getattr(agent, "stream", None),
                streams=getattr(agent, "streams", None),
            )
        app.state.agents = agents

        # RiskGuardian: periodic position monitor (stop-loss, take-profit, daily loss limit)
        risk_guardian = RiskGuardian(event_bus, redis_client)
        await risk_guardian.start()
        app.state.risk_guardian = risk_guardian
        app.state.redis_client = redis_client

        # AgentSupervisor: detects crashed agent tasks and restarts them
        supervisor = AgentSupervisor(event_bus, agents)
        await supervisor.start()
        app.state.supervisor = supervisor

        await broadcaster.broadcast(
            {
                FieldName.TYPE: "system",
                FieldName.STATUS: "running",
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
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
            config_source=get_settings_info().get(FieldName.CONFIG_SOURCE),
            database_mode="connected" if app.state.db_available else "in_memory_fallback",
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
        for task_name in ("poller_task", "keep_alive_task", "backtest_refresh_task"):
            task = getattr(app.state, task_name, None)
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        supervisor_instance = getattr(app.state, "supervisor", None)
        if supervisor_instance is not None:
            await supervisor_instance.stop()
        for agent in reversed(getattr(app.state, "agents", [])):
            await agent.stop()
        risk_guardian_instance = getattr(app.state, "risk_guardian", None)
        if risk_guardian_instance is not None:
            await risk_guardian_instance.stop()
        if pipeline is not None:
            await pipeline.stop()
        await broadcaster.stop()
        await close_redis()
        await engine.dispose()
        await mcp_lifespan_cm.__aexit__(None, None, None)


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
app.include_router(llm_health_router)
app.include_router(llm_health_router, prefix="/api")
# Register dashboard at both root and /api prefix so it works regardless of
# whether NEXT_PUBLIC_API_URL includes "/api" or not (matches health_router pattern)
app.include_router(dashboard_v2_router)
app.include_router(dashboard_v2_router, prefix="/api")
app.include_router(backtest_router)
app.include_router(backtest_router, prefix="/api")
app.include_router(learning_router)
app.include_router(learning_router, prefix="/api")
# Redis-backed REST persistence — required for in-memory mode UI hydration
app.include_router(notifications_router)
app.include_router(notifications_router, prefix="/api")
app.include_router(decisions_router)
app.include_router(decisions_router, prefix="/api")
app.include_router(system_router)
app.include_router(system_router, prefix="/api")
app.include_router(trades_router)
app.include_router(trades_router, prefix="/api")
app.include_router(monitoring_router)
app.include_router(monitoring_router, prefix="/api")
app.include_router(analyze_router)
app.include_router(analyze_router, prefix="/api")
app.include_router(tools_router)
app.include_router(tools_router, prefix="/api")
app.include_router(promotion_router)
app.include_router(promotion_router, prefix="/api")
app.include_router(ws_router)
app.mount("/mcp", mcp_app)


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
