"""
DB-only memory model for agents - prevents hallucinations and inconsistent state.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

MEMORY DISCIPLINE:
- Agents NEVER rely on memory or context
- Agents ALWAYS query DB for current state
- Agents NEVER hallucinate positions or trades
- Agents ONLY operate on verified DB data
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from api.observability import log_structured
from api.core.models.trade_ledger import TradeLedger


class AgentMemoryDiscipline:
    """Enforces DB-only memory model for agents."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_current_positions(self, agent_id: str) -> Dict[str, Any]:
        """Get agent's current positions from DB only."""
        try:
            stmt = select(TradeLedger).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.status == "OPEN"
                )
            ).order_by(TradeLedger.created_at.desc())
            
            result = await self.session.execute(stmt)
            positions = result.scalars().all()
            
            position_data = {}
            for position in positions:
                position_data[position.symbol] = {
                    "quantity": float(position.quantity),
                    "entry_price": float(position.entry_price),
                    "created_at": position.created_at.isoformat(),
                }
            
            log_structured(
                "info",
                "agent_memory_db_query",
                agent_id=agent_id,
                positions_count=len(positions),
                source="database_only",
            )
            
            return {
                "positions": position_data,
                "source": "database_only",
                "query_timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
        except Exception as e:
            log_structured(
                "error",
                "agent_memory_query_error",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )
            
            return {
                "positions": {},
                "source": "database_only",
                "error": str(e),
            }
    
    async def get_trade_history(self, agent_id: str, limit: int = 50) -> Dict[str, Any]:
        """Get agent's trade history from DB only."""
        try:
            stmt = select(TradeLedger).where(
                TradeLedger.agent_id == agent_id
            ).order_by(TradeLedger.created_at.desc()).limit(limit)
            
            result = await self.session.execute(stmt)
            trades = result.scalars().all()
            
            trade_data = []
            for trade in trades:
                trade_data.append({
                    "trade_id": str(trade.trade_id),
                    "symbol": trade.symbol,
                    "action": trade.trade_type,
                    "quantity": float(trade.quantity),
                    "entry_price": float(trade.entry_price) if trade.entry_price else None,
                    "exit_price": float(trade.exit_price) if trade.exit_price else None,
                    "pnl_realized": float(trade.pnl_realized) if trade.pnl_realized else None,
                    "status": trade.status,
                    "created_at": trade.created_at.isoformat(),
                })
            
            log_structured(
                "info",
                "agent_memory_history_query",
                agent_id=agent_id,
                trades_count=len(trade_data),
                source="database_only",
            )
            
            return {
                "trades": trade_data,
                "source": "database_only",
                "query_timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
        except Exception as e:
            log_structured(
                "error",
                "agent_memory_history_error",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )
            
            return {
                "trades": [],
                "source": "database_only",
                "error": str(e),
            }
    
    async def get_exposure_summary(self, agent_id: str) -> Dict[str, Any]:
        """Get agent's current exposure from DB only."""
        try:
            # Calculate current exposure
            stmt = select(
                func.sum(TradeLedger.quantity),
                func.sum(TradeLedger.pnl_realized),
                func.count(TradeLedger.trade_id)
            ).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.status == "OPEN"
                )
            )
            
            result = await self.session.execute(stmt)
            exposure_data = result.first()
            
            if not exposure_data:
                return {
                    "total_exposure": 0.0,
                    "unrealized_pnl": 0.0,
                    "open_positions": 0,
                    "source": "database_only",
                }
            
            total_exposure = float(exposure_data[0] or 0)
            unrealized_pnl = float(exposure_data[1] or 0)
            open_positions = int(exposure_data[2] or 0)
            
            log_structured(
                "info",
                "agent_memory_exposure_query",
                agent_id=agent_id,
                total_exposure=total_exposure,
                unrealized_pnl=unrealized_pnl,
                open_positions=open_positions,
                source="database_only",
            )
            
            return {
                "total_exposure": total_exposure,
                "unrealized_pnl": unrealized_pnl,
                "open_positions": open_positions,
                "source": "database_only",
            }
            
        except Exception as e:
            log_structured(
                "error",
                "agent_memory_exposure_error",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )
            
            return {
                "total_exposure": 0.0,
                "unrealized_pnl": 0.0,
                "open_positions": 0,
                "source": "database_only",
                "error": str(e),
            }
    
    async def validate_signal_id_processed(self, agent_id: str, signal_id: str) -> bool:
        """Check if signal_id was already processed by this agent."""
        try:
            stmt = select(TradeLedger).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.trace_id == signal_id
                )
            )
            
            result = await self.session.execute(stmt)
            existing_trade = result.scalar_one_or_none()
            
            if existing_trade:
                log_structured(
                    "info",
                    "agent_memory_duplicate_check",
                    agent_id=agent_id,
                    signal_id=signal_id,
                    existing_trade_id=str(existing_trade.trade_id),
                    source="database_only",
                )
                return True
            
            return False
            
        except Exception as e:
            log_structured(
                "error",
                "agent_memory_duplicate_check_error",
                agent_id=agent_id,
                signal_id=signal_id,
                error=str(e),
                exc_info=True,
            )
            
            # On error, assume not processed to be safe
            return False
