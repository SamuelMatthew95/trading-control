"""
Concurrent trade processor with row locking and serialized processing.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

CONCURRENCY SAFETY:
- Row locking prevents race conditions
- Serialized processing per symbol
- Atomic trade lifecycle enforcement
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict
import asyncio
import uuid

from sqlalchemy import select, and_, update
from sqlalchemy.dialects.postgresql import UUID
from api.core.events import SignalEvent, TradeExecutionEvent, SignalAction
from api.core.models.trade_ledger import TradeLedger


class ConcurrentTradeProcessor:
    """Thread-safe trade processor with row locking."""
    
    def __init__(self, session):
        self.session = session
        self._symbol_locks = {}  # Per-symbol processing locks
    
    async def process_signal_with_lock(self, signal: SignalEvent) -> TradeExecutionEvent:
        """Process signal with row-level locking to prevent race conditions."""
        
        # Acquire symbol-level lock for serialized processing
        async with self._acquire_symbol_lock(signal.symbol):
            return await self._execute_with_row_lock(signal)
    
    async def _acquire_symbol_lock(self, symbol: str):
        """Acquire per-symbol lock for serialized processing."""
        if symbol not in self._symbol_locks:
            self._symbol_locks[symbol] = asyncio.Lock()
        
        return self._symbol_locks[symbol]
    
    async def _execute_with_row_lock(self, signal: SignalEvent) -> TradeExecutionEvent:
        """Execute signal with database row locking."""
        from sqlalchemy import text
        
        # Start transaction with row lock
        async with self.session.begin():
            if signal.action == SignalAction.BUY:
                return await self._handle_buy_with_lock(signal)
            elif signal.action == SignalAction.SELL:
                return await self._handle_sell_with_lock(signal)
            else:
                return self._create_ignored_execution(signal)
    
    async def _handle_buy_with_lock(self, signal: SignalEvent) -> TradeExecutionEvent:
        """Handle BUY with row locking."""
        
        # Lock potential conflicting rows for this symbol/agent
        lock_query = text("""
            SELECT trade_id FROM trade_ledger 
            WHERE agent_id = :agent_id AND symbol = :symbol AND status = 'OPEN'
            FOR UPDATE SKIP LOCKED
        """)
        
        await self.session.execute(lock_query, {
            "agent_id": signal.agent_id,
            "symbol": signal.symbol,
        })
        
        # Create BUY trade
        trade = TradeLedger(
            agent_id=signal.agent_id,
            strategy_id=uuid.uuid4(),
            symbol=signal.symbol,
            trade_type="BUY",
            quantity=Decimal("1.0"),
            entry_price=signal.price,
            confidence_score=Decimal(str(signal.confidence or "0")),
            execution_mode="MOCK",
            trace_id=signal.signal_id,
            trade_metadata={"source": "signal"},
            source="concurrent_processor",
        )
        
        self.session.add(trade)
        await self.session.flush()
        
        return TradeExecutionEvent(
            signal_id=signal.signal_id,
            trade_id=trade.trade_id,
            agent_id=signal.agent_id,
            symbol=signal.symbol,
            action=SignalAction.BUY,
            entry_price=signal.price,
            quantity=Decimal("1.0"),
            status="OPEN",
            execution_mode="MOCK",
            timestamp=datetime.now(timezone.utc),
        )
    
    async def _handle_sell_with_lock(self, signal: SignalEvent) -> TradeExecutionEvent:
        """Handle SELL with row locking to prevent double-closes."""
        
        # Lock and fetch most recent OPEN position with row lock
        lock_query = text("""
            SELECT trade_id, entry_price, quantity, strategy_id 
            FROM trade_ledger 
            WHERE agent_id = :agent_id 
              AND symbol = :symbol 
              AND trade_type = 'BUY' 
              AND status = 'OPEN'
            FOR UPDATE SKIP LOCKED
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        result = await self.session.execute(lock_query, {
            "agent_id": signal.agent_id,
            "symbol": signal.symbol,
        })
        parent_row = result.first()
        
        if not parent_row:
            return self._create_rejected_execution(signal, "No open position to close")
        
        # Calculate P&L
        pnl = (signal.price - parent_row.entry_price) * parent_row.quantity
        
        # Close parent trade
        close_query = update(TradeLedger).where(
            TradeLedger.trade_id == parent_row.trade_id
        ).values(
            status="CLOSED",
            pnl_realized=pnl,
            updated_at=datetime.now(timezone.utc),
        )
        
        await self.session.execute(close_query)
        
        # Create SELL trade
        sell_trade = TradeLedger(
            agent_id=signal.agent_id,
            strategy_id=parent_row.strategy_id,
            symbol=signal.symbol,
            trade_type="SELL",
            quantity=parent_row.quantity,
            entry_price=parent_row.entry_price,
            exit_price=signal.price,
            pnl_realized=pnl,
            status="CLOSED",
            confidence_score=Decimal(str(signal.confidence or "0")),
            execution_mode="MOCK",
            trace_id=signal.signal_id,
            parent_trade_id=parent_row.trade_id,
            trade_metadata={"source": "signal"},
            source="concurrent_processor",
        )
        
        self.session.add(sell_trade)
        await self.session.flush()
        
        return TradeExecutionEvent(
            signal_id=signal.signal_id,
            trade_id=sell_trade.trade_id,
            agent_id=signal.agent_id,
            symbol=signal.symbol,
            action=SignalAction.SELL,
            entry_price=parent_row.entry_price,
            exit_price=signal.price,
            quantity=parent_row.quantity,
            pnl_realized=pnl,
            status="CLOSED",
            execution_mode="MOCK",
            timestamp=datetime.now(timezone.utc),
        )
    
    def _create_ignored_execution(self, signal: SignalEvent) -> TradeExecutionEvent:
        """Create ignored execution for non-trading signals."""
        return TradeExecutionEvent(
            signal_id=signal.signal_id,
            trade_id=str(uuid.uuid4()),
            agent_id=signal.agent_id,
            symbol=signal.symbol,
            action=signal.action,
            status="IGNORED",
            execution_mode="MOCK",
            timestamp=datetime.now(timezone.utc),
        )
    
    def _create_rejected_execution(self, signal: SignalEvent, reason: str) -> TradeExecutionEvent:
        """Create rejected execution."""
        return TradeExecutionEvent(
            signal_id=signal.signal_id,
            trade_id=str(uuid.uuid4()),
            agent_id=signal.agent_id,
            symbol=signal.symbol,
            action=signal.action,
            status="REJECTED",
            execution_mode="MOCK",
            timestamp=datetime.now(timezone.utc),
        )
