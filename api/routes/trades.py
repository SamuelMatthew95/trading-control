from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from api.constants import FieldName
from api.core.models import TradePerformance
from api.core.schemas import StandardResponse
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionLocal

router = APIRouter(tags=["trades"])


async def get_safe_writer() -> SafeWriter:
    """Get SafeWriter instance."""
    return SafeWriter(AsyncSessionLocal)


@router.get("/trades")
async def get_trades(
    safe_writer: Annotated[SafeWriter, Depends(get_safe_writer)],
) -> dict[str, Any]:
    """Get all trades with standardized response format."""
    try:
        async with safe_writer.transaction() as session:
            result = await session.execute(
                select(TradePerformance).order_by(TradePerformance.created_at.desc())
            )
            trades = result.scalars().all()

            trades_data = [
                {
                    FieldName.ID: str(t.id),
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

            return StandardResponse(success=True, data={FieldName.TRADES: trades_data}).model_dump()
    except (OperationalError, ProgrammingError):
        # In degraded environments (fresh DB / local sqlite without migrations),
        # return an empty payload instead of failing the endpoint.
        return StandardResponse(success=True, data={FieldName.TRADES: []}).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trades: {str(exc)}") from None


@router.post("/trades")
async def save_trade(
    trade_data: dict[str, Any],
    safe_writer: Annotated[SafeWriter, Depends(get_safe_writer)],
) -> dict[str, Any]:
    """Save a new trade using SafeWriter (only write path)."""
    try:
        # Validate input data
        if not trade_data.get(FieldName.SYMBOL) or not trade_data.get(FieldName.TRADE_TYPE):
            raise HTTPException(status_code=400, detail="Symbol and trade_type are required")

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
        raise HTTPException(status_code=409, detail="Trade was already processed")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save trade: {str(exc)}") from None


@router.options("/trades")
async def trades_options() -> dict[str, Any]:
    """OPTIONS method for trades endpoint."""
    return StandardResponse(
        success=True,
        data={"message": "Trades endpoint supports GET, POST, and OPTIONS"},
    ).model_dump()


# Bot Control Endpoints
@router.post("/trading/start")
async def start_trading_bot() -> dict[str, Any]:
    """Start the trading bot with standardized response format."""
    try:
        bot_state.update(
            {
                FieldName.RUNNING: True,
                "status": "running",
                FieldName.LAST_ACTION: "start",
                FieldName.LAST_ACTION_TIME: "just now",
            }
        )

        return StandardResponse(
            success=True,
            data={
                "status": "starting",
                "message": "Trading bot start initiated",
                FieldName.BOT_STATE: bot_state,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to start trading bot: {str(exc)}"
        ) from None


@router.post("/trading/stop")
async def stop_trading_bot() -> dict[str, Any]:
    """Stop the trading bot with standardized response format."""
    try:
        bot_state.update(
            {
                FieldName.RUNNING: False,
                "status": "stopped",
                FieldName.LAST_ACTION: "stop",
                FieldName.LAST_ACTION_TIME: "just now",
            }
        )

        return StandardResponse(
            success=True,
            data={
                "status": "stopping",
                "message": "Trading bot stop initiated",
                FieldName.BOT_STATE: bot_state,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop trading bot: {str(exc)}"
        ) from None


@router.get("/trading/status")
async def get_trading_status() -> dict[str, Any]:
    """Get current trading bot status with standardized response format."""
    try:
        return StandardResponse(
            success=True,
            data={
                FieldName.RUNNING: bot_state[FieldName.RUNNING],
                "status": bot_state[FieldName.STATUS],
                FieldName.LAST_ACTION: bot_state[FieldName.LAST_ACTION],
                FieldName.UPTIME: f"{bot_state[FieldName.UPTIME_MINUTES] // 60}h {bot_state[FieldName.UPTIME_MINUTES] % 60}m",
                FieldName.ACTIVE_POSITION: bot_state.get(FieldName.ACTIVE_POSITION, "None"),
                FieldName.RISK_EXPOSURE: bot_state[FieldName.RISK_EXPOSURE],
                FieldName.TOTAL_TRADES: bot_state[FieldName.TOTAL_TRADES],
                FieldName.PERFORMANCE: (
                    bot_state[FieldName.PERFORMANCE][-30:]
                    if bot_state[FieldName.PERFORMANCE]
                    else [0] * 30
                ),
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get trading status: {str(exc)}"
        ) from None


@router.post("/trading/emergency-stop")
async def emergency_stop_all() -> dict[str, Any]:
    """Emergency stop all trading activities with standardized response format."""
    try:
        bot_state.update(
            {
                FieldName.RUNNING: False,
                "status": "emergency_stopped",
                FieldName.LAST_ACTION: "emergency_stop",
                FieldName.LAST_ACTION_TIME: "just now",
            }
        )

        return StandardResponse(
            success=True,
            data={
                "status": "emergency_stopped",
                "message": "Emergency stop executed - all trading halted",
                FieldName.BOT_STATE: bot_state,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to execute emergency stop: {str(exc)}"
        ) from None


@router.get("/trading/bots")
async def get_bots_status() -> dict[str, Any]:
    """Get status of all bots for dashboard with standardized response format."""
    try:
        # Simulate multiple bots - in production this would query database
        bots = [
            {
                FieldName.ID: "trading-bot-1",
                FieldName.NAME: "Alpha Trading Bot",
                FieldName.STRATEGY: "Mean Reversion",
                "status": "running" if bot_state[FieldName.RUNNING] else "stopped",
                FieldName.UPTIME: str(bot_state[FieldName.UPTIME_MINUTES]),
                FieldName.PERFORMANCE: (
                    bot_state[FieldName.PERFORMANCE][-30:]
                    if bot_state[FieldName.PERFORMANCE]
                    else [0] * 30
                ),
                FieldName.ACTIVE_POSITION: bot_state.get(FieldName.ACTIVE_POSITION),
                FieldName.RISK_EXPOSURE: bot_state[FieldName.RISK_EXPOSURE],
                FieldName.TOTAL_TRADES: bot_state[FieldName.TOTAL_TRADES],
                FieldName.LAST_SIGNAL: "BUY BTC/USD" if bot_state[FieldName.RUNNING] else None,
            }
        ]

        return StandardResponse(
            success=True,
            data={
                FieldName.BOTS: bots,
                FieldName.TOTAL_ACTIVE: 1 if bot_state[FieldName.RUNNING] else 0,
                FieldName.TOTAL_BOTS: 1,
            },
        ).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get bots status: {str(exc)}"
        ) from None


@router.options("/trading/start")
@router.options("/trading/stop")
@router.options("/trading/status")
@router.options("/trading/emergency-stop")
@router.options("/bots/status")
async def trading_options() -> dict[str, Any]:
    """OPTIONS method for trading endpoints."""
    return StandardResponse(
        success=True,
        data={"message": "Trading endpoints support GET, POST, and OPTIONS"},
    ).model_dump()


# Global bot state (in production this would be in a database)
bot_state = {
    FieldName.RUNNING: False,
    "status": "stopped",
    FieldName.UPTIME_MINUTES: 0,
    FieldName.ACTIVE_POSITION: None,
    FieldName.RISK_EXPOSURE: 0.0,
    FieldName.TOTAL_TRADES: 0,
    FieldName.PERFORMANCE: [0] * 30,
    FieldName.LAST_ACTION: "none",
    FieldName.LAST_ACTION_TIME: None,
}
