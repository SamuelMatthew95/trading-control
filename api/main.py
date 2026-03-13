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
from api.routes.options import router as options_router
from api.routes.performance import router as performance_router
from api.routes.trades import router as trades_router
from api.security import enforce_api_key
from api.services.learning import AgentLearningService
from api.services.memory import AgentMemoryService
from api.services.options import OptionsService
from api.services.trading import TradingService
from multi_agent_orchestrator import MultiAgentOrchestrator

configure_logging(settings.LOG_LEVEL)

app = FastAPI(title="Trading Bot API", version="2.0.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_csv_env(settings.ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.middleware("http")(enforce_api_key)

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(trades_router)
app.include_router(performance_router)
app.include_router(options_router)
app.include_router(monitoring_router)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    token = request_id_ctx.set(request_id)
    started = time.perf_counter()
    metrics_store["requests_total"] = int(metrics_store.get("requests_total", 0)) + 1
    try:
        response = await call_next(request)
    except Exception:
        metrics_store["errors_total"] = int(metrics_store.get("errors_total", 0)) + 1
        raise
    finally:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        log_structured("request.complete", method=request.method, path=request.url.path, elapsed_ms=elapsed)
        request_id_ctx.reset(token)

    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    metrics_store["errors_total"] = int(metrics_store.get("errors_total", 0)) + 1
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error="Internal Server Error", detail=str(exc), timestamp=datetime.utcnow()).model_dump(),
    )


@app.on_event("startup")
async def startup_event():
    if not await test_database_connection():
        raise RuntimeError("Database connection failed - check DATABASE_URL")
    await init_database()
    _ = get_settings_info()
    orchestrator = MultiAgentOrchestrator(settings.ANTHROPIC_API_KEY)
    set_services(
        TradingService(orchestrator),
        AgentLearningService(),
        AgentMemoryService(),
        OptionsService(settings.ANTHROPIC_API_KEY, anthropic_model=settings.ANTHROPIC_MODEL),
    )


handler = app
