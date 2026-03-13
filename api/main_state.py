from __future__ import annotations

from typing import Optional

from api.services.learning import AgentLearningService
from api.services.memory import AgentMemoryService
from api.services.options import OptionsService
from api.services.trading import TradingService

_learning_service: Optional[AgentLearningService] = None
_trading_service: Optional[TradingService] = None
_memory_service: Optional[AgentMemoryService] = None
_options_service: Optional[OptionsService] = None


def set_services(
    trading_service: TradingService,
    learning_service: AgentLearningService,
    memory_service: AgentMemoryService,
    options_service: OptionsService,
) -> None:
    global _trading_service, _learning_service, _memory_service, _options_service
    _trading_service = trading_service
    _learning_service = learning_service
    _memory_service = memory_service
    _options_service = options_service


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


def get_options_service() -> OptionsService:
    if _options_service is None:
        raise RuntimeError("Options service not initialized")
    return _options_service
