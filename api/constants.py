"""
Application constants and configuration values.

Use the StrEnum classes for all string comparisons in domain logic — no bare string literals.
"""

import sys
from typing import Final

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Backport of StrEnum for Python 3.10."""

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


class AgentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    WAITING = "WAITING"


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
    NEW_AGENT = "new_agent"


class HypothesisType(StrEnum):
    """Hypothesis types used by StrategyProposer to classify LLM reflection output."""

    PARAMETER = "parameter"
    RULE = "rule"
    NEW_AGENT = "new_agent"


class Grade(StrEnum):
    """Letter grades assigned by GradeAgent to measure agent performance."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class GradeType(StrEnum):
    """Valid values for the agent_grades.grade_type PostgreSQL Enum column.

    Must stay in sync with the DB Enum definition:
    Enum("accuracy", "efficiency", "safety", "overall", name="grade_type")
    """

    ACCURACY = "accuracy"
    EFFICIENCY = "efficiency"
    SAFETY = "safety"
    OVERALL = "overall"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LogType(StrEnum):
    REASONING_SUMMARY = "reasoning_summary"
    GRADE = "grade"
    REFLECTION = "reflection"
    PROPOSAL = "proposal"
    SIGNAL_GENERATED = "signal_generated"


# ---------------------------------------------------------------------------
# Agent identity constants — single source of truth for all agent names.
# These must match the Redis heartbeat keys written by each agent.
# ---------------------------------------------------------------------------

# Individual agent name constants
AGENT_SIGNAL: Final[str] = "SIGNAL_AGENT"
AGENT_REASONING: Final[str] = "REASONING_AGENT"
AGENT_EXECUTION: Final[str] = "EXECUTION_ENGINE"
AGENT_GRADE: Final[str] = "GRADE_AGENT"
AGENT_IC_UPDATER: Final[str] = "IC_UPDATER"
AGENT_REFLECTION: Final[str] = "REFLECTION_AGENT"
AGENT_STRATEGY_PROPOSER: Final[str] = "STRATEGY_PROPOSER"
AGENT_NOTIFICATION: Final[str] = "NOTIFICATION_AGENT"

AGENT_CHALLENGER: Final[str] = "CHALLENGER_AGENT"

# Ordered tuple used everywhere agent iteration is needed
ALL_AGENT_NAMES: Final[tuple[str, ...]] = (
    AGENT_SIGNAL,
    AGENT_REASONING,
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_REFLECTION,
    AGENT_STRATEGY_PROPOSER,
    AGENT_NOTIFICATION,
    AGENT_CHALLENGER,
)

# Source identifiers used in event payloads and DB source columns (lowercase by convention)
SOURCE_SIGNAL: Final[str] = "signal_generator"
SOURCE_REASONING: Final[str] = "reasoning_agent"
SOURCE_EXECUTION: Final[str] = "execution_engine"
SOURCE_GRADE: Final[str] = "grade_agent"
SOURCE_IC_UPDATER: Final[str] = "ic_updater"
SOURCE_REFLECTION: Final[str] = "reflection_agent"
SOURCE_STRATEGY_PROPOSER: Final[str] = "strategy_proposer"
SOURCE_NOTIFICATION: Final[str] = "notification_agent"
SOURCE_DB_HELPERS: Final[str] = "db_helpers"

# Redis heartbeat key for any agent: REDIS_AGENT_STATUS_KEY.format(name=AGENT_SIGNAL)
REDIS_AGENT_STATUS_KEY: Final[str] = "agent:status:{name}"

# How long an agent heartbeat key lives in Redis after the last write.
# Must be > AGENT_STALE_THRESHOLD_SECONDS so a slow-but-running agent
# never flips to "offline" before it first appears as "STALE".
AGENT_HEARTBEAT_TTL_SECONDS: Final[int] = 300  # 5 minutes

# If an agent's last_seen is older than this, mark it STALE on the dashboard.
# Keep well below AGENT_HEARTBEAT_TTL_SECONDS so "STALE" is reachable.
AGENT_STALE_THRESHOLD_SECONDS: Final[int] = 120  # 2 minutes

# ---------------------------------------------------------------------------
# Redis key patterns
REDIS_KEY_PAPER_CASH: Final[str] = "paper:cash"
REDIS_KEY_PAPER_POSITION: Final[str] = "paper:positions:{symbol}"
REDIS_KEY_PAPER_ORDER: Final[str] = "paper:order:{broker_order_id}"
REDIS_KEY_ORDER_LOCK: Final[str] = "order_lock:{symbol}"
REDIS_KEY_LLM_TOKENS: Final[str] = "llm:tokens:{date}"
REDIS_KEY_LLM_COST: Final[str] = "llm:cost:{date}"
REDIS_KEY_KILL_SWITCH: Final[str] = "kill_switch:active"
REDIS_KEY_KILL_SWITCH_UPDATED_AT: Final[str] = "kill_switch:updated_at"
REDIS_KEY_REFLECTION_COUNT: Final[str] = "reflection:trade_count"
REDIS_KEY_IC_WEIGHTS: Final[str] = "alpha:ic_weights"
REDIS_KEY_PRICES: Final[str] = "prices:{symbol}"  # use .format(symbol=symbol)
REDIS_KEY_WORKER_HEARTBEAT: Final[str] = "worker:heartbeat"
REDIS_KEY_DLQ: Final[str] = "dlq:{stream}"

# Stream names
STREAM_MARKET_TICKS: Final[str] = "market_ticks"
STREAM_MARKET_EVENTS: Final[str] = "market_events"
STREAM_SIGNALS: Final[str] = "signals"
STREAM_DECISIONS: Final[str] = "decisions"
STREAM_GRADED_DECISIONS: Final[str] = "graded_decisions"
STREAM_ORDERS: Final[str] = "orders"
STREAM_EXECUTIONS: Final[str] = "executions"
STREAM_TRADE_PERFORMANCE: Final[str] = "trade_performance"
STREAM_RISK_ALERTS: Final[str] = "risk_alerts"
STREAM_LEARNING_EVENTS: Final[str] = "learning_events"
STREAM_SYSTEM_METRICS: Final[str] = "system_metrics"
STREAM_AGENT_LOGS: Final[str] = "agent_logs"
STREAM_AGENT_GRADES: Final[str] = "agent_grades"
STREAM_FACTOR_IC_HISTORY: Final[str] = "factor_ic_history"
STREAM_REFLECTION_OUTPUTS: Final[str] = "reflection_outputs"
STREAM_PROPOSALS: Final[str] = "proposals"
STREAM_NOTIFICATIONS: Final[str] = "notifications"
STREAM_GITHUB_PRS: Final[str] = "github_prs"
STREAM_TRADE_LIFECYCLE: Final[str] = "trade_lifecycle"
STREAM_DLQ: Final[str] = "dlq"

# The four streams shown on the dashboard pipeline view
PIPELINE_STREAMS: Final[tuple[str, ...]] = (
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
)

# Default values
DEFAULT_PAPER_CASH: Final[float] = 100_000.0
ORDER_LOCK_TTL_SECONDS: Final[int] = 5
WORKER_HEARTBEAT_TTL_SECONDS: Final[int] = 120  # Background worker liveness key TTL
REDIS_PRICES_TTL_SECONDS: Final[int] = 30  # How long price cache entries live
REDIS_IC_WEIGHTS_TTL_SECONDS: Final[int] = 90_000  # ~25 hours; survives overnight
RECLAIM_MIN_IDLE_MS: Final[int] = 60_000
DLQ_MAX_RETRIES: Final[int] = 3
TICK_INTERVAL_SECONDS: Final[float] = 0.25
MAX_BACKOFF_SECONDS: Final[int] = 60
LARGE_ORDER_THRESHOLD: Final[float] = 10.0  # qty threshold for VWAP slicing (e.g. 10 BTC)
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
