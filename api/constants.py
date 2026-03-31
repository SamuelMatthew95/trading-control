"""
Application constants and configuration values.

Use the StrEnum classes for all string comparisons in domain logic — no bare string literals.
"""

from enum import StrEnum
from typing import Final

# ---------------------------------------------------------------------------
# Domain enums — import and compare against these, not bare strings
# ---------------------------------------------------------------------------


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class AgentAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    REJECT = "reject"
    FLAT = "flat"


# Actions that produce no order event
NO_ORDER_ACTIONS: frozenset[str] = frozenset(
    {AgentAction.REJECT, AgentAction.HOLD, AgentAction.FLAT}
)


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    URGENT = "URGENT"
    CRITICAL = "CRITICAL"


class ProposalType(StrEnum):
    PARAMETER_CHANGE = "parameter_change"
    CODE_CHANGE = "code_change"
    REGIME_ADJUSTMENT = "regime_adjustment"
    SIGNAL_WEIGHT_REDUCTION = "signal_weight_reduction"
    AGENT_SUSPENSION = "agent_suspension"
    AGENT_RETIREMENT = "agent_retirement"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LogType(StrEnum):
    REASONING_SUMMARY = "reasoning_summary"
    GRADE = "grade"
    REFLECTION = "reflection"
    PROPOSAL = "proposal"


# Redis key patterns
REDIS_KEY_PAPER_CASH: Final[str] = "paper:cash"
REDIS_KEY_PAPER_POSITION: Final[str] = "paper:positions:{symbol}"
REDIS_KEY_ORDER_LOCK: Final[str] = "order_lock:{symbol}"
REDIS_KEY_LLM_TOKENS: Final[str] = "llm:tokens:{date}"
REDIS_KEY_LLM_COST: Final[str] = "llm:cost:{date}"
REDIS_KEY_KILL_SWITCH: Final[str] = "kill_switch:active"
REDIS_KEY_REFLECTION_COUNT: Final[str] = "reflection:trade_count"
REDIS_KEY_IC_WEIGHTS: Final[str] = "alpha:ic_weights"
REDIS_KEY_DLQ: Final[str] = "dlq:{stream}"

# Stream names
STREAM_MARKET_TICKS: Final[str] = "market_ticks"
STREAM_SIGNALS: Final[str] = "signals"
STREAM_ORDERS: Final[str] = "orders"
STREAM_EXECUTIONS: Final[str] = "executions"
STREAM_RISK_ALERTS: Final[str] = "risk_alerts"
STREAM_LEARNING_EVENTS: Final[str] = "learning_events"
STREAM_SYSTEM_METRICS: Final[str] = "system_metrics"
STREAM_AGENT_LOGS: Final[str] = "agent_logs"

# Default values
DEFAULT_PAPER_CASH: Final[float] = 100_000.0
ORDER_LOCK_TTL_SECONDS: Final[int] = 5
RECLAIM_MIN_IDLE_MS: Final[int] = 60_000
DLQ_MAX_RETRIES: Final[int] = 3
TICK_INTERVAL_SECONDS: Final[float] = 0.25
MAX_BACKOFF_SECONDS: Final[int] = 60
LARGE_ORDER_THRESHOLD: Final[float] = 10_000.0
VECTOR_SEARCH_LIMIT: Final[int] = 5
STRATEGY_MAP_REFRESH_SECONDS: Final[int] = 300
IC_LOOKBACK_DAYS: Final[int] = 30
SCORE_BUY_THRESHOLD: Final[float] = 0.6
SCORE_SELL_THRESHOLD: Final[float] = 0.4
REFLECTION_BONUS_PER_FACTOR: Final[float] = 0.05
REFLECTION_TRADE_THRESHOLD: Final[int] = 50
LLM_MODEL: Final[str] = "claude-sonnet-4-20250514"
LLM_TIMEOUT_SECONDS: Final[int] = 30
LLM_MAX_RETRIES: Final[int] = 3
ANTHROPIC_DAILY_TOKEN_BUDGET: Final[int] = 1_000_000  # $1M daily
ANTHROPIC_COST_ALERT_USD: Final[float] = 500.0  # Alert at $500
MAX_CONSUMER_LAG_ALERT: Final[int] = 5000  # 5 seconds lag alert

# LLM fallback modes
LLM_FALLBACK_MODE_SKIP_REASONING: Final[str] = "skip_reasoning"
LLM_FALLBACK_MODE_REJECT_SIGNAL: Final[str] = "reject_signal"
LLM_FALLBACK_MODE_USE_LAST_REFLECTION: Final[str] = "use_last_reflection"
LLM_FALLBACK_MODE: Final[str] = LLM_FALLBACK_MODE_SKIP_REASONING

# Valid symbols for trading
VALID_SYMBOLS: Final[set[str]] = {
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "SPY",
    "AAPL",
    "NVDA",
    "MSFT",
    "GOOGL",
}

# Initial symbol prices for paper mode
INITIAL_PRICES: Final[dict[str, float]] = {
    "BTC/USD": 67000.0,
    "ETH/USD": 3500.0,
    "SOL/USD": 145.0,
    "SPY": 510.0,
    "AAPL": 178.0,
    "NVDA": 875.0,
}
