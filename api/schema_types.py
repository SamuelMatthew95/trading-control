"""
TypedDict definitions for inter-service communication.
"""

from typing import TypedDict, List, Dict, Any


class MarketTickEvent(TypedDict):
    symbol: str
    price: float
    bid: float
    ask: float
    volume: float
    timestamp: str
    source: str


class SignalEvent(TypedDict):
    strategy_name: str
    symbol: str
    side: str
    qty: float
    price: float
    composite_score: float
    factor_attribution: Dict[str, float]
    signal_data: Dict[str, Any]


class AgentSummary(TypedDict):
    action: str
    confidence: float
    primary_edge: str
    risk_factors: List[str]
    size_pct: float
    stop_atr_x: float
    rr_ratio: float
    latency_ms: int
    cost_usd: float
    trace_id: str
    fallback: bool


class TradePerformanceRecord(TypedDict):
    order_id: str
    symbol: str
    pnl: float
    holding_secs: int
    entry_price: float
    exit_price: float
    market_context: Dict[str, Any]
    factor_attribution: Dict[str, float]


class ReflectionPayload(TypedDict):
    winning_factors: List[str]
    losing_factors: List[str]
    regime_edge: str
    sizing_recommendation: str
    new_hypotheses: List[str]
    summary: str


class OrderEvent(TypedDict):
    strategy_name: str
    symbol: str
    side: str
    qty: float
    price: float
    order_type: str
    time_in_force: str


class ExecutionEvent(TypedDict):
    order_id: str
    symbol: str
    side: str
    qty: float
    fill_price: float
    status: str
    broker_order_id: str
    filled_at: str


class RiskAlertEvent(TypedDict):
    alert_type: str
    severity: str
    message: str
    symbol: str | None
    timestamp: str
    metadata: Dict[str, Any]


class LearningEvent(TypedDict):
    event_type: str
    data: Dict[str, Any]
    timestamp: str


class SystemMetricEvent(TypedDict):
    metric_name: str
    value: float | str
    unit: str | None
    timestamp: str
    tags: Dict[str, str] | None
