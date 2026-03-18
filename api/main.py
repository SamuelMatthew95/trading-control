from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from api.config import parse_csv_env, settings
from api.core.models import ErrorResponse
from api.database import (
    get_settings_info,
    init_database,
    test_database_connection,
)
from api.main_state import set_services
from api.observability import (
    configure_logging,
    log_structured,
    metrics_store,
    request_id_ctx,
)
from api.routes.analyze import router as analyze_router
from api.routes.dashboard import router as dashboard_router
from api.routes.feedback import router as feedback_router
from api.routes.health import router as health_router
from api.routes.monitoring import router as monitoring_router
from api.routes.trades import router as trades_router
from api.services.feedback import FeedbackLearningService
from api.services.learning import AgentLearningService
from api.services.memory import AgentMemoryService
from api.services.run_lifecycle import RunLifecycleService
from api.services.trading import TradingService

configure_logging(settings.LOG_LEVEL)

_signal_task = None
_score_retry_task = None
ENABLE_SIGNAL_SCHEDULER = os.getenv("ENABLE_SIGNAL_SCHEDULER", "true").lower() == "true"

# Try to import MultiAgentOrchestrator
try:
    from multi_agent_orchestrator import MultiAgentOrchestrator

    MultiAgentOrchestrator = MultiAgentOrchestrator
    ORCHESTRATOR_AVAILABLE = True
except ImportError:
    MultiAgentOrchestrator = None
    ORCHESTRATOR_AVAILABLE = False


# Define lifespan function before app creation
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    # Startup
    try:
        db_ok = await test_database_connection()
        if not db_ok and settings.NODE_ENV == "production" and settings.DATABASE_URL:
            raise RuntimeError("Database connection failed - check DATABASE_URL")
        await init_database()
    except Exception as e:
        if settings.NODE_ENV == "production":
            raise RuntimeError(f"Database initialization failed: {e}")

    yield

    # Shutdown
    # Cleanup can be added here if needed


app = FastAPI(
    title="Trading Bot API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
# CORS MUST BE FIRST
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_csv_env(settings.ALLOWED_ORIGINS),  # This handles localhost
    allow_origin_regex=r"https://trading-control-.*\.vercel\.app",  # This handles ALL Vercel previews
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# TrustedHost comes AFTER CORS
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=parse_csv_env(settings.ALLOWED_HOSTS) or ["*"]
)

app.include_router(health_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")
app.include_router(trades_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/dashboard", status_code=307)


@app.middleware("http")
async def telemetry_and_security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request_id_ctx.set(request_id)

    # API key enforcement removed - no authentication required

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
            timestamp=datetime.utcnow(),
        ).model_dump(),
    )


# Initialize services
settings_info = get_settings_info()

if ORCHESTRATOR_AVAILABLE and MultiAgentOrchestrator:
    orchestrator = MultiAgentOrchestrator(settings.ANTHROPIC_API_KEY)
    trading_service = TradingService(orchestrator)
    log_structured("info", "MultiAgentOrchestrator loaded successfully")
else:
    # Create a mock trading service for deployment without orchestrator
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

    if ENABLE_SIGNAL_SCHEDULER:
        # signal_scheduler removed - no longer available
        pass

    async def _retry_loop() -> None:
        while True:
            try:
                await run_lifecycle_service.requeue_failed_scores_and_corrections()
            except Exception:
                pass
            await asyncio.sleep(3600)

    _score_retry_task = asyncio.create_task(_retry_loop())

    # Log startup completion
    log_structured(
        "info",
        "API startup complete",
        environment=settings.NODE_ENV,
    )

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

# Mangum handler for AWS Lambda (not used by Vercel)
