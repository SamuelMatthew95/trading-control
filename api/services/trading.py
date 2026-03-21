from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from multi_agent_orchestrator import MultiAgentOrchestrator
except ImportError:
    MultiAgentOrchestrator = None


@dataclass
class VirtualTrade:
    symbol: str
    created_at: datetime
    intended_price: float
    decision: str
    confidence: float


class TradingService:
    def __init__(self, orchestrator: Optional[MultiAgentOrchestrator]):
        self.orchestrator = orchestrator
        self.virtual_trades: List[VirtualTrade] = []

    def analyze(
        self, symbol: str, price: float, extra_signals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not self.orchestrator:
            from api.observability import log_structured

            log_structured(
                "warning",
                "MOCK MODE: Trading analysis using mock response",
                symbol=symbol,
                price=price,
            )
            return {
                "DECISION": "FLAT",
                "confidence": 0.0,
                "reasoning": "MOCK MODE: Orchestrator not available - analysis disabled",
                "position_size": 0.0,
                "risk_assessment": "low",
            }
        signals = [{"symbol": symbol, "price": price}, *extra_signals]
        return self.orchestrator.process_trade_signals(signals)

    def run_shadow(
        self, symbol: str, price: float, extra_signals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        result = self.analyze(symbol, price, extra_signals)
        self.virtual_trades.append(
            VirtualTrade(
                symbol=symbol,
                created_at=datetime.now(timezone.utc),
                intended_price=price,
                decision=result.get("DECISION", "FLAT"),
                confidence=float(result.get("confidence", 0)),
            )
        )
        return result

    def evaluate_shadow(self, symbol: str, observed_price: float) -> Dict[str, Any]:
        candidates = [trade for trade in self.virtual_trades if trade.symbol == symbol]
        if not candidates:
            return {"status": "no_data"}
        trade = candidates[-1]
        slippage_variance = abs(observed_price - trade.intended_price) / max(
            trade.intended_price, 1
        )
        age_seconds = (datetime.now(timezone.utc) - trade.created_at) / timedelta(
            seconds=1
        )
        profitable = (
            observed_price > trade.intended_price and trade.decision == "LONG"
        ) or (observed_price < trade.intended_price and trade.decision == "SHORT")
        return {
            "status": "evaluated",
            "symbol": symbol,
            "decision": trade.decision,
            "slippage_variance": round(slippage_variance, 6),
            "trajectory_similarity": 1.0 if profitable else 0.0,
            "confidence_score": round(
                (1 - min(slippage_variance, 1.0)) * trade.confidence, 4
            ),
            "age_seconds": int(age_seconds),
        }
