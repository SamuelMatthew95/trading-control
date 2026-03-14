import pytest
from api.services.trading import TradingService
from multi_agent_orchestrator import (DeterministicReasoningModel,
                                      MultiAgentOrchestrator, ToolError,
                                      TradeTools)


class ContradictoryModel(DeterministicReasoningModel):
    def complete_json(self, *, system_prompt, payload):
        if "normalize trade signals" in system_prompt.lower():
            return [
                {
                    "source": "a",
                    "direction": "LONG",
                    "confidence": 0.9,
                    "timeframe": "1D",
                },
                {
                    "source": "b",
                    "direction": "SHORT",
                    "confidence": 0.9,
                    "timeframe": "1D",
                },
            ]
        if "compute consensus" in system_prompt.lower():
            return {
                "direction": "LONG",
                "agreement_ratio": 0.49,
                "signal_strength": 0.4,
            }
        return super().complete_json(system_prompt=system_prompt, payload=payload)


def test_contradictory_signals_are_flagged_low_consensus():
    orchestrator = MultiAgentOrchestrator(api_key=None)
    orchestrator.executor.model = ContradictoryModel()
    result = orchestrator.analyze_trade(
        "AAPL", "1D", {"total_value": 100000, "drawdown": -0.01}
    )
    assert "LOW_CONSENSUS" in result["RISK FLAGS"]


@pytest.mark.asyncio
async def test_tool_retry_and_circuit_breaker_on_repeated_provider_failures():
    from api.database import AsyncSessionLocal
    from api.core.models import VectorMemoryRecord
    from sqlalchemy import delete
    
    # Clean up negative memories to ensure test isolation
    async with AsyncSessionLocal() as session:
        await session.execute(delete(VectorMemoryRecord).where(VectorMemoryRecord.store_type == "negative-memory"))
        await session.commit()
    
    calls = {"n": 0}

    def flaky_provider(_asset: str) -> float:
        calls["n"] += 1
        raise RuntimeError("500 from exchange")

    tools = TradeTools(
        price_provider=flaky_provider, max_retries=1, circuit_breaker_threshold=2
    )

    try:
        await tools.get_current_price("AAPL")
        assert False, "Expected ToolError"
    except ToolError:
        assert calls["n"] == 2

    try:
        await tools.get_current_price("AAPL")
        assert False, "Expected open circuit ToolError"
    except ToolError as exc:
        assert "circuit" in str(exc).lower()


def test_shadow_mode_persists_and_evaluates_virtual_trade():
    service = TradingService(MultiAgentOrchestrator(api_key=None))
    service.run_shadow("AAPL", 100.0, [])
    eval_result = service.evaluate_shadow("AAPL", observed_price=101.0)
    assert eval_result["status"] == "evaluated"
    assert "confidence_score" in eval_result
