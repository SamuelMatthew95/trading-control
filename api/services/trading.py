from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from api.constants import FieldName
from api.observability import log_structured

try:
    from api.services.multi_agent_orchestrator import MultiAgentOrchestrator
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
    def __init__(self, orchestrator: MultiAgentOrchestrator | None):
        self.orchestrator = orchestrator
        self.virtual_trades: list[VirtualTrade] = []

    def analyze(
        self, symbol: str, price: float, extra_signals: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not self.orchestrator:
            log_structured(
                "warning",
                "MOCK MODE: Trading analysis using mock response",
                symbol=symbol,
                price=price,
            )
            return {
                "DECISION": "FLAT",
                FieldName.CONFIDENCE: 0.0,
                FieldName.REASONING: "MOCK MODE: Orchestrator not available - analysis disabled",
                FieldName.POSITION_SIZE: 0.0,
                FieldName.RISK_ASSESSMENT: "low",
            }
        signals = [{FieldName.SYMBOL: symbol, FieldName.PRICE: price}, *extra_signals]
        return self.orchestrator.process_trade_signals(signals)

    def run_shadow(
        self, symbol: str, price: float, extra_signals: list[dict[str, Any]]
    ) -> dict[str, Any]:
        result = self.analyze(symbol, price, extra_signals)
        self.virtual_trades.append(
            VirtualTrade(
                symbol=symbol,
                created_at=datetime.now(timezone.utc),
                intended_price=price,
                decision=result.get("DECISION", "FLAT"),
                confidence=float(result.get(FieldName.CONFIDENCE, 0)),
            )
        )
        return result

    def evaluate_shadow(self, symbol: str, observed_price: float) -> dict[str, Any]:
        candidates = [trade for trade in self.virtual_trades if trade.symbol == symbol]
        if not candidates:
            return {FieldName.STATUS: "no_data"}
        trade = candidates[-1]
        slippage_variance = abs(observed_price - trade.intended_price) / max(
            trade.intended_price, 1
        )
        age_seconds = (datetime.now(timezone.utc) - trade.created_at) / timedelta(seconds=1)
        profitable = (observed_price > trade.intended_price and trade.decision == "LONG") or (
            observed_price < trade.intended_price and trade.decision == "SHORT"
        )
        return {
            FieldName.STATUS: "evaluated",
            FieldName.SYMBOL: symbol,
            FieldName.DECISION: trade.decision,
            FieldName.SLIPPAGE_VARIANCE: round(slippage_variance, 6),
            FieldName.TRAJECTORY_SIMILARITY: 1.0 if profitable else 0.0,
            FieldName.CONFIDENCE_SCORE: round(
                (1 - min(slippage_variance, 1.0)) * trade.confidence, 4
            ),
            FieldName.AGE_SECONDS: int(age_seconds),
        }
