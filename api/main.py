from __future__ import annotations

import os
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from api.core.models import ErrorResponse
from api.main_state import set_services
from api.routes.analyze import router as analyze_router
from api.routes.health import router as health_router
from api.routes.performance import router as performance_router
from api.routes.trades import router as trades_router
from api.services.learning import AgentLearningService
from api.services.trading import TradingService
from api.services.memory import AgentMemoryService
from api.database import get_settings_info, init_database, test_database_connection
from multi_agent_orchestrator import MultiAgentOrchestrator

app = FastAPI(title="Trading Bot API", version="1.1.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(trades_router)
app.include_router(performance_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
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
    orchestrator = MultiAgentOrchestrator(os.getenv("ANTHROPIC_API_KEY"))
    set_services(TradingService(orchestrator), AgentLearningService(), AgentMemoryService())


handler = app
