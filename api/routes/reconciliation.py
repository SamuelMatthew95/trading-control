"""
Reconciliation endpoints for system consistency validation.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_async_session
from api.observability import log_structured
from api.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.get("/validate")
async def validate_system_consistency(
    agent_id: str | None = Query(None, description="Filter by specific agent"),
    lookback_hours: int = Query(24, ge=1, le=168, description="Lookback period in hours"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Validate system consistency and detect issues.

    Returns detailed reconciliation results including:
    - Duplicate signal detection
    - Invalid lifecycle combinations
    - Orphaned SELL trades
    - Missing parent trades
    - Portfolio P&L recomputation
    """
    try:
        service = ReconciliationService(session)

        # Run full reconciliation
        result = await service.validate_ledger_consistency()

        # Format response
        response = {
            "success": result.status.value != "error",
            "data": {
                "status": result.status.value,
                "issues": [issue.value for issue in result.issues],
                "summary": result.summary,
                "details": result.details,
                "validation_timestamp": result.timestamp.isoformat(),
                "lookback_hours": lookback_hours,
                "agent_filter": agent_id,
            },
            "meta": {
                "source": "reconciliation_service",
                "validation_type": "full_consistency_check",
            },
        }

        log_structured(
            "info",
            "reconciliation_completed",
            status=result.status.value,
            issues_count=len(result.issues),
            agent_id=agent_id,
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "reconciliation_endpoint_error",
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Reconciliation validation failed")


@router.get("/pnl-recompute")
async def recompute_portfolio_pnl(
    agent_id: str | None = Query(None, description="Filter by specific agent"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Recompute portfolio P&L from ledger as source of truth.

    Returns accurate P&L calculations based on:
    - All closed trades in ledger
    - Proper entry/exit price matching
    - Correct quantity calculations
    """
    try:
        service = ReconciliationService(session)

        # Recalculate P&L from ledger
        pnl_data = await service.recompute_portfolio_pnl(agent_id)

        # Format response
        response = {
            "success": True,
            "data": {
                "total_pnl": float(pnl_data["total_pnl"]),
                "total_trades": pnl_data["total_trades"],
                "avg_pnl": float(pnl_data["avg_pnl"]),
                "win_rate": pnl_data["win_rate"],
                "source": "ledger_recomputation",
                "calculation_timestamp": datetime.now(timezone.utc).isoformat(),
                "agent_filter": agent_id,
            },
            "meta": {
                "source": "reconciliation_service",
                "calculation_type": "portfolio_pnl_recomputation",
            },
        }

        log_structured(
            "info",
            "pnl_recomputed",
            agent_id=agent_id,
            total_pnl=float(pnl_data["total_pnl"]),
            total_trades=pnl_data["total_trades"],
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "pnl_recomputation_error",
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="P&L recomputation failed")


@router.get("/health")
async def reconciliation_health(
    session: AsyncSession = Depends(get_async_session),
):
    """
    Health check for reconciliation service.

    Returns system consistency status and basic metrics.
    """
    try:
        service = ReconciliationService(session)

        # Quick consistency check
        result = await service.validate_ledger_consistency()

        # Get basic metrics
        from sqlalchemy import func, select

        from api.core.models.trade_ledger import TradeLedger

        total_trades_stmt = select(func.count(TradeLedger.trade_id))
        total_trades_result = await session.execute(total_trades_stmt)
        total_trades = total_trades_result.scalar() or 0

        open_positions_stmt = select(func.count(TradeLedger.trade_id)).where(
            TradeLedger.status == "OPEN"
        )
        open_positions_result = await session.execute(open_positions_stmt)
        open_positions = open_positions_result.scalar() or 0

        health_status = "healthy" if result.status.value == "consistent" else "unhealthy"

        response = {
            "success": True,
            "data": {
                "status": health_status,
                "consistency_check": result.status.value,
                "total_trades": total_trades,
                "open_positions": open_positions,
                "issues_found": len(result.issues),
                "last_check": result.timestamp.isoformat(),
            },
            "meta": {
                "source": "reconciliation_service",
                "check_type": "health",
            },
        }

        log_structured(
            "info",
            "reconciliation_health",
            status=health_status,
            total_trades=total_trades,
            open_positions=open_positions,
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "reconciliation_health_error",
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Health check failed")
