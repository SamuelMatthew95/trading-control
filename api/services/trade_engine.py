"""
Trade Engine - Core logic for trade execution and position management.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func

from api.core.events import SignalAction, SignalEvent, TradeExecutionEvent
from api.core.models.trade_ledger import TradeLedger


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
            entry_price=signal.price,
            quantity=Decimal("1.0"),  # TODO: Get from signal metadata
            execution_mode="MOCK",
            timestamp=datetime.now(timezone.utc),
        )

        if signal.action == SignalAction.BUY:
            return await self._handle_buy_signal(signal, execution)
        if signal.action == SignalAction.SELL:
            return await self._handle_sell_signal(signal, execution)
        # HOLD or other - no action
        execution.status = "IGNORED"
        return execution

    async def _handle_buy_signal(
        self, signal: SignalEvent, execution: TradeExecutionEvent
    ) -> TradeExecutionEvent:
        """Handle BUY signal - open new position."""
        # Create BUY trade
        trade = TradeLedger(
            agent_id=signal.agent_id,
            strategy_id=uuid.uuid4(),  # TODO: Get from signal metadata
            symbol=signal.symbol,
            trade_type="BUY",
            quantity=Decimal("1.0"),  # TODO: Get from signal metadata
            entry_price=signal.price,
            confidence_score=Decimal(str(signal.confidence or "0")),
            execution_mode="MOCK",
            trace_id=signal.signal_id,
            trade_metadata={"source": "signal"},
            source="trade_engine",
        )

        self.session.add(trade)
        await self.session.flush()

        # Update execution with trade details
        execution.entry_price = signal.price
        execution.quantity = Decimal("1.0")
        execution.status = "OPEN"

        return execution

    async def _handle_sell_signal(
        self, signal: SignalEvent, execution: TradeExecutionEvent
    ) -> TradeExecutionEvent:
        """Handle SELL signal - close most recent OPEN position."""
        # Find most recent OPEN BUY trade for this symbol
        from sqlalchemy import and_, select

        from api.core.models.trade_ledger import TradeLedger

        stmt = (
            select(TradeLedger)
            .where(
                and_(
                    TradeLedger.symbol == signal.symbol,
                    TradeLedger.trade_type == "BUY",
                    TradeLedger.status == "OPEN",
                )
            )
            .order_by(TradeLedger.created_at.desc())
        )

        result = await self.session.execute(stmt)
        parent_trade = result.scalar_one_or_none()

        if not parent_trade:
            # No open position to close
            execution.status = "REJECTED"
            execution.pnl_realized = Decimal("0")
            return execution

        # Calculate P&L
        pnl = (signal.price - parent_trade.entry_price) * parent_trade.quantity

        # Create SELL trade
        sell_trade = TradeLedger(
            agent_id=signal.agent_id,
            strategy_id=parent_trade.strategy_id,
            symbol=signal.symbol,
            trade_type="SELL",
            quantity=parent_trade.quantity,
            entry_price=parent_trade.entry_price,
            exit_price=signal.price,
            pnl_realized=pnl,
            status="CLOSED",
            confidence_score=Decimal(str(signal.confidence or "0")),
            execution_mode="MOCK",
            trace_id=signal.signal_id,
            parent_trade_id=parent_trade.trade_id,
            trade_metadata={"source": "signal"},
            source="trade_engine",
        )

        # Close parent trade
        parent_trade.status = "CLOSED"
        parent_trade.pnl_realized = pnl

        self.session.add(sell_trade)
        await self.session.flush()

        # Update execution with trade details
        execution.entry_price = parent_trade.entry_price
        execution.exit_price = signal.price
        execution.quantity = parent_trade.quantity
        execution.pnl_realized = pnl
        execution.status = "CLOSED"

        return execution

    async def get_open_positions(self, agent_id: str | None = None) -> list[TradeLedger]:
        """Get current open positions."""
        from sqlalchemy import select

        from api.core.models.trade_ledger import TradeLedger

        stmt = select(TradeLedger).where(TradeLedger.status == "OPEN")

        if agent_id:
            stmt = stmt.where(TradeLedger.agent_id == agent_id)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_portfolio_summary(self) -> dict:
        """Get portfolio summary statistics."""
        from sqlalchemy import select

        from api.core.models.trade_ledger import TradeLedger

        # Total P&L from closed trades
        pnl_stmt = select(func.coalesce(func.sum(TradeLedger.pnl_realized), 0)).where(
            TradeLedger.status == "CLOSED"
        )
        pnl_result = await self.session.execute(pnl_stmt)
        total_pnl = pnl_result.scalar()

        # Open positions count
        open_stmt = select(func.count(TradeLedger.trade_id)).where(TradeLedger.status == "OPEN")
        open_result = await self.session.execute(open_stmt)
        open_positions = open_result.scalar()

        # Daily P&L (simplified - today only)
        today = datetime.now(timezone.utc).date()
        daily_stmt = select(func.coalesce(func.sum(TradeLedger.pnl_realized), 0)).where(
            and_(TradeLedger.status == "CLOSED", func.date(TradeLedger.created_at) == today)
        )
        daily_result = await self.session.execute(daily_stmt)
        daily_pnl = daily_result.scalar()

        # Win rate
        winning_stmt = select(func.count(TradeLedger.trade_id)).where(
            and_(TradeLedger.status == "CLOSED", TradeLedger.pnl_realized > 0)
        )
        losing_stmt = select(func.count(TradeLedger.trade_id)).where(
            and_(TradeLedger.status == "CLOSED", TradeLedger.pnl_realized < 0)
        )

        winning_result = await self.session.execute(winning_stmt)
        losing_result = await self.session.execute(losing_stmt)
        winning_trades = winning_result.scalar()
        losing_trades = losing_result.scalar()
        total_trades = winning_trades + losing_trades

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        return {
            "total_pnl": total_pnl or Decimal("0"),
            "daily_pnl": daily_pnl or Decimal("0"),
            "open_positions": open_positions or 0,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "winning_trades": winning_trades or 0,
            "losing_trades": losing_trades or 0,
        }
