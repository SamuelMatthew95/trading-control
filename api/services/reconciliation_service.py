"""
Reconciliation service to validate system consistency.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

VALIDATION:
- Ledger consistency checks
- P&L recomputation from source of truth
- System-wide consistency validation
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import and_, func, select

from api.observability import log_structured


class ReconciliationStatus(Enum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    ERROR = "error"


class ReconciliationIssue(Enum):
    DUPLICATE_TRADES = "duplicate_trades"
    INVALID_LIFECYCLE = "invalid_lifecycle"
    PNL_MISMATCH = "pnl_mismatch"
    ORPHANED_TRADES = "orphaned_trades"
    MISSING_PARENT = "missing_parent"


@dataclass
class ReconciliationResult:
    """Result of reconciliation validation."""
    status: ReconciliationStatus
    issues: list[ReconciliationIssue]
    summary: dict[str, Any]
    details: dict[str, Any]
    timestamp: datetime = None


class ReconciliationService:
    """System consistency validation and P&L recomputation."""

    def __init__(self, session):
        self.session = session

    async def validate_ledger_consistency(self) -> ReconciliationResult:
        """Validate trade ledger for consistency issues."""
        issues = []
        summary = {}

        try:
            # Check 1: Duplicate signal_id validation
            duplicate_signals = await self._check_duplicate_signal_ids()
            if duplicate_signals:
                issues.append(ReconciliationIssue.DUPLICATE_TRADES)
                summary["duplicate_signals"] = len(duplicate_signals)

            # Check 2: Invalid lifecycle combinations
            invalid_lifecycle = await self._check_invalid_lifecycle()
            if invalid_lifecycle:
                issues.append(ReconciliationIssue.INVALID_LIFECYCLE)
                summary["invalid_lifecycle"] = len(invalid_lifecycle)

            # Check 3: Orphaned SELL trades
            orphaned_sells = await self._check_orphaned_sells()
            if orphaned_sells:
                issues.append(ReconciliationIssue.ORPHANED_TRADES)
                summary["orphaned_sells"] = len(orphaned_sells)

            # Check 4: Missing parent trades
            missing_parents = await self._check_missing_parents()
            if missing_parents:
                issues.append(ReconciliationIssue.MISSING_PARENT)
                summary["missing_parents"] = len(missing_parents)

            status = ReconciliationStatus.INCONSISTENT if issues else ReconciliationStatus.CONSISTENT

            result = ReconciliationResult(
                status=status,
                issues=issues,
                summary=summary,
                details={
                    "total_trades": await self._get_total_trade_count(),
                    "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                },
                timestamp=datetime.now(timezone.utc),
            )

            log_structured(
                "info",
                "reconciliation_completed",
                status=status.value,
                issues_count=len(issues),
                summary=summary,
            )

            return result

        except Exception as e:
            log_structured(
                "error",
                "reconciliation_error",
                error=str(e),
                exc_info=True,
            )

            return ReconciliationResult(
                status=ReconciliationStatus.ERROR,
                issues=[],
                summary={"error": str(e)},
                details={},
                timestamp=datetime.now(timezone.utc),
            )

    async def recompute_portfolio_pnl(self, agent_id: str | None = None) -> dict[str, Any]:
        """Recompute portfolio P&L from ledger as source of truth."""
        try:
            # Get all closed trades for P&L calculation
            from api.core.models.trade_ledger import TradeLedger

            stmt = select(
                func.sum(TradeLedger.pnl_realized),
                func.count(TradeLedger.trade_id),
                func.avg(TradeLedger.pnl_realized),
            ).where(
                and_(
                    TradeLedger.status == "CLOSED",
                    TradeLedger.pnl_realized.isnot(None),
                )
            )

            if agent_id:
                stmt = stmt.where(TradeLedger.agent_id == agent_id)

            result = await self.session.execute(stmt)
            pnl_data = result.first()

            if not pnl_data or pnl_data[0] is None:
                return {
                    "total_pnl": Decimal("0"),
                    "total_trades": 0,
                    "avg_pnl": Decimal("0"),
                    "win_rate": 0.0,
                }

            total_pnl = pnl_data[0] or Decimal("0")
            total_trades = pnl_data[1] or 0
            avg_pnl = pnl_data[2] or Decimal("0")

            # Calculate win rate
            winning_stmt = select(func.count(TradeLedger.trade_id)).where(
                and_(
                    TradeLedger.status == "CLOSED",
                    TradeLedger.pnl_realized > 0,
                )
            )

            if agent_id:
                winning_stmt = winning_stmt.where(TradeLedger.agent_id == agent_id)

            winning_result = await self.session.execute(winning_stmt)
            winning_trades = winning_result.scalar() or 0

            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

            log_structured(
                "info",
                "pnl_recomputed",
                agent_id=agent_id,
                total_pnl=float(total_pnl),
                total_trades=total_trades,
                win_rate=win_rate,
            )

            return {
                "total_pnl": total_pnl,
                "total_trades": total_trades,
                "avg_pnl": avg_pnl,
                "win_rate": win_rate,
                "source": "ledger_recomputation",
            }

        except Exception as e:
            log_structured(
                "error",
                "pnl_recomputation_error",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "total_pnl": Decimal("0"),
                "total_trades": 0,
                "avg_pnl": Decimal("0"),
                "win_rate": 0.0,
                "source": "error",
            }

    async def _check_duplicate_signal_ids(self) -> list[dict[str, Any]]:
        """Check for duplicate signal_id values."""
        from api.core.models.trade_ledger import TradeLedger

        # Find signal_ids that appear more than once
        stmt = select(
            TradeLedger.trace_id,
            func.count(TradeLedger.trade_id).label('count')
        ).group_by(TradeLedger.trace_id).having(
            func.count(TradeLedger.trade_id) > 1
        )

        result = await self.session.execute(stmt)
        duplicates = []

        for row in result:
            duplicates.append({
                "signal_id": row.trace_id,
                "count": row.count,
            })

        return duplicates

    async def _check_invalid_lifecycle(self) -> list[dict[str, Any]]:
        """Check for invalid trade lifecycle combinations."""
        from api.core.models.trade_ledger import TradeLedger

        # Find trades with invalid status/type combinations
        stmt = select(TradeLedger).where(
            and_(
                TradeLedger.trade_type == "BUY",
                TradeLedger.status == "CLOSED",
                TradeLedger.pnl_realized.isnot(None),
                TradeLedger.parent_trade_id.isnot(None),
            )
        )

        result = await self.session.execute(stmt)
        invalid_trades = []

        for trade in result.scalars():
            invalid_trades.append({
                "trade_id": str(trade.trade_id),
                "trade_type": trade.trade_type,
                "status": trade.status,
                "issue": "BUY trade should not have parent and be closed with P&L",
            })

        return invalid_trades

    async def _check_orphaned_sells(self) -> list[dict[str, Any]]:
        """Check for SELL trades without corresponding BUY parent."""
        from api.core.models.trade_ledger import TradeLedger

        stmt = select(TradeLedger).where(
            and_(
                TradeLedger.trade_type == "SELL",
                TradeLedger.parent_trade_id.is_(None),
            )
        )

        result = await self.session.execute(stmt)
        orphaned_trades = []

        for trade in result.scalars():
            orphaned_trades.append({
                "trade_id": str(trade.trade_id),
                "symbol": trade.symbol,
                "issue": "SELL trade without parent BUY trade",
            })

        return orphaned_trades

    async def _check_missing_parents(self) -> list[dict[str, Any]]:
        """Check for trades referencing non-existent parents."""
        from api.core.models.trade_ledger import TradeLedger

        stmt = select(TradeLedger).where(
            and_(
                TradeLedger.parent_trade_id.isnot(None),
                ~TradeLedger.parent_trade_id.in_(
                    select(TradeLedger.trade_id).where(TradeLedger.trade_type == "BUY")
                ),
            )
        )

        result = await self.session.execute(stmt)
        missing_parents = []

        for trade in result.scalars():
            missing_parents.append({
                "trade_id": str(trade.trade_id),
                "parent_trade_id": str(trade.parent_trade_id),
                "issue": "References non-existent parent trade",
            })

        return missing_parents

    async def _get_total_trade_count(self) -> int:
        """Get total number of trades in ledger."""
        from api.core.models.trade_ledger import TradeLedger

        stmt = select(func.count(TradeLedger.trade_id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0
