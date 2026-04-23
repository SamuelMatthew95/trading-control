"""
P&L recomputation endpoints for deterministic calculations.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

RECOMPUTATION:
- Always compute from entry_price → exit_price
- Never trust stored P&L as truth
- Mathematical guarantees for consistency
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_async_session
from api.observability import log_structured
from api.services.pnl_recomputation import PnLRecomputer

router = APIRouter(prefix="/api/pnl-recompute", tags=["pnl-recomputation"])


@router.get("/trade/{trade_id}")
async def recompute_trade_pnl(
    trade_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Recompute P&L for a specific trade from raw data.

    Returns deterministic P&L calculation:
    - entry_price → exit_price calculation
    - Never trusts stored P&L as truth
    - Mathematical guarantees for consistency
    """
    try:
        computer = PnLRecomputer(session)
        result = await computer.recompute_trade_pnl(trade_id)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        response = {
            "success": True,
            "data": result,
            "meta": {
                "source": "deterministic_recomputation",
                "calculation_type": "trade_pnl",
                "recomputation_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        log_structured(
            "info",
            "trade_pnl_recomputed",
            trade_id=trade_id,
            stored_pnl=result.get("stored_pnl"),
            recomputed_pnl=result.get("recomputed_pnl"),
            difference=result.get("pnl_difference"),
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "trade_pnl_recomputation_error",
            trade_id=trade_id,
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="P&L recomputation failed") from e


@router.get("/portfolio/{agent_id}")
async def recompute_portfolio_pnl(
    agent_id: str | None = Query(None, description="Agent ID filter"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Recompute entire portfolio P&L from raw trade data.

    Returns deterministic portfolio calculations:
    - All trade pairs reconstructed from entry/exit prices
    - Portfolio P&L calculated from scratch
    - Never trusts stored aggregates as truth
    """
    try:
        computer = PnLRecomputer(session)
        result = await computer.recompute_portfolio_pnl_strict(agent_id)

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        response = {
            "success": True,
            "data": result,
            "meta": {
                "source": "deterministic_recomputation",
                "calculation_type": "portfolio_pnl",
                "recomputation_timestamp": datetime.now(timezone.utc).isoformat(),
                "agent_filter": agent_id,
            },
        }

        log_structured(
            "info",
            "portfolio_pnl_recomputed",
            agent_id=agent_id,
            total_pnl=result.get("total_pnl"),
            total_trades=result.get("total_trades"),
            win_rate=result.get("win_rate"),
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "portfolio_pnl_recomputation_error",
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Portfolio P&L recomputation failed") from e


@router.get("/validate/consistency")
async def validate_pnl_consistency(
    agent_id: str | None = Query(None, description="Agent ID filter"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Validate P&L consistency across all trades.

    Checks for:
    - P&L calculation consistency
    - Trade pair integrity
    - Mathematical correctness verification
    """
    try:
        computer = PnLRecomputer(session)
        result = await computer.validate_pnl_consistency(agent_id)

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        response = {
            "success": True,
            "data": result,
            "meta": {
                "source": "deterministic_recomputation",
                "validation_type": "pnl_consistency",
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
                "agent_filter": agent_id,
            },
        }

        log_structured(
            "info",
            "pnl_consistency_validated",
            agent_id=agent_id,
            consistency_rate=result.get("consistency_rate"),
            inconsistent_trades=result.get("inconsistent_trades"),
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "pnl_consistency_validation_error",
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="P&L consistency validation failed") from e


@router.get("/health")
async def pnl_recomputation_health(
    session: AsyncSession = Depends(get_async_session),
):
    """
    Health check for P&L recomputation service.

    Returns service status and basic metrics.
    """
    try:
        from sqlalchemy import func, select

        from api.core.models.trade_ledger import TradeLedger

        # Get basic trade statistics
        total_trades_stmt = select(func.count(TradeLedger.trade_id))
        total_trades_result = await session.execute(total_trades_stmt)
        total_trades = total_trades_result.scalar() or 0

        pnl_trades_stmt = select(func.count(TradeLedger.trade_id)).where(
            TradeLedger.pnl_realized.isnot(None)
        )
        pnl_trades_result = await session.execute(pnl_trades_stmt)
        pnl_trades = pnl_trades_result.scalar() or 0

        response = {
            "success": True,
            "data": {
                "status": "healthy",
                "total_trades": total_trades,
                "trades_with_pnl": pnl_trades,
                "recomputation_available": True,
                "service_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "meta": {
                "source": "pnl_recomputation_service",
                "check_type": "health",
            },
        }

        log_structured(
            "info",
            "pnl_recomputation_health",
            total_trades=total_trades,
            trades_with_pnl=pnl_trades,
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "pnl_recomputation_health_error",
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Health check failed") from e
