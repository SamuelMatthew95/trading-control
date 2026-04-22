"""
Trade validation service with strict enforcement.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

VALIDATION:
- Every trade must have required identifiers
- Trade relationships must be valid
- Financial data must be consistent
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models.trade_ledger import TradeLedger
from api.core.trade_validation import StrictTradeValidator
from api.observability import log_structured


class TradeValidationService:
    """Strict trade validation enforcement."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.validator = StrictTradeValidator()

    async def validate_trade_creation(self, trade_data: dict[str, Any]) -> dict[str, Any]:
        """Validate trade creation with strict requirements."""
        try:
            # Step 1: Validate all required fields
            self.validator.validate_trade_fields(trade_data)

            # Step 2: Validate financial data
            self.validator.validate_financial_data(trade_data)

            # Step 3: Validate trade lifecycle
            self.validator.validate_trade_lifecycle(trade_data)

            # Step 4: Enforce required identifiers
            self.validator.enforce_required_identifiers(trade_data)

            # Step 5: Check for duplicates
            await self._check_for_duplicates(trade_data)

            return {
                "success": True,
                "trade_data": trade_data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                "validation_summary": self.validator.get_validation_summary(),
            }

        except Exception as e:
            log_structured(
                "error",
                "trade_validation_error",
                trade_id=trade_data.get("trade_id", "unknown"),
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "error": str(e),
                "trade_data": trade_data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def _check_for_duplicates(self, trade_data: dict[str, Any]) -> None:
        """Check for duplicate trades before creation."""
        signal_id = trade_data.get("signal_id")
        agent_id = trade_data.get("agent_id")
        symbol = trade_data.get("symbol")

        if not all([signal_id, agent_id, symbol]):
            return

        # Check for existing signal_id
        stmt = select(TradeLedger).where(
            and_(
                TradeLedger.trace_id == signal_id,
                TradeLedger.agent_id == agent_id,
            )
        )

        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            error_msg = f"Duplicate trade detected: signal_id={signal_id}, agent_id={agent_id}, symbol={symbol}"
            self.validator.validation_errors.append(error_msg)
            raise ValueError(error_msg)

    async def validate_trade_update(self, trade_id: str, update_data: dict[str, Any]) -> dict[str, Any]:
        """Validate trade update with strict requirements."""
        try:
            # Get existing trade
            stmt = select(TradeLedger).where(TradeLedger.trade_id == trade_id)
            result = await self.session.execute(stmt)
            existing_trade = result.scalar_one_or_none()

            if not existing_trade:
                raise ValueError(f"Trade not found: {trade_id}")

            # Merge with existing data
            merged_data = {**existing_trade.__dict__, **update_data}

            # Validate merged data
            self.validator.validate_trade_fields(merged_data)
            self.validator.validate_financial_data(merged_data)
            self.validator.validate_trade_lifecycle(merged_data)

            return {
                "success": True,
                "trade_id": trade_id,
                "update_data": update_data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                "validation_summary": self.validator.get_validation_summary(),
            }

        except Exception as e:
            log_structured(
                "error",
                "trade_update_validation_error",
                trade_id=trade_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "error": str(e),
                "trade_id": trade_id,
                "update_data": update_data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def validate_trade_relationships(self, trade_id: str) -> dict[str, Any]:
        """Validate trade relationships are valid."""
        try:
            # Get trade and related trades
            stmt = select(TradeLedger).where(
                or_(
                    TradeLedger.trade_id == trade_id,
                    TradeLedger.parent_trade_id == trade_id,
                )
            )

            result = await self.session.execute(stmt)
            trades = result.scalars().all()

            if not trades:
                raise ValueError(f"No trades found for relationship validation: {trade_id}")

            # Validate relationships
            for trade in trades:
                if trade.parent_trade_id:
                    # This is a child trade - validate parent exists
                    parent_stmt = select(TradeLedger).where(
                        TradeLedger.trade_id == trade.parent_trade_id
                    )
                    parent_result = await self.session.execute(parent_stmt)
                    parent_trade = parent_result.scalar_one_or_none()

                    if not parent_trade:
                        error_msg = f"Orphaned trade detected: {trade.trade_id} references non-existent parent {trade.parent_trade_id}"
                        self.validator.validation_errors.append(error_msg)
                        raise ValueError(error_msg)

            return {
                "success": True,
                "trade_id": trade_id,
                "related_trades": len(trades),
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                "validation_summary": self.validator.get_validation_summary(),
            }

        except Exception as e:
            log_structured(
                "error",
                "trade_relationship_validation_error",
                trade_id=trade_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "error": str(e),
                "trade_id": trade_id,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def enforce_trade_consistency(self, agent_id: str, symbol: str) -> dict[str, Any]:
        """Enforce trade consistency for agent/symbol combination."""
        try:
            # Check for conflicting positions
            stmt = select(TradeLedger).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.symbol == symbol,
                    TradeLedger.status == "OPEN",
                )
            )

            result = await self.session.execute(stmt)
            open_positions = result.scalars().all()

            if len(open_positions) > 1:
                error_msg = f"Multiple open positions detected: {len(open_positions)} open trades for {symbol}"
                self.validator.validation_errors.append(error_msg)
                raise ValueError(error_msg)

            return {
                "success": True,
                "agent_id": agent_id,
                "symbol": symbol,
                "open_positions": len(open_positions),
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                "validation_summary": self.validator.get_validation_summary(),
            }

        except Exception as e:
            log_structured(
                "error",
                "trade_consistency_enforcement_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "error": str(e),
                "agent_id": agent_id,
                "symbol": symbol,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def get_validation_summary(self, agent_id: str | None = None) -> dict[str, Any]:
        """Get validation summary for monitoring."""
        try:
            total_trades_stmt = select(func.count(TradeLedger.trade_id))

            if agent_id:
                total_trades_stmt = total_trades_stmt.where(TradeLedger.agent_id == agent_id)

            result = await self.session.execute(total_trades_stmt)
            total_trades = result.scalar() or 0

            return {
                "agent_id": agent_id,
                "total_trades": total_trades,
                "validation_errors": len(self.validator.validation_errors),
                "errors": self.validator.validation_errors,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                "service_status": "active",
            }

        except Exception as e:
            log_structured(
                "error",
                "validation_summary_error",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "agent_id": agent_id,
                "total_trades": 0,
                "validation_errors": 1,
                "errors": [str(e)],
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                "service_status": "error",
            }
