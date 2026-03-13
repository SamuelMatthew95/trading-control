from __future__ import annotations

import time
import uuid
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from api.config import parse_csv_env, settings
from api.core.models import ErrorResponse
from api.database import get_settings_info, init_database, test_database_connection
from api.main_state import set_services
from api.observability import configure_logging, log_structured, metrics_store, request_id_ctx
from api.routes.analyze import router as analyze_router
from api.routes.health import router as health_router
from api.routes.monitoring import router as monitoring_router
from api.routes.performance import router as performance_router
from api.routes.trades import router as trades_router
from api.security import enforce_api_key
from api.services.learning import AgentLearningService
from api.services.memory import AgentMemoryService
from api.services.trading import TradingService
from multi_agent_orchestrator import MultiAgentOrchestrator

configure_logging(settings.LOG_LEVEL)

app = FastAPI(title="Trading Bot API", version="2.0.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_csv_env(settings.ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=parse_csv_env(settings.ALLOWED_HOSTS) or ["*"])

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(trades_router)
app.include_router(performance_router)
app.include_router(monitoring_router)


@app.middleware("http")
async def telemetry_and_security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request_id_ctx.set(request_id)

    enforce_api_key(request)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000
        metrics_store.register_request(elapsed, is_error=True)
        metrics_store.log_event("request_failed", method=request.method, path=request.url.path, latency_ms=round(elapsed, 2))
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
    log_structured("error", "Unhandled API exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal Server Error",
            detail="Unexpected server error",
            timestamp=datetime.utcnow(),
        ).model_dump(),
    )


@app.on_event("startup")
async def startup_event():
    db_ok = await test_database_connection()
    if not db_ok and settings.NODE_ENV == "production":
        raise RuntimeError("Database connection failed - check DATABASE_URL")

    await init_database()
    _ = get_settings_info()

    orchestrator = MultiAgentOrchestrator(settings.ANTHROPIC_API_KEY)
    set_services(TradingService(orchestrator), AgentLearningService(), AgentMemoryService())

    for agent in ["SIGNAL_AGENT", "RISK_AGENT", "CONSENSUS_AGENT", "SIZING_AGENT"]:
        metrics_store.update_agent(agent, "idle", health="ok", last_task="none")

    log_structured("info", "API startup complete", environment=settings.NODE_ENV, database_connected=db_ok)


handler = app
