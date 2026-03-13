from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

from multi_agent_orchestrator import MultiAgentOrchestrator


@dataclass
class VirtualTrade:
    symbol: str
    created_at: datetime
    intended_price: float
    decision: str
    confidence: float


class TradingService:
    def __init__(self, orchestrator: MultiAgentOrchestrator):
        self.orchestrator = orchestrator
        self.virtual_trades: List[VirtualTrade] = []

    def analyze(self, symbol: str, price: float, extra_signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        signals = [{"symbol": symbol, "price": price}, *extra_signals]
        return self.orchestrator.process_trade_signals(signals)

    def run_shadow(self, symbol: str, price: float, extra_signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = self.analyze(symbol, price, extra_signals)
        self.virtual_trades.append(
            VirtualTrade(
                symbol=symbol,
                created_at=datetime.utcnow(),
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
        slippage_variance = abs(observed_price - trade.intended_price) / max(trade.intended_price, 1)
        age_seconds = (datetime.utcnow() - trade.created_at) / timedelta(seconds=1)
        profitable = (observed_price > trade.intended_price and trade.decision == "LONG") or (
            observed_price < trade.intended_price and trade.decision == "SHORT"
        )
        return {
            "status": "evaluated",
            "symbol": symbol,
            "decision": trade.decision,
            "slippage_variance": round(slippage_variance, 6),
            "trajectory_similarity": 1.0 if profitable else 0.0,
            "confidence_score": round((1 - min(slippage_variance, 1.0)) * trade.confidence, 4),
            "age_seconds": int(age_seconds),
        }
