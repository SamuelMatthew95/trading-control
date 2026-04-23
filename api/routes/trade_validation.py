"""
Trade validation endpoints with strict enforcement.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_async_session
from api.observability import log_structured
from api.services.trade_validation import TradeValidationService

router = APIRouter(prefix="/api/trades", tags=["trade-validation"])


@router.post("/validate")
async def validate_trade_creation(
    trade_data: dict[str, Any],
    session: AsyncSession = Depends(get_async_session),
):
    """
    Validate trade creation with strict requirements.

    Enforces:
    - All required identifiers present
    - Financial data consistency
    - Trade lifecycle validity
    - No duplicate signals
    """
    try:
        service = TradeValidationService(session)
        result = await service.validate_trade_creation(trade_data)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        response = {
            "success": True,
            "data": {
                "trade_id": result.get("trade_id"),
                "validation_timestamp": result.get("validation_timestamp"),
                "validation_summary": result.get("validation_summary"),
            },
            "meta": {
                "source": "trade_validation_service",
                "validation_type": "trade_creation",
            },
        }

        log_structured(
            "info",
            "trade_validation_success",
            trade_id=result.get("trade_id"),
            validation_timestamp=result.get("validation_timestamp"),
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        log_structured(
            "error",
            "trade_validation_endpoint_error",
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Trade validation failed") from e


@router.put("/validate/{trade_id}")
async def validate_trade_update(
    trade_id: str,
    update_data: dict[str, Any],
    session: AsyncSession = Depends(get_async_session),
):
    """
    Validate trade update with strict requirements.

    Enforces:
    - Trade exists and is updateable
    - Financial data consistency
    - Trade lifecycle validity
    - Required identifiers preserved
    """
    try:
        service = TradeValidationService(session)
        result = await service.validate_trade_update(trade_id, update_data)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        response = {
            "success": True,
            "data": {
                "trade_id": trade_id,
                "update_timestamp": result.get("update_timestamp"),
                "validation_summary": result.get("validation_summary"),
            },
            "meta": {
                "source": "trade_validation_service",
                "validation_type": "trade_update",
            },
        }

        log_structured(
            "info",
            "trade_update_validation_success",
            trade_id=trade_id,
            update_timestamp=result.get("update_timestamp"),
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        log_structured(
            "error",
            "trade_update_validation_error",
            trade_id=trade_id,
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Trade update validation failed") from e


@router.get("/validate/relationships/{trade_id}")
async def validate_trade_relationships(
    trade_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Validate trade relationships with strict requirements.

    Enforces:
    - Parent/child relationships are valid
    - No orphaned trades
    - Proper trade pairing
    - Required identifiers preserved
    """
    try:
        service = TradeValidationService(session)
        result = await service.validate_trade_relationships(trade_id)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        response = {
            "success": True,
            "data": {
                "trade_id": trade_id,
                "related_trades": result.get("related_trades"),
                "validation_timestamp": result.get("validation_timestamp"),
                "validation_summary": result.get("validation_summary"),
            },
            "meta": {
                "source": "trade_validation_service",
                "validation_type": "trade_relationships",
            },
        }

        log_structured(
            "info",
            "trade_relationships_validation_success",
            trade_id=trade_id,
            related_trades=result.get("related_trades"),
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        log_structured(
            "error",
            "trade_relationships_validation_error",
            trade_id=trade_id,
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Trade relationships validation failed") from e


@router.get("/validate/consistency/{agent_id}")
async def validate_agent_consistency(
    agent_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Validate agent trade consistency with strict requirements.

    Enforces:
    - No conflicting positions
    - Proper trade lifecycle
    - Required identifiers present
    - Financial data consistency
    """
    try:
        service = TradeValidationService(session)
        result = await service.enforce_trade_consistency(agent_id, "BTC")

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        response = {
            "success": True,
            "data": {
                "agent_id": agent_id,
                "symbol": "BTC",
                "consistency_check": result.get("consistency_check"),
                "validation_timestamp": result.get("validation_timestamp"),
                "validation_summary": result.get("validation_summary"),
            },
            "meta": {
                "source": "trade_validation_service",
                "validation_type": "agent_consistency",
            },
        }

        log_structured(
            "info",
            "agent_consistency_validation_success",
            agent_id=agent_id,
            consistency_check=result.get("consistency_check"),
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        log_structured(
            "error",
            "agent_consistency_validation_error",
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Agent consistency validation failed") from e


@router.get("/health")
async def validation_service_health(
    session: AsyncSession = Depends(get_async_session),
):
    """
    Health check for trade validation service.

    Returns service status and basic metrics.
    """
    try:
        service = TradeValidationService(session)
        summary = await service.get_validation_summary()

        response = {
            "success": True,
            "data": {
                "status": "healthy",
                "total_validations": summary.get("total_trades", 0),
                "validation_errors": summary.get("validation_errors", 0),
                "service_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "meta": {
                "source": "trade_validation_service",
                "check_type": "health",
            },
        }

        log_structured(
            "info",
            "trade_validation_health",
            status="healthy",
            total_validations=summary.get("total_trades", 0),
        )

        return response

    except Exception as e:
        log_structured(
            "error",
            "trade_validation_health_error",
            error=str(e),
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Health check failed") from e
