from __future__ import annotations

from typing import Optional

from api.services.learning import AgentLearningService
from api.services.trading import TradingService
from api.services.memory import AgentMemoryService

_learning_service: Optional[AgentLearningService] = None
_trading_service: Optional[TradingService] = None
_memory_service: Optional[AgentMemoryService] = None


def set_services(trading_service: TradingService, learning_service: AgentLearningService, memory_service: AgentMemoryService) -> None:
    global _trading_service, _learning_service, _memory_service
    _trading_service = trading_service
    _learning_service = learning_service
    _memory_service = memory_service


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
