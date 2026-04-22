"""
Trade Ledger Service - Core transaction architecture service.

This service manages the stateful ledger that pairs BUY and SELL signals
to calculate real P&L, replacing the logging-only architecture.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timezone

from sqlalchemy import select, update, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models.trade_ledger import TradeLedger
from api.core.models.strategy import Strategy
from api.observability import log_structured
from api.runtime_state import is_db_available


class TradeLedgerService:
    """Service for managing the trade ledger with BUY/SELL pairing logic."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_buy_trade(
        self,
        agent_id: str,
        strategy_id: uuid.UUID,
        symbol: str,
        quantity: Decimal,
        entry_price: Decimal,
        confidence_score: Optional[float] = None,
        execution_mode: str = "MOCK",
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeLedger:
        """Create a BUY trade that opens a position."""
        
        trade = TradeLedger(
            agent_id=agent_id,
            strategy_id=strategy_id,
            symbol=symbol,
            trade_type="BUY",
            quantity=quantity,
            entry_price=entry_price,
            confidence_score=Decimal(str(confidence_score)) if confidence_score else None,
            execution_mode=execution_mode,
            trace_id=trace_id,
            trade_metadata=metadata or {},
            source="trade_ledger_service",
        )

        self.session.add(trade)
        await self.session.flush()  # Get the trade_id
        
        log_structured(
            "info",
            "trade_ledger_buy_created",
            trade_id=str(trade.trade_id),
            agent_id=agent_id,
            symbol=symbol,
            quantity=float(quantity),
            entry_price=float(entry_price),
            execution_mode=execution_mode,
            trace_id=trace_id,
        )

        return trade

    async def create_sell_trade(
        self,
        agent_id: str,
        strategy_id: uuid.UUID,
        symbol: str,
        quantity: Decimal,
        exit_price: Decimal,
        confidence_score: Optional[float] = None,
        execution_mode: str = "MOCK",
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[TradeLedger, Optional[TradeLedger]]:
        """
        Create a SELL trade that closes a position.
        
        Returns:
            Tuple[SELL_TRADE, PARENT_BUY_TRADE or None]
            The parent BUY trade is returned if found and paired successfully.
        """
        
        # Find the latest OPEN BUY trade for this symbol and agent/strategy
        parent_buy = await self._find_open_buy_trade(
            agent_id=agent_id,
            strategy_id=strategy_id,
            symbol=symbol,
            quantity=quantity,
        )

        if not parent_buy:
            log_structured(
                "warning",
                "trade_ledger_sell_no_open_position",
                agent_id=agent_id,
                symbol=symbol,
                quantity=float(quantity),
                exit_price=float(exit_price),
                trace_id=trace_id,
            )
            # Create SELL trade without parent (will be marked as error)
            sell_trade = TradeLedger(
                agent_id=agent_id,
                strategy_id=strategy_id,
                symbol=symbol,
                trade_type="SELL",
                quantity=quantity,
                entry_price=exit_price,  # For SELL, entry_price is the exit price
                exit_price=exit_price,
                status="CANCELLED",  # Mark as error since no corresponding BUY
                confidence_score=Decimal(str(confidence_score)) if confidence_score else None,
                execution_mode=execution_mode,
                trace_id=trace_id,
                trade_metadata={**(metadata or {}), "error": "No open BUY position found"},
                source="trade_ledger_service",
            )
            self.session.add(sell_trade)
            await self.session.flush()
            return sell_trade, None

        # Calculate P&L
        pnl_realized = (exit_price - parent_buy.entry_price) * quantity

        # Create SELL trade
        sell_trade = TradeLedger(
            agent_id=agent_id,
            strategy_id=strategy_id,
            symbol=symbol,
            trade_type="SELL",
            quantity=quantity,
            entry_price=parent_buy.entry_price,  # Inherit entry price from parent BUY
            exit_price=exit_price,
            pnl_realized=pnl_realized,
            status="CLOSED",
            parent_trade_id=parent_buy.trade_id,
            confidence_score=Decimal(str(confidence_score)) if confidence_score else None,
            execution_mode=execution_mode,
            trace_id=trace_id,
            trade_metadata=metadata or {},
            source="trade_ledger_service",
            closed_at=datetime.now(timezone.utc),
        )

        self.session.add(sell_trade)

        # Update parent BUY trade to CLOSED
        parent_buy.status = "CLOSED"
        parent_buy.closed_at = datetime.now(timezone.utc)

        await self.session.flush()

        log_structured(
            "info",
            "trade_ledger_sell_created_and_paired",
            sell_trade_id=str(sell_trade.trade_id),
            parent_buy_id=str(parent_buy.trade_id),
            agent_id=agent_id,
            symbol=symbol,
            quantity=float(quantity),
            entry_price=float(parent_buy.entry_price),
            exit_price=float(exit_price),
            pnl_realized=float(pnl_realized),
            execution_mode=execution_mode,
            trace_id=trace_id,
        )

        return sell_trade, parent_buy

    async def _find_open_buy_trade(
        self,
        agent_id: str,
        strategy_id: uuid.UUID,
        symbol: str,
        quantity: Decimal,
    ) -> Optional[TradeLedger]:
        """Find the latest OPEN BUY trade for the given criteria."""
        
        stmt = (
            select(TradeLedger)
            .where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.strategy_id == strategy_id,
                    TradeLedger.symbol == symbol,
                    TradeLedger.trade_type == "BUY",
                    TradeLedger.status == "OPEN",
                    TradeLedger.quantity >= quantity,  # Ensure enough quantity
                )
            )
            .order_by(desc(TradeLedger.created_at))
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_open_positions(
        self,
        agent_id: Optional[str] = None,
        strategy_id: Optional[uuid.UUID] = None,
    ) -> List[TradeLedger]:
        """Get all open positions (BUY trades that haven't been closed)."""
        
        stmt = select(TradeLedger).where(
            and_(
                TradeLedger.trade_type == "BUY",
                TradeLedger.status == "OPEN",
            )
        )

        if agent_id:
            stmt = stmt.where(TradeLedger.agent_id == agent_id)
        if strategy_id:
            stmt = stmt.where(TradeLedger.strategy_id == strategy_id)

        stmt = stmt.order_by(desc(TradeLedger.created_at))

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_recent_trades(
        self,
        limit: int = 50,
        agent_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[TradeLedger]:
        """Get recent trades for the dashboard feed."""
        
        stmt = select(TradeLedger).order_by(desc(TradeLedger.created_at)).limit(limit)

        if agent_id:
            stmt = stmt.where(TradeLedger.agent_id == agent_id)
        if symbol:
            stmt = stmt.where(TradeLedger.symbol == symbol)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def calculate_agent_performance(
        self,
        agent_id: str,
        lookback_days: int = 30,
    ) -> Dict[str, Any]:
        """Calculate agent performance metrics for grading."""
        
        from datetime import timedelta
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        # Get all closed trades for this agent in the lookback period
        stmt = (
            select(
                func.count(TradeLedger.trade_id).label("total_trades"),
                func.sum(
                    func.case(
                        (TradeLedger.pnl_realized > 0, 1),
                        else_=0,
                    )
                ).label("winning_trades"),
                func.sum(TradeLedger.pnl_realized).label("total_pnl"),
                func.avg(TradeLedger.pnl_realized).label("avg_pnl"),
            )
            .where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.status == "CLOSED",
                    TradeLedger.created_at >= cutoff_date,
                )
            )
        )

        result = await self.session.execute(stmt)
        row = result.first()

        total_trades = row.total_trades or 0
        winning_trades = row.winning_trades or 0
        total_pnl = row.total_pnl or Decimal("0")
        avg_pnl = row.avg_pnl or Decimal("0")

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        return {
            "agent_id": agent_id,
            "lookback_days": lookback_days,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": float(win_rate),
            "total_pnl": float(total_pnl),
            "avg_pnl": float(avg_pnl),
            "grade": self._calculate_agent_grade(win_rate, total_pnl, total_trades),
        }

    def _calculate_agent_grade(
        self,
        win_rate: float,
        total_pnl: Decimal,
        total_trades: int,
    ) -> str:
        """Calculate agent grade based on performance metrics."""
        
        if total_trades < 5:
            return "INSUFFICIENT_DATA"

        if win_rate >= 60 and total_pnl > 0:
            return "A"
        elif win_rate >= 50 and total_pnl > 0:
            return "B"
        elif win_rate >= 40:
            return "C"
        else:
            return "D"

    async def get_portfolio_summary(
        self,
        agent_id: Optional[str] = None,
        strategy_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Get portfolio summary for dashboard stats."""
        
        # Get open positions count
        open_positions_stmt = (
            select(func.count(TradeLedger.trade_id))
            .where(
                and_(
                    TradeLedger.trade_type == "BUY",
                    TradeLedger.status == "OPEN",
                )
            )
        )
        if agent_id:
            open_positions_stmt = open_positions_stmt.where(TradeLedger.agent_id == agent_id)
        if strategy_id:
            open_positions_stmt = open_positions_stmt.where(TradeLedger.strategy_id == strategy_id)

        open_positions_result = await self.session.execute(open_positions_stmt)
        open_positions = open_positions_result.scalar() or 0

        # Get today's P&L
        from datetime import date
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

        daily_pnl_stmt = (
            select(func.sum(TradeLedger.pnl_realized))
            .where(
                and_(
                    TradeLedger.status == "CLOSED",
                    TradeLedger.closed_at >= today_start,
                )
            )
        )
        if agent_id:
            daily_pnl_stmt = daily_pnl_stmt.where(TradeLedger.agent_id == agent_id)
        if strategy_id:
            daily_pnl_stmt = daily_pnl_stmt.where(TradeLedger.strategy_id == strategy_id)

        daily_pnl_result = await self.session.execute(daily_pnl_stmt)
        daily_pnl = daily_pnl_result.scalar() or Decimal("0")

        # Get total P&L
        total_pnl_stmt = (
            select(func.sum(TradeLedger.pnl_realized))
            .where(TradeLedger.status == "CLOSED")
        )
        if agent_id:
            total_pnl_stmt = total_pnl_stmt.where(TradeLedger.agent_id == agent_id)
        if strategy_id:
            total_pnl_stmt = total_pnl_stmt.where(TradeLedger.strategy_id == strategy_id)

        total_pnl_result = await self.session.execute(total_pnl_stmt)
        total_pnl = total_pnl_result.scalar() or Decimal("0")

        # Calculate win rate
        win_rate_stmt = (
            select(
                func.count(TradeLedger.trade_id).label("total"),
                func.sum(
                    func.case(
                        (TradeLedger.pnl_realized > 0, 1),
                        else_=0,
                    )
                ).label("wins"),
            )
            .where(TradeLedger.status == "CLOSED")
        )
        if agent_id:
            win_rate_stmt = win_rate_stmt.where(TradeLedger.agent_id == agent_id)
        if strategy_id:
            win_rate_stmt = win_rate_stmt.where(TradeLedger.strategy_id == strategy_id)

        win_rate_result = await self.session.execute(win_rate_stmt)
        win_rate_row = win_rate_result.first()
        
        total_trades = win_rate_row.total or 0
        wins = win_rate_row.wins or 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        return {
            "open_positions": open_positions,
            "daily_pnl": float(daily_pnl),
            "total_pnl": float(total_pnl),
            "win_rate": float(win_rate),
            "total_trades": total_trades,
        }


# Factory function for dependency injection
async def get_trade_ledger_service(session: AsyncSession) -> TradeLedgerService:
    """Factory function to create TradeLedgerService instance."""
    return TradeLedgerService(session)
