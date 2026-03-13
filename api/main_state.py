from __future__ import annotations

from typing import Optional

from api.services.feedback import FeedbackLearningService
from api.services.learning import AgentLearningService
from api.services.memory import AgentMemoryService
from api.services.run_lifecycle import RunLifecycleService
from api.services.trading import TradingService

_learning_service: Optional[AgentLearningService] = None
_trading_service: Optional[TradingService] = None
_memory_service: Optional[AgentMemoryService] = None
_feedback_service: Optional[FeedbackLearningService] = None
_run_lifecycle_service: Optional[RunLifecycleService] = None


def set_services(
    trading_service: TradingService,
    learning_service: AgentLearningService,
    memory_service: AgentMemoryService,
    feedback_service: FeedbackLearningService,
    run_lifecycle_service: RunLifecycleService,
) -> None:
    global _trading_service, _learning_service, _memory_service, _feedback_service, _run_lifecycle_service
    _trading_service = trading_service
    _learning_service = learning_service
    _memory_service = memory_service
    _feedback_service = feedback_service
    _run_lifecycle_service = run_lifecycle_service


def get_trading_service() -> TradingService:
    if _trading_service is None:
        raise RuntimeError("Trading service not initialized")
    return _trading_service


def get_learning_service() -> AgentLearningService:
    if _learning_service is None:
        raise RuntimeError("Learning service not initialized")
    return _learning_service


def get_memory_service() -> AgentMemoryService:
    if _memory_service is None:
        raise RuntimeError("Memory service not initialized")
    return _memory_service


def get_feedback_service() -> FeedbackLearningService:
    if _feedback_service is None:
        raise RuntimeError("Feedback service not initialized")
    return _feedback_service


def get_run_lifecycle_service() -> RunLifecycleService:
    if _run_lifecycle_service is None:
        raise RuntimeError("Run lifecycle service not initialized")
    return _run_lifecycle_service
