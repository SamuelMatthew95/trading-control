"""
FastAPI dependency injection for typed service access.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.execution.reconciler import OrderReconciler
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.market_ingestor import MarketIngestor
from api.redis_client import get_redis
from api.db import get_db


def get_event_bus(request: Request) -> EventBus:
    """Get EventBus from app state."""
    obj = getattr(request.app.state, "event_bus", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="event_bus not initialised")
    return obj


def get_dlq_manager(request: Request) -> DLQManager:
    """Get DLQManager from app state."""
    obj = getattr(request.app.state, "dlq_manager", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="dlq_manager not initialised")
    return obj


def get_reconciler(request: Request) -> OrderReconciler:
    """Get OrderReconciler from app state."""
    obj = getattr(request.app.state, "reconciler", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="reconciler not initialised")
    return obj


def get_reasoning_agent(request: Request) -> ReasoningAgent:
    """Get ReasoningAgent from app state."""
    obj = getattr(request.app.state, "reasoning_agent", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="reasoning_agent not initialised")
    return obj


def get_market_ingestor(request: Request) -> MarketIngestor:
    """Get MarketIngestor from app state."""
    obj = getattr(request.app.state, "market_ingestor", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="market_ingestor not initialised")
    return obj


def get_redis(request: Request) -> Redis:
    """Get Redis client from app state."""
    obj = getattr(request.app.state, "redis", None)
    if obj is None:
        raise HTTPException(status_code=503, detail="redis not initialised")
    return obj


# Type aliases for dependency injection
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
DLQManagerDep = Annotated[DLQManager, Depends(get_dlq_manager)]
ReconcilerDep = Annotated[OrderReconciler, Depends(get_reconciler)]
ReasoningAgentDep = Annotated[ReasoningAgent, Depends(get_reasoning_agent)]
MarketIngestorDep = Annotated[MarketIngestor, Depends(get_market_ingestor)]
RedisDep = Annotated[Redis, Depends(get_redis)]

# Re-export existing dependencies
from api.db import get_db

DBSessionDep = Annotated[get_db(), Depends(get_db)]
