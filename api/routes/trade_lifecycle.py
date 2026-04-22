"""
Trade lifecycle enforcement endpoints.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

LIFECYCLE ENFORCEMENT:
- SELL trades must have corresponding BUY parent
- BUY trades must not have existing OPEN position
- Position consistency must be maintained
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_async_session
from api.observability import log_structured
from api.services.trade_lifecycle_enforcer import TradeLifecycleEnforcer


router = APIRouter(prefix="/api/trades/lifecycle", tags=["trade-lifecycle"])


@router.post("/enforce/sell-before-buy")
async def enforce_sell_before_buy(
    trade_data: Dict[str, Any],
    session: AsyncSession = Depends(get_async_session),
):
    """
    Enforce SELL before BUY rule for all trades.
    
    Prevents invalid trade sequences:
    - No orphaned SELL trades
    - Proper parent/child relationships
    - Position consistency maintained
    """
    try:
        enforcer = TradeLifecycleEnforcer(session)
        result = await enforcer.enforce_sell_before_buy_rule(trade_data)
        
        if result["rejected"]:
            raise HTTPException(status_code=400, detail=result["reason"])
        
        response = {
            "success": True,
            "data": {
                "trade_id": result.get("trade_id"),
                "validation_timestamp": result.get("validation_timestamp"),
                "rule_enforced": "sell_before_buy",
            },
            "meta": {
                "source": "trade_lifecycle_service",
                "enforcement_type": "sell_before_buy_rule",
            },
        }
        
        log_structured(
            "info",
            "sell_before_buy_enforced",
            trade_id=result.get("trade_id"),
            agent_id=result.get("agent_id"),
            symbol=result.get("symbol"),
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        log_structured(
            "error",
            "sell_before_buy_enforcement_error",
            trade_data=trade_data,
            error=str(e),
            exc_info=True,
        )
        
        raise HTTPException(status_code=500, detail="SELL before BUY enforcement failed")


@router.post("/enforce/buy-sequence")
async def enforce_buy_sequence(
    trade_data: Dict[str, Any],
    session: AsyncSession = Depends(get_async_session),
):
    """
    Enforce BUY sequence rules for all trades.
    
    Prevents invalid trade sequences:
    - No multiple OPEN positions for same symbol
    - Position limits respected
    - Proper trade sequencing
    """
    try:
        enforcer = TradeLifecycleEnforcer(session)
        result = await enforcer.enforce_buy_sequence_rule(trade_data)
        
        if result["rejected"]:
            raise HTTPException(status_code=400, detail=result["reason"])
        
        response = {
            "success": True,
            "data": {
                "trade_id": result.get("trade_id"),
                "validation_timestamp": result.get("validation_timestamp"),
                "rule_enforced": "buy_sequence",
            },
            "meta": {
                "source": "trade_lifecycle_service",
                "enforcement_type": "buy_sequence_rule",
            },
        }
        
        log_structured(
            "info",
            "buy_sequence_enforced",
            trade_id=result.get("trade_id"),
            agent_id=result.get("agent_id"),
            symbol=result.get("symbol"),
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        log_structured(
            "error",
            "buy_sequence_enforcement_error",
            trade_data=trade_data,
            error=str(e),
            exc_info=True,
        )
        
        raise HTTPException(status_code=500, detail="BUY sequence enforcement failed")


@router.get("/violations/{agent_id}")
async def get_lifecycle_violations(
    agent_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get all lifecycle violations for an agent.
    
    Returns:
    - SELL before BUY violations
    - BUY sequence violations
    - Position consistency issues
    - Orphaned trades
    """
    try:
        enforcer = TradeLifecycleEnforcer(session)
        
        # Get all violations
        orphaned_sells = await enforcer.check_orphaned_sells()
        sequence_violations = await enforcer.check_sequence_violations(agent_id)
        position_issues = await enforcer.check_position_consistency(agent_id)
        
        violations = {
            "orphaned_sells": len(orphaned_sells),
            "sequence_violations": len(sequence_violations),
            "position_issues": len(position_issues),
            "total_violations": len(orphaned_sells) + len(sequence_violations) + len(position_issues),
            "agent_id": agent_id,
            "check_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        response = {
            "success": True,
            "data": violations,
            "meta": {
                "source": "trade_lifecycle_service",
                "check_type": "violations_summary",
            },
        }
        
        log_structured(
            "info",
            "lifecycle_violations_retrieved",
            agent_id=agent_id,
            total_violations=violations["total_violations"],
        )
        
        return response
        
    except Exception as e:
        log_structured(
            "error",
            "lifecycle_violations_error",
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )
        
        raise HTTPException(status_code=500, detail="Lifecycle violations check failed")


@router.get("/health")
async def lifecycle_enforcement_health(
    session: AsyncSession = Depends(get_async_session),
):
    """
    Health check for trade lifecycle enforcement service.
    
    Returns service status and basic metrics.
    """
    try:
        enforcer = TradeLifecycleEnforcer(session)
        
        # Get basic metrics
        orphaned_count = len(await enforcer.check_orphaned_sells())
        
        response = {
            "success": True,
            "data": {
                "status": "healthy",
                "orphaned_sells": orphaned_count,
                "enforcement_active": True,
                "check_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "meta": {
                "source": "trade_lifecycle_service",
                "check_type": "health",
            },
        }
        
        log_structured(
            "info",
            "lifecycle_enforcement_health",
            status="healthy",
            orphaned_sells=orphaned_count,
        )
        
        return response
        
    except Exception as e:
        log_structured(
            "error",
            "lifecycle_enforcement_health_error",
            error=str(e),
            exc_info=True,
        )
        
        raise HTTPException(status_code=500, detail="Lifecycle enforcement health check failed")
