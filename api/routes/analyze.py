from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.core.models import TradeDecision, TradeRequest
from api.database import get_async_session
from api.main_state import (
    get_learning_service,
    get_run_lifecycle_service,
    get_trading_service,
)
from api.observability import log_structured, metrics_store
from api.utils import with_retries

router = APIRouter(tags=["analysis"])


class StandardResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None


@router.post("/analyze")
async def analyze_trade(
    request: TradeRequest,
    trading_service=Depends(get_trading_service),
    learning_service=Depends(get_learning_service),
    run_lifecycle_service=Depends(get_run_lifecycle_service),
):
    try:
        if not request.symbol or not request.price:
            raise HTTPException(status_code=400, detail="Symbol and price are required")

        start = datetime.now(timezone.utc)

        async def _run_analysis():
            return trading_service.analyze(
                request.symbol, request.price, request.signals or []
            )

        metrics_store.log_event("task_started", symbol=request.symbol, task="analyze")
        for agent in ["SIGNAL_AGENT", "CONSENSUS_AGENT", "RISK_AGENT", "SIZING_AGENT"]:
            metrics_store.update_agent(
                agent, "running", current_task=f"analyze {request.symbol}"
            )

        try:
            result = await with_retries(_run_analysis)
        except Exception as exc:  # noqa: BLE001
            for agent in [
                "SIGNAL_AGENT",
                "CONSENSUS_AGENT",
                "RISK_AGENT",
                "SIZING_AGENT",
            ]:
                metrics_store.update_agent(
                    agent,
                    "failed",
                    error=str(exc),
                    last_task=f"analyze {request.symbol}",
                )
            metrics_store.log_event(
                "task_failed", symbol=request.symbol, task="analyze", error=str(exc)
            )
            log_structured(
                "error", "Trade analysis failed", symbol=request.symbol, error=str(exc)
            )
            raise HTTPException(
                status_code=500, detail="Trade analysis failed"
            ) from exc

        async with get_async_session() as session:
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            for agent in [
                "SIGNAL_AGENT",
                "RISK_AGENT",
                "CONSENSUS_AGENT",
                "SIZING_AGENT",
            ]:
                await learning_service.record_agent_call(agent, True, elapsed, session)
                metrics_store.update_agent(
                    agent,
                    "idle",
                    health="ok",
                    latency_ms=round(elapsed * 1000, 2),
                    last_task=f"analyze {request.symbol}",
                )

            history = trading_service.orchestrator.get_trade_history()
            if history:
                await run_lifecycle_service.complete_run(history[-1])

        estimated_tokens = max(200, len(str(result)) // 2)
        estimated_cost_usd = round(estimated_tokens * 0.000003, 6)
        metrics_store.log_event(
            "task_completed",
            symbol=request.symbol,
            task="analyze",
            latency_ms=round(
                (datetime.now(timezone.utc) - start).total_seconds() * 1000, 2
            ),
            token_usage=estimated_tokens,
            cost_usd=estimated_cost_usd,
        )

        decision = TradeDecision(
            symbol=request.symbol,
            decision=result.get("DECISION", "FLAT"),
            confidence=float(result.get("confidence", 0.0)),
            reasoning=result.get("reasoning", "Analysis completed"),
            timestamp=datetime.now(timezone.utc),
            position_size=result.get("position_size"),
            risk_assessment=result.get("risk_assessment"),
        )

        return StandardResponse(success=True, data=decision.model_dump()).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/shadow/analyze")
async def shadow_analyze(
    request: TradeRequest,
    trading_service=Depends(get_trading_service),
):
    try:
        if not request.symbol or not request.price:
            raise HTTPException(status_code=400, detail="Symbol and price are required")

        metrics_store.log_event(
            "task_started", symbol=request.symbol, task="shadow_analyze"
        )
        result = trading_service.run_shadow(
            request.symbol, request.price, request.signals or []
        )
        metrics_store.log_event(
            "task_completed", symbol=request.symbol, task="shadow_analyze"
        )
        return StandardResponse(
            success=True, data={"mode": "shadow", "result": result}
        ).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Shadow analysis failed: {str(e)}")


@router.get("/shadow/evaluate/{symbol}")
async def shadow_evaluate(
    symbol: str, observed_price: float, trading_service=Depends(get_trading_service)
):
    try:
        if not symbol or observed_price <= 0:
            raise HTTPException(
                status_code=400, detail="Symbol and valid price are required"
            )

        result = trading_service.evaluate_shadow(symbol, observed_price)
        if result.get("status") == "no_data":
            raise HTTPException(status_code=404, detail="No shadow trades for symbol")
        return StandardResponse(success=True, data=result).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Shadow evaluation failed: {str(e)}"
        )


@router.options("/analyze")
@router.options("/shadow/analyze")
@router.options("/shadow/evaluate/{symbol}")
async def analyze_options():
    return StandardResponse(
        success=True,
        data={"message": "Analyze endpoints support GET, POST, and OPTIONS"},
    ).model_dump()
