from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from api.core.models import TradeDecision, TradeRequest
from api.main_state import get_learning_service, get_memory_service, get_trading_service
from api.database import get_async_session

router = APIRouter(tags=["analysis"])


@router.post("/api/analyze", response_model=TradeDecision)
async def analyze_trade(
    request: TradeRequest,
    trading_service=Depends(get_trading_service),
    learning_service=Depends(get_learning_service),
    memory_service=Depends(get_memory_service),
):
    start = datetime.utcnow()
    result = trading_service.analyze(request.symbol, request.price, request.signals or [])

    async with get_async_session() as session:
        elapsed = (datetime.utcnow() - start).total_seconds()
        for agent in ["SIGNAL_AGENT", "RISK_AGENT", "CONSENSUS_AGENT", "SIZING_AGENT"]:
            await learning_service.record_agent_call(agent, True, elapsed, session)

        history = trading_service.orchestrator.get_trade_history()
        if history:
            await memory_service.persist_run(session, history[-1])

    return TradeDecision(
        symbol=request.symbol,
        decision=result.get("DECISION", "FLAT"),
        confidence=float(result.get("confidence", 0.0)),
        reasoning=result.get("reasoning", "Analysis completed"),
        timestamp=datetime.utcnow(),
        position_size=result.get("position_size"),
        risk_assessment=result.get("risk_assessment"),
    )


@router.post("/api/shadow/analyze")
async def shadow_analyze(
    request: TradeRequest,
    trading_service=Depends(get_trading_service),
):
    return {"mode": "shadow", "result": trading_service.run_shadow(request.symbol, request.price, request.signals or [])}


@router.get("/api/shadow/evaluate/{symbol}")
async def shadow_evaluate(symbol: str, observed_price: float, trading_service=Depends(get_trading_service)):
    result = trading_service.evaluate_shadow(symbol, observed_price)
    if result.get("status") == "no_data":
        raise HTTPException(status_code=404, detail="No shadow trades for symbol")
    return result
