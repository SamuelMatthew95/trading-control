"""
Canonical event models for trading system.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class SignalAction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class SignalEvent:
    """Canonical trading signal - source of truth."""
    signal_id: str
    agent_id: str
    symbol: str
    action: SignalAction
    price: Decimal
    timestamp: datetime
    confidence: float | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_redis_event(cls, event: dict[str, Any]) -> "SignalEvent":
        """Create SignalEvent from Redis stream data."""
        return cls(
            signal_id=str(event.get("msg_id") or event.get("signal_id") or str(uuid.uuid4())),
            agent_id=str(event.get("agent_id") or "unknown"),
            symbol=str(event.get("symbol") or ""),
            action=SignalAction(event.get("action", "HOLD")),
            price=Decimal(str(event.get("price", "0"))),
            confidence=event.get("confidence"),
            timestamp=datetime.fromisoformat(event.get("timestamp", datetime.utcnow().isoformat())),
            metadata=event.get("metadata"),
        )


@dataclass
class TradeExecutionEvent:
    """Result of trade execution - derived from SignalEvent."""
    signal_id: str
    trade_id: str
    agent_id: str
    symbol: str
    action: SignalAction
    entry_price: Decimal | None = None
    exit_price: Decimal | None = None
    quantity: Decimal = Decimal("0")
    pnl_realized: Decimal | None = None
    status: str = "OPEN"
    execution_mode: str = "MOCK"
    timestamp: datetime = None

    @property
    def is_buy(self) -> bool:
        return self.action == SignalAction.BUY

    @property
    def is_sell(self) -> bool:
        return self.action == SignalAction.SELL

    @property
    def is_open(self) -> bool:
        return self.status == "OPEN"

    @property
    def is_closed(self) -> bool:
        return self.status == "CLOSED"


@dataclass(frozen=True)
class PositionState:
    """Current position state - derived from trades."""
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    unrealized_pnl: Decimal | None = None
    last_trade_id: str | None = None
    updated_at: datetime = None

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0
