"""
Trade Engine - Core logic for trade execution and position management.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List
import uuid

from api.core.events import SignalEvent, TradeExecutionEvent, SignalAction


class TradeEngine:
    """Core trade execution engine - handles buy/sell lifecycle."""
    
    def __init__(self, session):
        self.session = session
    
    async def process_signal(self, signal: SignalEvent) -> TradeExecutionEvent:
        """Process trading signal with strict lifecycle rules."""
        # Create execution event
        execution = TradeExecutionEvent(
            signal_id=signal.signal_id,
            trade_id=str(uuid.uuid4()),
            agent_id=signal.agent_id,
            symbol=signal.symbol,
            action=signal.action,
            execution_mode="MOCK",
            timestamp=datetime.now(timezone.utc),
        )
        
        if signal.action == SignalAction.BUY:
            return await self._handle_buy_signal(signal, execution)
        elif signal.action == SignalAction.SELL:
            return await self._handle_sell_signal(signal, execution)
        else:
            # HOLD or other - no action
            execution.status = "IGNORED"
            return execution
    
    async def _handle_buy_signal(self, signal: SignalEvent, execution: TradeExecutionEvent) -> TradeExecutionEvent:
        """Handle BUY signal - open new position."""
        # Create BUY trade
        trade = {
            "agent_id": signal.agent_id,
            "strategy_id": str(uuid.uuid4()),  # TODO: Get from signal metadata
            "symbol": signal.symbol,
            "trade_type": "BUY",
            "quantity": Decimal("1.0"),  # TODO: Get from signal metadata
            "entry_price": signal.price,
            "confidence_score": Decimal(str(signal.confidence or "0")),
            "execution_mode": "MOCK",
            "trace_id": signal.signal_id,
            "trade_metadata": {"source": "signal"},
            "source": "trade_engine",
        }
        
        # Update execution with trade details
        execution.entry_price = signal.price
        execution.quantity = Decimal("1.0")
        execution.status = "OPEN"
        
        return execution
    
    async def _handle_sell_signal(self, signal: SignalEvent, execution: TradeExecutionEvent) -> TradeExecutionEvent:
        """Handle SELL signal - close most recent OPEN position."""
        # For now, simulate finding parent trade
        # In real implementation, this would query DB
        parent_trade = {
            "entry_price": Decimal("50000"),
            "quantity": Decimal("1.0"),
            "strategy_id": str(uuid.uuid4()),
        }
        
        # Calculate P&L
        pnl = (signal.price - parent_trade["entry_price"]) * parent_trade["quantity"]
        
        # Update execution with trade details
        execution.entry_price = parent_trade["entry_price"]
        execution.exit_price = signal.price
        execution.quantity = parent_trade["quantity"]
        execution.pnl_realized = pnl
        execution.status = "CLOSED"
        
        return execution
