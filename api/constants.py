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
    UNKNOWN = "UNKNOWN"


class Source(StrEnum):
    """Origin of a data payload — DB record, in-memory store, Redis, or fallback."""

    DB = "db"
    IN_MEMORY = "in_memory"
    REDIS = "redis"
    FALLBACK = "fallback"


# Default payload values — explicit sentinels so missing data stays visible
# instead of silently collapsing into an empty string.
EMPTY_STRING: Final[str] = ""
UNKNOWN_VALUE: Final[str] = "unknown"
DEFAULT_TRACE_ID: Final[str] = "unknown-trace"
DEFAULT_AGENT_ID: Final[str] = "unknown-agent"
DEFAULT_MSG_ID: Final[str] = "unknown-msg"


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


class LifecyclePhase(StrEnum):
    """Agent/consumer lifecycle phases recorded via write_agent_lifecycle_event."""

    STARTED = "started"
    STOPPED = "stopped"
    CRASHED = "crashed"
    RECOVERED = "recovered"


class FieldName(StrEnum):
    """Canonical payload / JSON field names used across services."""

    ACCURACY = "accuracy"
    ACKNOWLEDGED = "acknowledged"
    ACTION = "action"
    ACTIVE = "active"
    ACTIVE_AGENTS = "active_agents"
    ACTIVE_AGENT_COUNT = "active_agent_count"
    ACTIVE_ALERTS = "active_alerts"
    ACTIVE_CONNECTIONS = "active_connections"
    ACTIVE_COUNT = "active_count"
    ACTIVE_POSITION = "active_position"
    ACTIVE_POSITIONS = "active_positions"
    ACTIVE_WS_CONNECTIONS = "active_ws_connections"
    AGENT = "agent"
    AGENTS = "agents"
    AGENTS_ACTIVE = "agents_active"
    AGENT_GRADES = "agent_grades"
    AGENT_ID = "agent_id"
    AGENT_LOGS = "agent_logs"
    AGENT_METRICS = "agent_metrics"
    AGENT_NAME = "agent_name"
    AGENT_PULSE = "agent_pulse"
    AGENT_RUNS = "agent_runs"
    AGENT_RUN_ID = "agent_run_id"
    AGENT_STATUS = "agent_status"
    AGENT_STATUSES = "agent_statuses"
    AGENT_TYPE = "agent_type"
    AGE_SECONDS = "age_seconds"
    AGREEMENT_RATIO = "agreement_ratio"
    ALERTS = "alerts"
    ALERT_LEVEL = "alert_level"
    ALERT_TYPE = "alert_type"
    ALL_HYPOTHESES = "all_hypotheses"
    ANTHROPIC = "anthropic"
    API_VERSION = "api_version"
    APPLIED = "applied"
    APPLIED_AT = "applied_at"
    APPLIED_BY = "applied_by"
    APPLIED_DECISION_KEYS = "applied_decision_keys"
    APPROVED = "approved"
    APPROXIMATE = "approximate"
    ASK = "ask"
    ASSET = "asset"
    ASSET_PRICE = "asset_price"
    AT = "at"
    ATR = "atr"
    AUTO_APPLIED = "auto_applied"
    AVG_COST = "avg_cost"
    AVG_ENTRY_PRICE = "avg_entry_price"
    AVG_LATENCY_MS = "avg_latency_ms"
    AVG_LOSS = "avg_loss"
    AVG_PNL = "avg_pnl"
    AVG_RETURN = "avg_return"
    AVG_SCORE = "avg_score"
    AVG_SCORE_PCT = "avg_score_pct"
    AVG_WIN = "avg_win"
    BACKLOG = "backlog"
    BADGES = "badges"
    BAD_RISK_REWARD = "bad_risk_reward"
    BEST_HOURS = "best_hours"
    BEST_TRADE = "best_trade"
    BIAS = "bias"
    BID = "bid"
    BLOCKED_TOOLS = "blocked_tools"
    BLOCKS = "blocks"
    BODY = "body"
    BOTS = "bots"
    BOT_STATE = "bot_state"
    BROKER_ORDER_ID = "broker_order_id"
    BROKER_STATUS = "broker_status"
    BUYING_POWER = "buying_power"
    BUYS = "buys"
    BY_SEVERITY = "by_severity"
    BY_STREAM = "by_stream"
    CACHED_UNTIL_EPOCH = "cached_until_epoch"
    CASH = "cash"
    CHALLENGERS = "challengers"
    CHALLENGER_CONFIG = "challenger_config"
    CHALLENGER_ID = "challenger_id"
    CHANGE = "change"
    CHANGE_AMT = "change_amt"
    CHANGE_PCT = "change_pct"
    CHECK_TIME = "check_time"
    CIRCUIT_BREAKER_ACTIVE = "circuit_breaker_active"
    CLEARED = "cleared"
    CLOSED_TRADES = "closed_trades"
    COMMISSION = "commission"
    COMPOSITE_IC = "composite_ic"
    COMPOSITE_SCORE = "composite_score"
    COMPUTED_AT = "computed_at"
    CONCERNS = "concerns"
    CONFIDENCE = "confidence"
    CONFIDENCE_SCORE = "confidence_score"
    CONFIG = "config"
    CONFIG_SOURCE = "config_source"
    CONNECTION = "connection"
    CONSECUTIVE_LOW_GRADES = "consecutive_low_grades"
    CONSENSUS = "consensus"
    CONSISTENCY = "consistency"
    CONSUMER = "consumer"
    CONTENT = "content"
    CONTENT_TYPE = "content_type"
    CONTEXT = "context"
    CONTEXT_DUMP = "context_dump"
    CONTROL_PLANE = "control_plane"
    COST_EFFICIENCY = "cost_efficiency"
    COST_NORMALIZED = "cost_normalized"
    COST_USD = "cost_usd"
    COUNT = "count"
    COUNTS = "counts"
    CREATED_AT = "created_at"
    CRITICAL = "critical"
    CRITICAL_ALERTS = "critical_alerts"
    CRYPTO = "crypto"
    CURRENT_PRICE = "current_price"
    CURRENT_REGIME = "current_regime"
    CURRENT_WEIGHTS = "current_weights"
    CUTOFF = "cutoff"
    DAILY_CALLS = "daily_calls"
    DAILY_PNL = "daily_pnl"
    DATA = "data"
    DATABASE = "database"
    DATABASE_CONNECTED = "database_connected"
    DATABASE_HEALTH = "database_health"
    DATABASE_MODE = "database_mode"
    DATA_FRESHNESS_MS = "data_freshness_ms"
    DATA_KEYS = "data_keys"
    DATA_METRICS = "data_metrics"
    DATE = "date"
    DAY = "day"
    DB_AVAILABLE = "db_available"
    DB_HEALTH = "db_health"
    DB_POOL_STATUS = "db_pool_status"
    DB_SCHEMA_VERSION = "db_schema_version"
    DB_STATUS = "db_status"
    DEADLINE = "deadline"
    DECISION = "decision"
    DECISIONS = "decisions"
    DECISIONS_COUNT = "decisions_count"
    DECISIONS_EVALUATED = "decisions_evaluated"
    DECISION_STREAM_LENGTH = "decision_stream_length"
    DECISION_TRACE_ID = "decision_trace_id"
    DEDUPLICATED = "deduplicated"
    DEGRADED_MODE = "degraded_mode"
    DEGRADED_REASON = "degraded_reason"
    DELIVERY = "delivery"
    DESCRIPTION = "description"
    DETAILS = "details"
    DIRECTION = "direction"
    DISCREPANCY = "discrepancy"
    DISPLAY = "display"
    DLQ_COUNT = "dlq_count"
    DRAWDOWN = "drawdown"
    EE_DECISIONS_EVALUATED = "ee_decisions_evaluated"
    EE_EVENT_COUNT = "ee_event_count"
    EE_LAST_STATUS = "ee_last_status"
    EFFECTIVE_DELAY_MS = "effective_delay_ms"
    ELAPSED = "elapsed"
    EMAIL = "email"
    EMBEDDING = "embedding"
    EMPTY_REASON = "empty_reason"
    ENTITY_ID = "entity_id"
    ENTITY_TYPE = "entity_type"
    ENTRY = "entry"
    ENTRY_PRICE = "entry_price"
    ENTRY_QUALITY = "entry_quality"
    ENTRY_TIME = "entry_time"
    ENVIRONMENT = "environment"
    EQUITY_CURVE = "equity_curve"
    EQUITY_CURVE_POINTS = "equity_curve_points"
    EQUITY_POINTS = "equity_points"
    ERROR = "error"
    ERRORS = "errors"
    ERROR_COUNT = "error_count"
    ERROR_RATE = "error_rate"
    EVENT = "event"
    EVENTS = "events"
    EVENT_COUNT = "event_count"
    EVENT_ID = "event_id"
    EVENT_TYPE = "event_type"
    EXCHANGE = "exchange"
    EXECUTED = "executed"
    EXECUTED_AT = "executed_at"
    EXECUTION_TIME_MS = "execution_time_ms"
    EXECUTION_TRACE_ID = "execution_trace_id"
    EXEC_STATUS = "exec_status"
    EXIT_PRICE = "exit_price"
    EXIT_QUALITY = "exit_quality"
    EXIT_REASON = "exit_reason"
    EXIT_TIME = "exit_time"
    EXPECTED_IMPROVEMENT = "expected_improvement"
    EXPECTED_QUANTITY = "expected_quantity"
    EXPIRES_AT = "expires_at"
    EXTERNAL_ORDER_ID = "external_order_id"
    FACTOR = "factor"
    FACTOR_ID = "factor_id"
    FACTOR_NAME = "factor_name"
    FACTS = "facts"
    FAILED = "failed"
    FALLBACK = "fallback"
    FALLBACK_REASON = "fallback_reason"
    FEEDBACK = "feedback"
    FEEDBACK_JOBS_FAILED = "feedback_jobs_failed"
    FEEDBACK_JOBS_PENDING = "feedback_jobs_pending"
    FIELDS = "fields"
    FILLED = "filled"
    FILLED_AT = "filled_at"
    FILLED_AVG_PRICE = "filled_avg_price"
    FILLED_ORDERS_LAST_HOUR = "filled_orders_last_hour"
    FILLED_PRICE = "filled_price"
    FILLED_QTY = "filled_qty"
    FILLED_QUANTITY = "filled_quantity"
    FILLS = "fills"
    FILLS_ANALYZED = "fills_analyzed"
    FILLS_GRADED = "fills_graded"
    FILL_ID = "fill_id"
    FILL_PRICE = "fill_price"
    FILL_RATE_PERCENT = "fill_rate_percent"
    FILL_TIME = "fill_time"
    FIVE_MIN_AGO = "five_min_ago"
    FLAGS = "flags"
    FLAT_TRADES = "flat_trades"
    FREQUENCY = "frequency"
    FRESH_SYMBOLS = "fresh_symbols"
    GEMINI = "gemini"
    GRADE = "grade"
    GRADED_AT = "graded_at"
    GRADED_DECISIONS = "graded_decisions"
    GRADES = "grades"
    GRADE_ADJUSTED_DELAY = "grade_adjusted_delay"
    GRADE_EVERY = "grade_every"
    GRADE_HISTORY = "grade_history"
    GRADE_LABEL = "grade_label"
    GRADE_PAYLOAD = "grade_payload"
    GRADE_SCORE = "grade_score"
    GRADE_TRACE_ID = "grade_trace_id"
    GRADE_TREND = "grade_trend"
    GRADE_TYPE = "grade_type"
    GROQ = "groq"
    GROUNDING = "grounding"
    GROUPS = "groups"
    GUARD_HITS = "guard_hits"
    HAS_DATA = "has_data"
    HEAD_ID = "head_id"
    HEALTH = "health"
    HEALTH_SCORE = "health_score"
    HEARTBEAT_AGE = "heartbeat_age"
    HEARTBEAT_COUNT = "heartbeat_count"
    HEARTBEAT_STATUS = "heartbeat_status"
    HISTORY = "history"
    HOLDING_PERIOD_MINUTES = "holding_period_minutes"
    HOLDS = "holds"
    HOUR_UTC = "hour_utc"
    HYDRATION = "hydration"
    HYDRATION_STATUS = "hydration_status"
    HYPOTHESES = "hypotheses"
    HYPOTHESIS = "hypothesis"
    HYPOTHESIS_COUNT = "hypothesis_count"
    HYPOTHESIS_TYPE = "hypothesis_type"
    IC = "ic"
    ICON = "icon"
    IC_NORMALIZED = "ic_normalized"
    IC_SCORE = "ic_score"
    IC_WEIGHTS = "ic_weights"
    ID = "id"
    IDEMPOTENCY_KEY = "idempotency_key"
    IDEM_KEY = "idem_key"
    IDLE_CONNECTIONS = "idle_connections"
    IMPACT = "impact"
    IMPLEMENTATION = "implementation"
    INFO = "info"
    INPUT = "input"
    INPUT_DATA = "input_data"
    INSIGHTS = "insights"
    INSTANCES = "instances"
    INSTANCE_ID = "instance_id"
    INSTANCE_KEY = "instance_key"
    INSTANCE_STATUS = "instance_status"
    IN_AGENT_LOGS = "in_agent_logs"
    IN_AGENT_RUNS = "in_agent_runs"
    IN_TRADE_LIFECYCLE = "in_trade_lifecycle"
    IS_STALE = "is_stale"
    ITEMS = "items"
    ITERATION = "iteration"
    JOBS_PROCESSED = "jobs_processed"
    JOB_ID = "job_id"
    JUSTIFIED = "justified"
    KEY = "key"
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    KIND = "kind"
    LABEL = "label"
    LAG = "lag"
    LAG_MS = "lag_ms"
    LAG_SECONDS = "lag_seconds"
    LAST_ACTION = "last_action"
    LAST_ACTION_TIME = "last_action_time"
    LAST_CHECKED = "last_checked"
    LAST_DECISION = "last_decision"
    LAST_ERROR = "last_error"
    LAST_EVENT = "last_event"
    LAST_GRADE_SCORE = "last_grade_score"
    LAST_HOUR = "last_hour"
    LAST_LATENCY_MS = "last_latency_ms"
    LAST_LEVEL = "last_level"
    LAST_PRICE = "last_price"
    LAST_PROCESSED_AT = "last_processed_at"
    LAST_PROCESSED_ID = "last_processed_id"
    LAST_RUN = "last_run"
    LAST_SEEN = "last_seen"
    LAST_SEEN_AT = "last_seen_at"
    LAST_SIGNAL = "last_signal"
    LAST_STEP = "last_step"
    LAST_SUCCESS_AT = "last_success_at"
    LAST_TASK = "last_task"
    LAST_TIMESTAMP = "last_timestamp"
    LAST_TRACE_ID = "last_trace_id"
    LAST_UPDATE = "last_update"
    LATENCY_MS = "latency_ms"
    LATENCY_SCORE = "latency_score"
    LATEST_CLOSED_TRADE = "latest_closed_trade"
    LATEST_DECISION = "latest_decision"
    LATEST_GRADE = "latest_grade"
    LATEST_NOTIFICATION = "latest_notification"
    LATEST_OPEN_POSITION = "latest_open_position"
    LATE_ENTRY = "late_entry"
    LEARNING_EVENTS = "learning_events"
    LEDGER_SOURCE = "ledger_source"
    LENGTH = "length"
    LEVEL = "level"
    LIFECYCLE = "lifecycle"
    LIFECYCLE_EVENT = "lifecycle_event"
    LIMIT = "limit"
    LISTS = "lists"
    LLM_AVAILABLE = "llm_available"
    LLM_EFFECTIVE_DELAY_MS = "llm_effective_delay_ms"
    LLM_HEALTH_SCORE = "llm_health_score"
    LLM_PROVIDER = "llm_provider"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_SUCCEEDED = "llm_succeeded"
    LLM_SUCCESS_RATE_PCT = "llm_success_rate_pct"
    LLM_TIMEOUT_COUNT = "llm_timeout_count"
    LOGS = "logs"
    LOG_LEVEL = "log_level"
    LOG_TYPE = "log_type"
    LONG_TRADES = "long_trades"
    LOOP_EVENT = "loop_event"
    LOSING_FACTORS = "losing_factors"
    LOSING_TRADES = "losing_trades"
    LOSSES = "losses"
    LOSS_ATTRIBUTION = "loss_attribution"
    MARKET_EVENTS = "market_events"
    MARKET_VALUE = "market_value"
    MASKED_URL = "masked_url"
    MAXLEN = "maxlen"
    MAX_DRAWDOWN = "max_drawdown"
    MAX_FILLS = "max_fills"
    MAX_RETRIES = "max_retries"
    MAX_RUNUP = "max_runup"
    MAX_TOKENS = "max_tokens"
    MESSAGE = "message"
    MESSAGES = "messages"
    MESSAGES_SENT = "messages_sent"
    MESSAGE_COUNT_5MIN = "message_count_5min"
    MESSAGE_ID = "message_id"
    META = "meta"
    METADATA = "metadata"
    METADATA_ = "metadata_"
    METRICS = "metrics"
    METRIC_NAME = "metric_name"
    METRIC_UNIT = "metric_unit"
    METRIC_VALUE = "metric_value"
    MISALIGNED_SIGNAL = "misaligned_signal"
    MISTAKES = "mistakes"
    MISTAKE_CLUSTERS = "mistake_clusters"
    MODE = "mode"
    MODEL = "model"
    MODEL_VAR = "model_var"
    MOMENTUM = "momentum"
    MOMENTUM_PCT = "momentum_pct"
    MONITORING_ACTIVE = "monitoring_active"
    MSG_ID = "msg_id"
    N = "n"
    NAME = "name"
    NEW_AVG_COST = "new_avg_cost"
    NEW_QUANTITY = "new_quantity"
    NEW_VALUE = "new_value"
    NEXT_TIMEFRAME = "next_timeframe"
    NORM_RETURN = "norm_return"
    NOTE = "note"
    NOTIFICATIONS = "notifications"
    NOTIFICATIONS_COUNT = "notifications_count"
    NOTIFICATION_ID = "notification_id"
    NOTIFICATION_SUMMARY = "notification_summary"
    NOTIFICATION_TYPE = "notification_type"
    NOTIONAL = "notional"
    OBSERVED_MSG_ID = "observed_msg_id"
    OFFSET = "offset"
    OK = "ok"
    OLDEST_PENDING_AGE_SECONDS = "oldest_pending_age_seconds"
    OLDEST_PENDING_SCORE_AGE_SECONDS = "oldest_pending_score_age_seconds"
    OPEN = "open"
    OPENAI = "openai"
    OPEN_POSITIONS = "open_positions"
    ORCHESTRATOR = "orchestrator"
    ORDERS = "orders"
    ORDERS_LAST_HOUR = "orders_last_hour"
    ORDER_ID = "order_id"
    ORDER_TYPE = "order_type"
    ORIGINAL_ID = "original_id"
    ORIGINAL_STREAM = "original_stream"
    OUTCOME = "outcome"
    OUTPUT = "output"
    OUTPUT_DATA = "output_data"
    OVERALL_SCORE = "overall_score"
    OVERALL_STATUS = "overall_status"
    P95_LATENCY_MS = "p95_latency_ms"
    PARAMETER = "parameter"
    PATTERNS = "patterns"
    PAYLOAD = "payload"
    PCT = "pct"
    PENDING = "pending"
    PENDING_ORDERS_LAST_HOUR = "pending_orders_last_hour"
    PERFORMANCE = "performance"
    PERFORMANCE_METRICS = "performance_metrics"
    PERSISTED_EVENTS = "persisted_events"
    PERSISTED_EVENT_COUNT = "persisted_event_count"
    PERSISTED_LOGS = "persisted_logs"
    PERSISTENCE_MODE = "persistence_mode"
    PERSISTENCE_SOURCE = "persistence_source"
    PER_STREAM = "per_stream"
    PING = "ping"
    PIPELINE_HEALTH = "pipeline_health"
    PIPELINE_RUNNING = "pipeline_running"
    PNL = "pnl"
    PNL_PERCENT = "pnl_percent"
    POOL = "pool"
    POOL_NAME = "pool_name"
    POOL_UTILIZATION_PERCENT = "pool_utilization_percent"
    POOR_EXIT = "poor_exit"
    PORTFOLIO = "portfolio"
    PORTFOLIO_STATE = "portfolio_state"
    PORTFOLIO_VALUE = "portfolio_value"
    POSITIONS = "positions"
    POSITION_EXISTS = "position_exists"
    POSITION_ID = "position_id"
    POSITION_QUANTITY = "position_quantity"
    POSITION_SIZE = "position_size"
    POSTGRES = "postgres"
    PREMATURE_ENTRY = "premature_entry"
    PREVIEW = "preview"
    PREVIOUS_SCALE = "previous_scale"
    PREVIOUS_VALUE = "previous_value"
    PRICE = "price"
    PRICES = "prices"
    PRICE_HINT = "price_hint"
    PRIMARY_EDGE = "primary_edge"
    PROCESSED_COUNT = "processed_count"
    PROCESSED_EVENTS_LAST_HOUR = "processed_events_last_hour"
    PROCESSING_ATTEMPT = "processing_attempt"
    PROPOSALS = "proposals"
    PROPOSAL_TYPE = "proposal_type"
    PROVIDER = "provider"
    QTY = "qty"
    QUANTITY = "quantity"
    QUOTA = "quota"
    RANKED_INDICES = "ranked_indices"
    RATE = "rate"
    RATELIMIT = "ratelimit"
    RATE_LIMIT = "rate_limit"
    RATE_LIMITED_COUNT = "rate_limited_count"
    RATE_LIMITS = "rate_limits"
    RATIO = "ratio"
    RAW_DATA = "raw_data"
    READ = "read"
    REALIZED_PNL = "realized_pnl"
    REALTIME_EVENT_COUNT = "realtime_event_count"
    REASON = "reason"
    REASONING = "reasoning"
    REASONING_SCORE = "reasoning_score"
    REASONING_SUMMARY = "reasoning_summary"
    RECENT = "recent"
    RECENT_ACTIVITY = "recent_activity"
    RECENT_EVENTS = "recent_events"
    RECENT_FAILURES = "recent_failures"
    RECENT_FILLS = "recent_fills"
    RECENT_GRADES = "recent_grades"
    RECENT_IC_CHANGES = "recent_ic_changes"
    RECENT_PROPOSALS = "recent_proposals"
    RECENT_RESULTS = "recent_results"
    RECOMMENDATION = "recommendation"
    RECOMMENDATIONS = "recommendations"
    RECOMMENDED_ACTION = "recommended_action"
    RECOMMENDED_CONFIDENCE = "recommended_confidence"
    REDIS = "redis"
    REDIS_DECISIONS_APPLIED = "redis_decisions_applied"
    REDIS_DECISIONS_SEEN = "redis_decisions_seen"
    REDIS_HYDRATION_STATUS = "redis_hydration_status"
    REDIS_ID = "redis_id"
    REDIS_METRICS = "redis_metrics"
    REDIS_NOTIFICATIONS_APPLIED = "redis_notifications_applied"
    REDIS_NOTIFICATIONS_SEEN = "redis_notifications_seen"
    REDUCTION_PCT = "reduction_pct"
    REFLECTED_AT = "reflected_at"
    REFLECTION = "reflection"
    REFLECTIONS = "reflections"
    REFLECTION_ID = "reflection_id"
    REFLECTION_TRACE_ID = "reflection_trace_id"
    REFLECTION_TYPE = "reflection_type"
    REGIME = "regime"
    REGIME_CONTEXT = "regime_context"
    REGIME_EDGE = "regime_edge"
    REPLAYED = "replayed"
    REQUEST_ID = "request_id"
    REQUIRES_APPROVAL = "requires_approval"
    RESOLVED = "resolved"
    RESULT = "result"
    RETIRED_AT = "retired_at"
    RETIRED_COUNT = "retired_count"
    RETRIES = "retries"
    RETRIEVED_CONTEXT = "retrieved_context"
    RETRY_BUCKETS = "retry_buckets"
    RETRY_COUNT = "retry_count"
    RETURN_PCT = "return_pct"
    RISK = "risk"
    RISK_ALERTS = "risk_alerts"
    RISK_ASSESSMENT = "risk_assessment"
    RISK_EXPOSURE = "risk_exposure"
    RISK_FACTORS = "risk_factors"
    RISK_REWARD = "risk_reward"
    RISK_SCORE = "risk_score"
    RISK_STATE = "risk_state"
    ROLE = "role"
    RR_RATIO = "rr_ratio"
    RULES = "rules"
    RUN = "run"
    RUNNING = "running"
    RUNS = "runs"
    RUNTIME_DB_HEALTH = "runtime_db_health"
    RUNTIME_STORE = "runtime_store"
    RUN_ID = "run_id"
    RUN_TYPE = "run_type"
    SCHEMA_VERSION = "schema_version"
    SCOPE = "scope"
    SCORE = "score"
    SCORE_PCT = "score_pct"
    SCORE_TREND = "score_trend"
    SCORING = "scoring"
    SCORING_FAILED = "scoring_failed"
    SCORING_PENDING = "scoring_pending"
    SECONDS_AGO = "seconds_ago"
    SELLS = "sells"
    SESSION_ID = "session_id"
    SEVERITY = "severity"
    SEVERITY_COUNTS = "severity_counts"
    SHARPE_RATIO = "sharpe_ratio"
    SHORT_TRADES = "short_trades"
    SID = "sid"
    SIDE = "side"
    SIGNAL = "signal"
    SIGNALS = "signals"
    SIGNAL_ALIGNMENT = "signal_alignment"
    SIGNAL_CONFIDENCE = "signal_confidence"
    SIGNAL_DATA = "signal_data"
    SIGNAL_EVENTS = "signal_events"
    SIGNAL_ID = "signal_id"
    SIGNAL_STREAM_LENGTH = "signal_stream_length"
    SIGNAL_STRENGTH = "signal_strength"
    SIGNAL_TRACE_ID = "signal_trace_id"
    SIGNAL_TYPE = "signal_type"
    SIGNAL_WEIGHT_SCALE = "signal_weight_scale"
    SIM = "sim"
    SIMILARITY = "similarity"
    SIMILAR_TRADES = "similar_trades"
    SIZE_MULTIPLIER = "size_multiplier"
    SIZE_PCT = "size_pct"
    SIZING = "sizing"
    SKIPPED_BY_MEMORY_GUARD = "skipped_by_memory_guard"
    SLACK = "slack"
    SLIPPAGE_VARIANCE = "slippage_variance"
    SNIPPET = "snippet"
    SOURCE = "source"
    STAGE = "stage"
    STAGES = "stages"
    STALE_SYMBOLS = "stale_symbols"
    STARTED_AT = "started_at"
    STATE = "state"
    STATUS = "status"
    STATUS_LABEL = "status_label"
    STEP_DATA = "step_data"
    STEP_NAME = "step_name"
    STOCKS = "stocks"
    STOP = "stop"
    STOP_ATR_X = "stop_atr_x"
    STOP_PRICE = "stop_price"
    STORE_TYPE = "store_type"
    STRATEGIES = "strategies"
    STRATEGY = "strategy"
    STRATEGY_ID = "strategy_id"
    STRATEGY_NAME = "strategy_name"
    STRATEGY_PROPOSER = "strategy_proposer"
    STREAM = "stream"
    STREAMS = "streams"
    STREAMS_STATUS = "streams_status"
    STREAM_COUNT = "stream_count"
    STREAM_COUNTS = "stream_counts"
    STREAM_HEALTH = "stream_health"
    STREAM_LAG = "stream_lag"
    STREAM_SOURCE = "stream_source"
    STRENGTH = "strength"
    STRENGTHS = "strengths"
    STRONG_HYPOTHESES = "strong_hypotheses"
    SUBJECT = "subject"
    SUBTITLE = "subtitle"
    SUCCESS = "success"
    SUCCESSES = "successes"
    SUCCESS_COUNT = "success_count"
    SUCCESS_RATE = "success_rate"
    SUCCESS_RATE_PCT = "success_rate_pct"
    SUGGESTED_CHANNELS = "suggested_channels"
    SUMMARY = "summary"
    SUMMARY_VERSION = "summary_version"
    SUSPENDED_AGENTS = "suspended_agents"
    SUSPENDED_UNTIL = "suspended_until"
    SYMBOL = "symbol"
    SYNCED_COUNT = "synced_count"
    SYNC_STATUS = "sync_status"
    SYSTEM = "system"
    SYSTEM_DIRECTIVE = "system_directive"
    SYSTEM_HEALTH = "system_health"
    SYSTEM_LOAD = "system_load"
    SYSTEM_METRICS = "system_metrics"
    T = "t"
    TAGS = "tags"
    TAKE_PROFIT_PRICE = "take_profit_price"
    TARGET = "target"
    TARGET_AGENT = "target_agent"
    TASK_ID = "task_id"
    TASK_METRICS = "task_metrics"
    TASK_STATE = "task_state"
    TELEGRAM = "telegram"
    TELEMETRY = "telemetry"
    TEMPERATURE = "temperature"
    TEMPLATE = "template"
    TEXT = "text"
    THRESHOLD = "threshold"
    TID = "tid"
    TIMEFRAME = "timeframe"
    TIMEOUT = "timeout"
    TIMEOUTS = "timeouts"
    TIMEOUT_COUNT = "timeout_count"
    TIMESTAMP = "timestamp"
    TIME_IN_FORCE = "time_in_force"
    TIME_OF_DAY_PATTERNS = "time_of_day_patterns"
    TIMING_SCORE = "timing_score"
    TITLE = "title"
    TODAY = "today"
    TODAY_PNL = "today_pnl"
    TOKENS_USED = "tokens_used"
    TONE = "tone"
    TOOLS = "tools"
    TOTAL = "total"
    TOTAL_ACTIVE = "total_active"
    TOTAL_BOTS = "total_bots"
    TOTAL_CALLS = "total_calls"
    TOTAL_CALLS_LIFETIME = "total_calls_lifetime"
    TOTAL_CONNECTIONS = "total_connections"
    TOTAL_ERRORS = "total_errors"
    TOTAL_FILLS = "total_fills"
    TOTAL_IN_WINDOW = "total_in_window"
    TOTAL_ORDERS = "total_orders"
    TOTAL_ORDERS_LAST_HOUR = "total_orders_last_hour"
    TOTAL_PNL = "total_pnl"
    TOTAL_REQUESTS = "total_requests"
    TOTAL_SYMBOLS = "total_symbols"
    TOTAL_TRADES = "total_trades"
    TOTAL_VALUE = "total_value"
    TRACE = "trace"
    TRACE_COVERAGE = "trace_coverage"
    TRACE_ID = "trace_id"
    TRACE_SUMMARY = "trace_summary"
    TRADE = "trade"
    TRADES = "trades"
    TRADES_ANALYZED = "trades_analyzed"
    TRADE_ALERTS = "trade_alerts"
    TRADE_COUNT = "trade_count"
    TRADE_EVAL_ID = "trade_eval_id"
    TRADE_FEED = "trade_feed"
    TRADE_ID = "trade_id"
    TRADE_LIFECYCLE = "trade_lifecycle"
    TRADE_RATE = "trade_rate"
    TRADE_TYPE = "trade_type"
    TRADING_PAUSED = "trading_paused"
    TRADING_PAUSED_REASON = "trading_paused_reason"
    TRAFFIC_LIGHT = "traffic_light"
    TRAJECTORY_SIMILARITY = "trajectory_similarity"
    TS = "ts"
    TYPE = "type"
    UNIT = "unit"
    UNITS = "units"
    UNREALIZED_PNL = "unrealized_pnl"
    UNREALIZED_PNL_PCT = "unrealized_pnl_pct"
    UPDATED_AT = "updated_at"
    UPSTREAM_ACTIVITY = "upstream_activity"
    UPTIME = "uptime"
    UPTIME_MINUTES = "uptime_minutes"
    UPTIME_SECONDS = "uptime_seconds"
    VALUE = "value"
    VECTOR_METADATA = "vector_metadata"
    VETO = "veto"
    VOLUME = "volume"
    VWAP_PLAN = "vwap_plan"
    WARNING = "warning"
    WEIGHT = "weight"
    WEIGHTS = "weights"
    WEIGHT_SCALE = "weight_scale"
    WINDOW_SECONDS = "window_seconds"
    WINNING_FACTORS = "winning_factors"
    WINNING_TRADES = "winning_trades"
    WINS = "wins"
    WIN_RATE = "win_rate"
    WIN_RATE_PERCENT = "win_rate_percent"
    WORKER_HEARTBEATS = "worker_heartbeats"
    WORST_HOURS = "worst_hours"
    WORST_TRADE = "worst_trade"


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
# Per-day total LLM call counter — used by /llm/health to populate daily_calls
# after a backend restart, where the in-process ring buffer is empty but the
# durable Redis counter survives. Follows the same {date} key shape so old
# days roll off naturally without an explicit expiry.
REDIS_KEY_LLM_DAILY_CALLS: Final[str] = "llm:daily_calls:{date}"
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
EMBED_DIMENSIONS: Final[int] = 1536  # pgvector column width — embedding vector length
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
# Per-stream health thresholds — MetricsAggregator marks a stream stale / lagging.
STALE_THRESHOLD_SECONDS: Final[int] = 30  # no update in 30s → stale
CRITICAL_LAG_MS: Final[int] = 5000  # lag > 5s → critical
WARNING_LAG_MS: Final[int] = 1000  # lag > 1s → warning
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
# Lower threshold used in memory mode — rule-based fallback signals produce composite_score=0.30,
# yielding final_score≈0.36 which is below the production gate. This lets paper trades execute
# so the trading dashboard shows real fills, positions, and equity-curve data.
EXECUTION_DECISION_THRESHOLD_MEMORY: Final[float] = 0.30

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
