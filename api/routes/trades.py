from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.core.models import Trade, TradeModel
from api.database import get_async_session

router = APIRouter(tags=["trades"])


@router.get("/api/trades")
async def get_trades():
    try:
        async with get_async_session() as session:
            result = await session.execute(select(Trade).order_by(Trade.created_at.desc()))
            trades = result.scalars().all()
            return {
                "trades": [
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
            }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to fetch trades: {exc}")


@router.post("/api/trades")
async def save_trade(trade: TradeModel):
    try:
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
            return {"message": "Trade saved successfully", "id": db_trade.id}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to save trade: {exc}")
