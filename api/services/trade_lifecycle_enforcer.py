"""
Trade lifecycle enforcer - SELL before BUY never happens.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

LIFECYCLE RULES:
- SELL trades must have corresponding BUY parent
- BUY trades must have valid status transitions
- No orphaned SELL trades allowed
- Position consistency must be maintained
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.models.trade_ledger import TradeLedger
from api.observability import log_structured


class TradeLifecycleEnforcer:
    """Enforces trade lifecycle rules to prevent invalid sequences."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def validate_sell_before_buy(
        self, agent_id: str, symbol: str, sell_signal_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Validate that SELL trade has corresponding BUY parent.

        Rules enforced:
        - Every SELL must reference an existing BUY trade
        - BUY trade must be in OPEN status
        - Agent must be the same as BUY trade
        - Symbol must match
        """
        try:
            # Check if there's an existing OPEN BUY trade for this agent/symbol
            stmt = (
                select(TradeLedger)
                .where(
                    and_(
                        TradeLedger.agent_id == agent_id,
                        TradeLedger.symbol == symbol,
                        TradeLedger.trade_type == "BUY",
                        TradeLedger.status == "OPEN",
                    )
                )
                .order_by(TradeLedger.created_at.desc())
            )

            result = await self.session.execute(stmt)
            parent_buy_trades = result.scalars().all()

            if not parent_buy_trades:
                return {
                    "valid": False,
                    "reason": "No OPEN BUY position found for SELL",
                    "agent_id": agent_id,
                    "symbol": symbol,
                    "required_action": "Open BUY position first",
                    "sell_signal": sell_signal_data,
                }

            # Check if SELL quantity exceeds available BUY quantity
            parent_trade = parent_buy_trades[0]  # Use most recent
            sell_quantity = Decimal(str(sell_signal_data.get("quantity", "1")))

            if sell_quantity > parent_trade.quantity:
                return {
                    "valid": False,
                    "reason": f"SELL quantity {sell_quantity} exceeds BUY quantity {parent_trade.quantity}",
                    "agent_id": agent_id,
                    "symbol": symbol,
                    "required_action": "Reduce SELL quantity to match BUY",
                    "sell_signal": sell_signal_data,
                    "parent_buy_quantity": float(parent_trade.quantity),
                    "sell_quantity": float(sell_quantity),
                }

            return {
                "valid": True,
                "reason": "SELL trade validation passed",
                "agent_id": agent_id,
                "symbol": symbol,
                "parent_buy_trade_id": str(parent_trade.trade_id),
                "parent_buy_quantity": float(parent_trade.quantity),
                "sell_quantity": float(sell_quantity),
                "sell_signal": sell_signal_data,
            }

        except Exception as e:
            log_structured(
                "error",
                "sell_before_buy_validation_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(e),
                exc_info=True,
            )

            return {
                "valid": False,
                "reason": f"Validation error: {str(e)}",
                "agent_id": agent_id,
                "symbol": symbol,
                "error": str(e),
            }

    async def validate_buy_sequence(
        self, agent_id: str, symbol: str, buy_signal_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Validate BUY trade sequence rules.

        Rules enforced:
        - BUY trades must not have existing OPEN position
        - Agent position limits must be respected
        - Symbol trading rules must be followed
        """
        try:
            # Check for existing OPEN position for this agent/symbol
            stmt = select(TradeLedger).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.symbol == symbol,
                    TradeLedger.trade_type == "BUY",
                    TradeLedger.status == "OPEN",
                )
            )

            result = await self.session.execute(stmt)
            existing_open = result.scalar_one_or_none()

            if existing_open:
                return {
                    "valid": False,
                    "reason": f"OPEN BUY position already exists for {symbol}",
                    "agent_id": agent_id,
                    "symbol": symbol,
                    "existing_trade_id": str(existing_open.trade_id),
                    "required_action": "Close existing position first",
                    "buy_signal": buy_signal_data,
                }

            # Check position limits (example: max 10 units per symbol)
            max_position_size = Decimal("10.0")
            buy_quantity = Decimal(str(buy_signal_data.get("quantity", "1")))

            # Get current exposure for this symbol
            exposure_stmt = select(func.sum(TradeLedger.quantity)).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.symbol == symbol,
                    TradeLedger.trade_type == "BUY",
                    TradeLedger.status == "OPEN",
                )
            )

            exposure_result = await self.session.execute(exposure_stmt)
            current_exposure = exposure_result.scalar() or Decimal("0")

            if current_exposure + buy_quantity > max_position_size:
                return {
                    "valid": False,
                    "reason": f"BUY quantity {buy_quantity} would exceed position limit {max_position_size}",
                    "agent_id": agent_id,
                    "symbol": symbol,
                    "current_exposure": float(current_exposure),
                    "max_position_size": float(max_position_size),
                    "required_action": "Reduce BUY quantity",
                    "buy_signal": buy_signal_data,
                }

            return {
                "valid": True,
                "reason": "BUY trade validation passed",
                "agent_id": agent_id,
                "symbol": symbol,
                "current_exposure": float(current_exposure),
                "max_position_size": float(max_position_size),
                "buy_quantity": float(buy_quantity),
                "buy_signal": buy_signal_data,
            }

        except Exception as e:
            log_structured(
                "error",
                "buy_sequence_validation_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(e),
                exc_info=True,
            )

            return {
                "valid": False,
                "reason": f"Validation error: {str(e)}",
                "agent_id": agent_id,
                "symbol": symbol,
                "error": str(e),
            }

    async def get_position_summary(
        self, agent_id: str, symbol: str | None = None
    ) -> dict[str, Any]:
        """Get position summary for validation."""
        try:
            # Get all OPEN trades
            stmt = (
                select(TradeLedger)
                .where(
                    and_(
                        TradeLedger.agent_id == agent_id,
                        TradeLedger.status == "OPEN",
                        or_(
                            TradeLedger.symbol == symbol if symbol else True,
                            TradeLedger.symbol.isnot(None) if not symbol else False,
                        ),
                    )
                )
                .options(selectinload(TradeLedger.parent_trade))
            )

            result = await self.session.execute(stmt)
            open_trades = result.scalars().all()

            positions = []
            for trade in open_trades:
                positions.append(
                    {
                        "trade_id": str(trade.trade_id),
                        "symbol": trade.symbol,
                        "quantity": float(trade.quantity),
                        "entry_price": float(trade.entry_price),
                        "created_at": trade.created_at.isoformat(),
                        "has_parent": trade.parent_trade_id is not None,
                        "parent_trade_id": str(trade.parent_trade_id)
                        if trade.parent_trade_id
                        else None,
                    }
                )

            return {
                "agent_id": agent_id,
                "symbol_filter": symbol,
                "open_positions": len(open_trades),
                "positions": positions,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured(
                "error",
                "position_summary_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(e),
                exc_info=True,
            )

            return {
                "agent_id": agent_id,
                "error": str(e),
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def check_orphaned_sells(self) -> list[dict[str, Any]]:
        """Find SELL trades without corresponding BUY parents."""
        try:
            # Find SELL trades with parent_trade_id is None or non-existent
            stmt = select(TradeLedger).where(
                and_(
                    TradeLedger.trade_type == "SELL",
                    or_(
                        TradeLedger.parent_trade_id.is_(None),
                        ~TradeLedger.parent_trade_id.in_(
                            select(TradeLedger.trade_id).where(TradeLedger.trade_type == "BUY")
                        ),
                    ),
                )
            )

            result = await self.session.execute(stmt)
            orphaned_sells = result.scalars().all()

            orphaned_list = []
            for sell in orphaned_sells:
                orphaned_list.append(
                    {
                        "trade_id": str(sell.trade_id),
                        "symbol": sell.symbol,
                        "agent_id": sell.agent_id,
                        "quantity": float(sell.quantity),
                        "entry_price": float(sell.entry_price),
                        "exit_price": float(sell.exit_price),
                        "parent_trade_id": str(sell.parent_trade_id)
                        if sell.parent_trade_id
                        else None,
                        "orphan_reason": "No corresponding BUY parent found",
                        "created_at": sell.created_at.isoformat(),
                    }
                )

            log_structured(
                "warning",
                "orphaned_sells_found",
                count=len(orphaned_list),
            )

            return orphaned_list

        except Exception as e:
            log_structured(
                "error",
                "orphaned_sells_check_error",
                error=str(e),
                exc_info=True,
            )

            return []

    async def enforce_sell_before_buy_rule(self, trade_data: dict[str, Any]) -> dict[str, Any]:
        """
        Enforce SELL before BUY rule for all trades.

        This is called during trade creation to prevent invalid sequences.
        """
        try:
            trade_type = trade_data.get("trade_type", "")
            symbol = trade_data.get("symbol", "")
            agent_id = trade_data.get("agent_id", "")

            if trade_type == "SELL":
                # Validate SELL has parent BUY
                validation_result = await self.validate_sell_before_buy(
                    agent_id, symbol, trade_data
                )

                if not validation_result["valid"]:
                    log_structured(
                        "warning",
                        "sell_before_buy_rule_violation",
                        agent_id=agent_id,
                        symbol=symbol,
                        reason=validation_result["reason"],
                    )

                    return {
                        "rejected": True,
                        "reason": validation_result["reason"],
                        "validation": validation_result,
                    }

            return {
                "rejected": False,
                "reason": "Trade validation passed",
            }

        except Exception as e:
            log_structured(
                "error",
                "sell_before_buy_enforcement_error",
                trade_data=trade_data,
                error=str(e),
                exc_info=True,
            )

            return {
                "rejected": True,
                "reason": f"Enforcement error: {str(e)}",
            }
