from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.core.models import Trade, TradeModel
from api.database import get_async_session

router = APIRouter(tags=["trades"])


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None


@router.get("/trades")
async def get_trades() -> Dict[str, Any]:
    """Get all trades with standardized response format."""
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(Trade).order_by(Trade.created_at.desc())
            )
            trades = result.scalars().all()

            trades_data = [
                {
                    "id": t.id,
                    "date": t.date,
                    "asset": t.asset,
                    "direction": t.direction,
                    "size": t.size,
                    "entry": t.entry,
                    "stop": t.stop,
                    "target": t.target,
                    "rr_ratio": t.rr_ratio,
                    "exit_price": t.exit_price,
                    "pnl": t.pnl,
                    "outcome": t.outcome,
                }
                for t in trades
            ]

            return StandardResponse(
                success=True, data={"trades": trades_data}
            ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch trades: {str(exc)}"
        )


@router.post("/trades")
async def save_trade(trade: TradeModel) -> Dict[str, Any]:
    """Save a new trade with standardized response format."""
    try:
        # Validate input data
        if not trade.asset or not trade.direction:
            raise HTTPException(
                status_code=400, detail="Asset and direction are required"
            )

        async with get_async_session() as session:
            db_trade = Trade(
                date=trade.date,
                asset=trade.asset,
                direction=trade.direction,
                size=trade.size,
                entry=trade.entry,
                stop=trade.stop,
                target=trade.target,
                rr_ratio=trade.rr_ratio,
                exit_price=trade.exit,
                pnl=trade.pnl,
                outcome=trade.outcome,
            )
            session.add(db_trade)
            await session.flush()

            return StandardResponse(
                success=True,
                data={"message": "Trade saved successfully", "id": db_trade.id},
            ).model_dump()
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
