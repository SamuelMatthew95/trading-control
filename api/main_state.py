from __future__ import annotations

from typing import Optional

from api.services.trading import TradingService

_trading_service: Optional[TradingService] = None

def set_services(
    trading_service: TradingService,
) -> None:
    global _trading_service
    _trading_service = trading_service

def get_trading_service() -> TradingService:
    if _trading_service is None:
        raise RuntimeError("Trading service not initialized")
    return _trading_service
