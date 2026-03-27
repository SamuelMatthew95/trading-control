"""FastAPI dependency injection helpers for service and runtime state access."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.execution.reconciler import OrderReconciler
from api.services.market_ingestor import MarketIngestor


def get_event_bus(request: Request) -> EventBus:
    """Return the initialized EventBus instance from FastAPI app state."""
    obj = getattr(request.app.state, "event_bus", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="event_bus not initialised")
    return obj


def get_dlq_manager(request: Request) -> DLQManager:
    """Return the initialized DLQ manager from FastAPI app state."""
    obj = getattr(request.app.state, "dlq_manager", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="dlq_manager not initialised")
    return obj


def get_reconciler(request: Request) -> OrderReconciler:
    """Return the initialized reconciler from FastAPI app state."""
    obj = getattr(request.app.state, "reconciler", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="reconciler not initialised")
    return obj


def get_reasoning_agent(request: Request) -> ReasoningAgent:
    """Return the initialized reasoning agent from FastAPI app state."""
    obj = getattr(request.app.state, "reasoning_agent", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="reasoning_agent not initialised")
    return obj


def get_market_ingestor(request: Request) -> MarketIngestor:
    """Return the initialized market ingestor from FastAPI app state."""
    obj = getattr(request.app.state, "market_ingestor", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="market_ingestor not initialised")
    return obj


def get_redis(request: Request) -> Redis:
    """Return the initialized Redis client from FastAPI app state."""
    obj = getattr(request.app.state, "redis", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="redis not initialised")
    return obj


EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
DLQManagerDep = Annotated[DLQManager, Depends(get_dlq_manager)]
ReconcilerDep = Annotated[OrderReconciler, Depends(get_reconciler)]
ReasoningAgentDep = Annotated[ReasoningAgent, Depends(get_reasoning_agent)]
MarketIngestorDep = Annotated[MarketIngestor, Depends(get_market_ingestor)]
RedisDep = Annotated[Redis, Depends(get_redis)]
DBSessionDep = Annotated[AsyncSession, Depends(get_db)]
