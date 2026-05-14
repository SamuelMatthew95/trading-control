"""
Application constants and configuration values.

Use the StrEnum classes for all string comparisons in domain logic — no bare string literals.
"""

import sys
from typing import Final

from api.config import settings

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


class StorageBackend(StrEnum):
    """Storage backend types for runtime state management."""

    DATABASE = "db"
    MEMORY = "memory"


class RuntimeMode(StrEnum):
    """Runtime modes indicating system state."""

    CONNECTED = "connected"
    IN_MEMORY = "in_memory"
    IN_MEMORY_FALLBACK = "in_memory_fallback"


class HealthStatus(StrEnum):
    """Health status indicators for system components."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LLMCallResult(StrEnum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    ERROR = "error"


class LogType(StrEnum):
    REASONING_SUMMARY = "reasoning_summary"
    GRADE = "grade"
    REFLECTION = "reflection"
    PROPOSAL = "proposal"
    SIGNAL_GENERATED = "signal_generated"


class AgentLogType(StrEnum):
    """In-memory/event-bus log type labels (legacy uppercase contract)."""

    SIGNAL_GENERATED = "SIGNAL_GENERATED"


class FieldName(StrEnum):
    """Canonical payload / JSON field names used across services."""

    ACTION = "action"
    AGENT = "agent"
    APPLIED = "applied"
    APPLIED_AT = "applied_at"
    APPLIED_BY = "applied_by"
    AGENT_ID = "agent_id"
    AGENT_NAME = "agent_name"
    AGENT_RUN_ID = "agent_run_id"
    ALERT_TYPE = "alert_type"
    AVG_COST = "avg_cost"
    BIAS = "bias"
    BROKER_ORDER_ID = "broker_order_id"
    CHANGE = "change"
    COMMISSION = "commission"
    COMPOSITE_SCORE = "composite_score"
    CONFIDENCE = "confidence"
    CONTENT = "content"
    CONTENT_TYPE = "content_type"
    COST_USD = "cost_usd"
    CREATED_AT = "created_at"
    DATA = "data"
    DESCRIPTION = "description"
    DIRECTION = "direction"
    DECISION_TRACE_ID = "decision_trace_id"
    EMBEDDING = "embedding"
    ENTITY_ID = "entity_id"
    ENTITY_TYPE = "entity_type"
    ENTRY_PRICE = "entry_price"
    ENTRY_TIME = "entry_time"
    ERROR = "error"
    EVENT_COUNT = "event_count"
    EVENT_ID = "event_id"
    EVENT_TYPE = "event_type"
    EXCHANGE = "exchange"
    EXECUTION_TIME_MS = "execution_time_ms"
    EXECUTION_TRACE_ID = "execution_trace_id"
    EXIT_PRICE = "exit_price"
    EXIT_REASON = "exit_reason"
    EXIT_TIME = "exit_time"
    EXTERNAL_ORDER_ID = "external_order_id"
    FACTOR_ID = "factor_id"
    FACTOR_NAME = "factor_name"
    FALLBACK = "fallback"
    FEEDBACK = "feedback"
    FILL_PRICE = "fill_price"
    FILLED_AT = "filled_at"
    FILLED_PRICE = "filled_price"
    FILLED_QUANTITY = "filled_quantity"
    GRADE = "grade"
    GRADE_SCORE = "grade_score"
    GRADE_LABEL = "grade_label"
    GRADE_TYPE = "grade_type"
    GRADED_AT = "graded_at"
    GRADE_TRACE_ID = "grade_trace_id"
    HOLDING_PERIOD_MINUTES = "holding_period_minutes"
    HOUR_UTC = "hour_utc"
    IDEMPOTENCY_KEY = "idempotency_key"
    INPUT_DATA = "input_data"
    INSIGHTS = "insights"
    LAST_EVENT = "last_event"
    LAST_PRICE = "last_price"
    LAST_SEEN = "last_seen"
    LAST_SEEN_AT = "last_seen_at"
    LATENCY_MS = "latency_ms"
    LEVEL = "level"
    LOG_LEVEL = "log_level"
    LOG_TYPE = "log_type"
    MARKET_VALUE = "market_value"
    MAX_DRAWDOWN = "max_drawdown"
    MAX_RUNUP = "max_runup"
    MESSAGE = "message"
    METADATA = "metadata"
    METRICS = "metrics"
    MSG_ID = "msg_id"
    NEW_AVG_COST = "new_avg_cost"
    NEW_QUANTITY = "new_quantity"
    NOTIFICATION_ID = "notification_id"
    NOTIFICATION_TYPE = "notification_type"
    ORDER_ID = "order_id"
    ORDER_TYPE = "order_type"
    OUTCOME = "outcome"
    OUTPUT_DATA = "output_data"
    PAYLOAD = "payload"
    PCT = "pct"
    PERFORMANCE_METRICS = "performance_metrics"
    PNL = "pnl"
    PNL_PERCENT = "pnl_percent"
    PRICE = "price"
    PRIMARY_EDGE = "primary_edge"
    PROPOSAL_TYPE = "proposal_type"
    QTY = "qty"
    QUANTITY = "quantity"
    REASON = "reason"
    REASONING_SCORE = "reasoning_score"
    REFLECTION_TYPE = "reflection_type"
    REFLECTED_AT = "reflected_at"
    REFLECTION_TRACE_ID = "reflection_trace_id"
    REGIME = "regime"
    REQUIRES_APPROVAL = "requires_approval"
    RISK_FACTORS = "risk_factors"
    RR_RATIO = "rr_ratio"
    RUN_ID = "run_id"
    SCHEMA_VERSION = "schema_version"
    SCORE = "score"
    SIGNAL = "signal"
    SCORE_PCT = "score_pct"
    SESSION_ID = "session_id"
    SHARPE_RATIO = "sharpe_ratio"
    SIDE = "side"
    SIGNAL_CONFIDENCE = "signal_confidence"
    SIGNAL_TRACE_ID = "signal_trace_id"
    SIGNAL_TYPE = "signal_type"
    SIZE_PCT = "size_pct"
    SOURCE = "source"
    STATUS = "status"
    STEP_DATA = "step_data"
    STEP_NAME = "step_name"
    STOP_ATR_X = "stop_atr_x"
    STRATEGY_ID = "strategy_id"
    STRATEGY_NAME = "strategy_name"
    STRENGTH = "strength"
    SYMBOL = "symbol"
    TIMESTAMP = "timestamp"
    TRACE_ID = "trace_id"
    TRADE_ID = "trade_id"
    TRADE_TYPE = "trade_type"
    TS = "ts"
    TYPE = "type"
    HEARTBEAT_COUNT = "heartbeat_count"
    UNREALIZED_PNL = "unrealized_pnl"
    UPDATED_AT = "updated_at"
    WEIGHT_SCALE = "weight_scale"
    SUSPENDED_UNTIL = "suspended_until"
    # --- Learning pipeline fields ---
    AVG_RETURN = "avg_return"
    AVG_SCORE = "avg_score"
    CONSISTENCY = "consistency"
    ENTRY_QUALITY = "entry_quality"
    EXIT_QUALITY = "exit_quality"
    EXPECTED_IMPROVEMENT = "expected_improvement"
    MISTAKE_CLUSTERS = "mistake_clusters"
    MISTAKES = "mistakes"
    OVERALL_SCORE = "overall_score"
    PATTERNS = "patterns"
    RECOMMENDATIONS = "recommendations"
    REFLECTION_ID = "reflection_id"
    RISK_REWARD = "risk_reward"
    RULES = "rules"
    SCORE_TREND = "score_trend"
    SIGNAL_ALIGNMENT = "signal_alignment"
    STRENGTHS = "strengths"
    TIMING_SCORE = "timing_score"
    TRADE_EVAL_ID = "trade_eval_id"
    TRADES_ANALYZED = "trades_analyzed"
    WIN_RATE = "win_rate"


class StatusValue(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"


class EventType(StrEnum):
    SIGNAL_GENERATED = "signal.generated"
    DAILY_LOSS_LIMIT_BREACHED = "daily_loss_limit_breached"


class EntityType(StrEnum):
    SIGNAL = "signal"


class SignalType(StrEnum):
    STRONG_MOMENTUM = "STRONG_MOMENTUM"
    MOMENTUM = "MOMENTUM"
    PRICE_UPDATE = "PRICE_UPDATE"


class SignalStrength(StrEnum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class MarketDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


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
AGENT_PROPOSAL_APPLIER: Final[str] = "PROPOSAL_APPLIER"

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
    AGENT_PROPOSAL_APPLIER,
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
SOURCE_SUPERVISOR: Final[str] = "agent_supervisor"
SOURCE_PROPOSAL_APPLIER: Final[str] = "proposal_applier"

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
REDIS_KEY_ORDER_DEDUP: Final[str] = "order:dedup:{idempotency_key}"
ORDER_DEDUP_TTL_SECONDS: Final[int] = 86400  # 24h — covers any realistic replay window
REDIS_KEY_LLM_TOKENS: Final[str] = "llm:tokens:{date}"
REDIS_KEY_LLM_COST: Final[str] = "llm:cost:{date}"
# Dynamic call delay written by GradeAgent when rate-limiting is detected
REDIS_KEY_LLM_CALL_DELAY_MS: Final[str] = "llm:call_delay_ms"
REDIS_KEY_KILL_SWITCH: Final[str] = "kill_switch:active"
REDIS_KEY_KILL_SWITCH_UPDATED_AT: Final[str] = "kill_switch:updated_at"
REDIS_KEY_IC_WEIGHTS: Final[str] = "alpha:ic_weights"

# Learning-loop control plane — written by ProposalApplier, read by ExecutionEngine
# and ReasoningAgent so grade-driven proposals actually change trading behavior.
# trading_paused: "1" means refuse all new orders (mirror of kill switch, but
# triggered by Grade F retirement proposals rather than the manual button).
REDIS_KEY_TRADING_PAUSED: Final[str] = "learning:trading_paused"
REDIS_KEY_TRADING_PAUSED_REASON: Final[str] = "learning:trading_paused_reason"
# signal_weight_scale: float in (0, 1]. ReasoningAgent multiplies decision
# confidence by this value. Each Grade C reduction multiplies it by 0.7.
REDIS_KEY_SIGNAL_WEIGHT_SCALE: Final[str] = "learning:signal_weight_scale"
REDIS_KEY_AGENT_SUSPENDED: Final[str] = "learning:agent_suspended:{name}"
SIGNAL_WEIGHT_SCALE_MIN: Final[float] = (
    0.05  # never drop below 5% — full mute uses suspension instead
)
SIGNAL_WEIGHT_REDUCTION_FACTOR: Final[float] = 0.7  # one Grade C → 30% reduction
AGENT_SUSPEND_TTL_SECONDS: Final[int] = 86_400  # 24h cooling-off; auto-recover
LEARNING_CONTROL_TTL_SECONDS: Final[int] = 90_000  # ~25h, matches IC weights

REDIS_KEY_PRICES: Final[str] = "prices:{symbol}"  # use .format(symbol=symbol)
REDIS_KEY_WORKER_HEARTBEAT: Final[str] = "worker:heartbeat"
REDIS_PUBSUB_PRICE_UPDATES: Final[str] = "price_updates"  # pub/sub channel for SSE streaming
REDIS_KEY_DLQ: Final[str] = "dlq:{stream}"
REDIS_KEY_DLQ_RETRIES: Final[str] = "dlq:retries:{event_id}"
DLQ_RETRIES_TTL_SECONDS: Final[int] = 86400  # 1 day — DLQ retry counter lifespan
REDIS_KEY_NOTIFICATION_DEDUP: Final[str] = (
    "notif:dedup:{stream}:{event_type}:{side}:{symbol}:{trace}"
)
NOTIFICATION_DEDUP_TTL_SECONDS: Final[int] = 60  # dedup window — 1 minute
NOTIFICATIONS_STREAM_MAXLEN: Final[int] = 1000

# Redis-backed REST persistence — survives across requests in memory mode
REDIS_KEY_NOTIFICATIONS_RECENT: Final[str] = "notifications:recent"
REDIS_KEY_NOTIFICATIONS_READ: Final[str] = "notifications:read"
REDIS_KEY_DECISIONS_RECENT: Final[str] = "decisions:recent"
REDIS_KEY_LLM_METRICS: Final[str] = "llm:metrics"
REDIS_NOTIFICATIONS_MAX: Final[int] = 200
REDIS_DECISIONS_MAX: Final[int] = 500

# Stream names
STREAM_MARKET_TICKS: Final[str] = "market_ticks"
STREAM_MARKET_EVENTS: Final[str] = "market_events"
STREAM_SIGNALS: Final[str] = "signals"
STREAM_DECISIONS: Final[str] = "decisions"
STREAM_GRADED_DECISIONS: Final[str] = "graded_decisions"
STREAM_ORDERS: Final[str] = "orders"
STREAM_EXECUTIONS: Final[str] = "executions"
STREAM_TRADE_COMPLETED: Final[str] = "trade_completed"
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
IC_LOOKBACK_DAYS: Final[int] = int(settings.IC_LOOKBACK_DAYS)
SCORE_BUY_THRESHOLD: Final[float] = 0.6
SCORE_SELL_THRESHOLD: Final[float] = 0.4
REFLECTION_BONUS_PER_FACTOR: Final[float] = 0.05
REFLECTION_TRADE_THRESHOLD: Final[int] = int(settings.REFLECTION_TRADE_THRESHOLD)
LLM_MODEL: Final[str] = "claude-sonnet-4-20250514"

LLM_TIMEOUT_SECONDS: Final[int] = int(settings.LLM_TIMEOUT_SECONDS)
LLM_MAX_RETRIES: Final[int] = int(settings.LLM_MAX_RETRIES)
ANTHROPIC_DAILY_TOKEN_BUDGET: Final[int] = int(settings.ANTHROPIC_DAILY_TOKEN_BUDGET)
ANTHROPIC_COST_ALERT_USD: Final[float] = float(settings.ANTHROPIC_COST_ALERT_USD)
# Minimum delay between sequential LLM calls to avoid burst rate-limiting (ms)
LLM_CALL_DELAY_MS: Final[int] = 200
# GradeAgent bumps the call delay by this amount each time it detects rate-limiting
LLM_DELAY_ADJUSTMENT_STEP_MS: Final[int] = 250
# Hard cap on dynamic call delay
LLM_DELAY_MAX_MS: Final[int] = 2000
# How many rate-limits in the metrics window before GradeAgent acts
LLM_RATE_LIMIT_GRADE_THRESHOLD: Final[int] = 3
# Sliding window for LLM metrics (seconds) — how far back we look for success rate
LLM_METRICS_WINDOW_SECONDS: Final[int] = 300  # 5 minutes
# Max call records kept in the in-memory metrics ring buffer
LLM_METRICS_MAX_RECORDS: Final[int] = 200
MAX_CONSUMER_LAG_ALERT: Final[int] = 5000  # 5 seconds lag alert
PROCESS_TIMEOUT_SECONDS: Final[int] = 120  # Max time for a single message process() call
SUPERVISOR_CHECK_INTERVAL_SECONDS: Final[int] = 30  # AgentSupervisor health-check cadence
SUPERVISOR_MAX_RESTARTS_PER_WINDOW: Final[int] = 3  # Prevent restart thrashing per agent
SUPERVISOR_RESTART_WINDOW_SECONDS: Final[int] = 300  # 5-minute restart window

# Agentic pattern constants
# ReAct self-critique: only critique decisions above this confidence (controls LLM cost)
REACT_CRITIQUE_CONFIDENCE_THRESHOLD: Final[float] = 0.7
# Evaluator-Optimizer: trigger reflection refinement if fewer hypotheses than this
REFLECTION_MIN_HYPOTHESES: Final[int] = 2
# ExecutionEngine: minimum weighted score required to execute (signal*0.5 + reasoning*0.3 + perf*0.2)
EXECUTION_DECISION_THRESHOLD: Final[float] = 0.55

# Risk Guardian constants — position-level and portfolio-level risk limits
# Close position if unrealized loss exceeds this fraction of entry price
STOP_LOSS_PCT: Final[float] = 0.05
# Close position if unrealized gain exceeds this fraction of entry price
TAKE_PROFIT_PCT: Final[float] = 0.10
# Activate kill switch if today's realized PnL < -(portfolio_value * this)
DAILY_LOSS_LIMIT_PCT: Final[float] = 0.02
# How often (seconds) RiskGuardian scans open positions
RISK_CHECK_INTERVAL_SECONDS: Final[int] = 30

# LLM fallback modes
LLM_FALLBACK_MODE_SKIP_REASONING: Final[str] = "skip_reasoning"
LLM_FALLBACK_MODE_REJECT_SIGNAL: Final[str] = "reject_signal"
LLM_FALLBACK_MODE_USE_LAST_REFLECTION: Final[str] = "use_last_reflection"
LLM_FALLBACK_MODE: Final[str] = LLM_FALLBACK_MODE_SKIP_REASONING

# Symbol constants
SYMBOL_BTC_USD: Final[str] = "BTC/USD"
SYMBOL_ETH_USD: Final[str] = "ETH/USD"
SYMBOL_SOL_USD: Final[str] = "SOL/USD"
SYMBOL_SPY: Final[str] = "SPY"
SYMBOL_AAPL: Final[str] = "AAPL"
SYMBOL_NVDA: Final[str] = "NVDA"
SYMBOL_MSFT: Final[str] = "MSFT"
SYMBOL_GOOGL: Final[str] = "GOOGL"

# Valid symbols for trading
VALID_SYMBOLS: Final[set[str]] = {
    SYMBOL_BTC_USD,
    SYMBOL_ETH_USD,
    SYMBOL_SOL_USD,
    SYMBOL_SPY,
    SYMBOL_AAPL,
    SYMBOL_NVDA,
    SYMBOL_MSFT,
    SYMBOL_GOOGL,
}

# Initial symbol prices for paper mode
INITIAL_PRICES: Final[dict[str, float]] = {
    SYMBOL_BTC_USD: 67000.0,
    SYMBOL_ETH_USD: 3500.0,
    SYMBOL_SOL_USD: 145.0,
    SYMBOL_SPY: 510.0,
    SYMBOL_AAPL: 178.0,
    SYMBOL_NVDA: 875.0,
}
