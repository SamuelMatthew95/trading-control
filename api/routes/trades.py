from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from api.core.models import TradePerformance
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionLocal
from api.core.schemas import StandardResponse

router = APIRouter(prefix="/trades", tags=["trades"])


async def get_safe_writer() -> SafeWriter:
    """Get SafeWriter instance."""
    return SafeWriter(AsyncSessionLocal)


@router.get("/")
async def get_trades(safe_writer: SafeWriter = Depends(get_safe_writer)) -> Dict[str, Any]:
    """Get all trades with standardized response format."""
    try:
        async with safe_writer.transaction() as session:
            result = await session.execute(
                select(TradePerformance).order_by(TradePerformance.created_at.desc())
            )
            trades = result.scalars().all()

            trades_data = [
                {
                    "id": str(t.id),
                    "symbol": t.symbol,
                    "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                    "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                    "entry_price": float(t.entry_price),
                    "exit_price": float(t.exit_price) if t.exit_price else None,
                    "quantity": float(t.quantity),
                    "pnl": float(t.pnl) if t.pnl else None,
                    "pnl_percent": float(t.pnl_percent) if t.pnl_percent else None,
                    "trade_type": t.trade_type,
                    "exit_reason": t.exit_reason,
                }
                for t in trades
            ]

            return StandardResponse(
                success=True, data={"trades": trades_data}
            ).model_dump()
    except (OperationalError, ProgrammingError):
        # In degraded environments (fresh DB / local sqlite without migrations),
        # return an empty payload instead of failing the endpoint.
        return StandardResponse(success=True, data={"trades": []}).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch trades: {str(exc)}"
        )


@router.post("/trades")
async def save_trade(
    trade_data: Dict[str, Any], 
    safe_writer: SafeWriter = Depends(get_safe_writer)
) -> Dict[str, Any]:
    """Save a new trade using SafeWriter (only write path)."""
    try:
        # Validate input data
        if not trade_data.get("symbol") or not trade_data.get("trade_type"):
            raise HTTPException(
                status_code=400, detail="Symbol and trade_type are required"
            )

        # Generate unique message ID for exactly-once semantics
        msg_id = str(uuid4())
        stream = "trade_api"
        
        # Use SafeWriter - the ONLY write path
        success = await safe_writer.write_trade_performance(msg_id, stream, trade_data)
        
        if success:
            return StandardResponse(
                success=True,
                data={"message": "Trade saved successfully", "msg_id": msg_id},
            ).model_dump()
        else:
            raise HTTPException(
                status_code=409, detail="Trade was already processed"
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save trade: {str(exc)}")


@router.options("/trades")
async def trades_options() -> Dict[str, Any]:
    """OPTIONS method for trades endpoint."""
    return StandardResponse(
        success=True,
        data={"message": "Trades endpoint supports GET, POST, and OPTIONS"},
    ).model_dump()


# Bot Control Endpoints
@router.post("/trading/start")
async def start_trading_bot() -> Dict[str, Any]:
    """Start the trading bot with standardized response format."""
    try:
        bot_state.update(
            {
                "running": True,
                "status": "running",
                "last_action": "start",
                "last_action_time": "just now",
            }
        )

        return StandardResponse(
            success=True,
            data={
                "status": "starting",
                "message": "Trading bot start initiated",
                "bot_state": bot_state,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to start trading bot: {str(exc)}"
        )


@router.post("/trading/stop")
async def stop_trading_bot() -> Dict[str, Any]:
    """Stop the trading bot with standardized response format."""
    try:
        bot_state.update(
            {
                "running": False,
                "status": "stopped",
                "last_action": "stop",
                "last_action_time": "just now",
            }
        )

        return StandardResponse(
            success=True,
            data={
                "status": "stopping",
                "message": "Trading bot stop initiated",
                "bot_state": bot_state,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop trading bot: {str(exc)}"
        )


@router.get("/trading/status")
async def get_trading_status() -> Dict[str, Any]:
    """Get current trading bot status with standardized response format."""
    try:

        return StandardResponse(
            success=True,
            data={
                "running": bot_state["running"],
                "status": bot_state["status"],
                "last_action": bot_state["last_action"],
                "uptime": f"{bot_state['uptime_minutes'] // 60}h {bot_state['uptime_minutes'] % 60}m",
                "active_position": bot_state.get("active_position", "None"),
                "risk_exposure": bot_state["risk_exposure"],
                "total_trades": bot_state["total_trades"],
                "performance": (
                    bot_state["performance"][-30:]
                    if bot_state["performance"]
                    else [0] * 30
                ),
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get trading status: {str(exc)}"
        )


@router.post("/trading/emergency-stop")
async def emergency_stop_all() -> Dict[str, Any]:
    """Emergency stop all trading activities with standardized response format."""
    try:
        bot_state.update(
            {
                "running": False,
                "status": "emergency_stopped",
                "last_action": "emergency_stop",
                "last_action_time": "just now",
            }
        )

        return StandardResponse(
            success=True,
            data={
                "status": "emergency_stopped",
                "message": "Emergency stop executed - all trading halted",
                "bot_state": bot_state,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to execute emergency stop: {str(exc)}"
        )


@router.get("/trading/bots")
async def get_bots_status() -> Dict[str, Any]:
    """Get status of all bots for dashboard with standardized response format."""
    try:

        # Simulate multiple bots - in production this would query database
        bots = [
            {
                "id": "trading-bot-1",
                "name": "Alpha Trading Bot",
                "strategy": "Mean Reversion",
                "status": "running" if bot_state["running"] else "stopped",
                "uptime": str(bot_state["uptime_minutes"]),
                "performance": (
                    bot_state["performance"][-30:]
                    if bot_state["performance"]
                    else [0] * 30
                ),
                "active_position": bot_state.get("active_position"),
                "risk_exposure": bot_state["risk_exposure"],
                "total_trades": bot_state["total_trades"],
                "last_signal": "BUY BTC/USD" if bot_state["running"] else None,
            }
        ]

        return StandardResponse(
            success=True,
            data={
                "bots": bots,
                "total_active": 1 if bot_state["running"] else 0,
                "total_bots": 1,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get bots status: {str(exc)}"
        )


@router.options("/trading/start")
@router.options("/trading/stop")
@router.options("/trading/status")
@router.options("/trading/emergency-stop")
@router.options("/bots/status")
async def trading_options() -> Dict[str, Any]:
    """OPTIONS method for trading endpoints."""
    return StandardResponse(
        success=True,
        data={"message": "Trading endpoints support GET, POST, and OPTIONS"},
    ).model_dump()


# Global bot state (in production this would be in a database)
bot_state = {
    "running": False,
    "status": "stopped",
    "uptime_minutes": 0,
    "active_position": None,
    "risk_exposure": 0.0,
    "total_trades": 0,
    "performance": [0] * 30,
    "last_action": "none",
    "last_action_time": None,
}
