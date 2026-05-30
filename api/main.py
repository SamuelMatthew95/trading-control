from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from api.config import get_cors_origins, parse_csv_env, settings
from api.core.schemas import ErrorResponse
from api.mcp.server import mcp_app
from api.observability import (
    bind_request_context,
    configure_logging,
    log_structured,
    metrics_store,
)
from api.redis_inspector import router as debug_redis_router
from api.routes.analyze import router as analyze_router
from api.routes.backtest import router as backtest_router
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
from api.startup import lifespan

configure_logging(settings.LOG_LEVEL)


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
