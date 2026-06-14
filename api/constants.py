"""
Application constants and configuration values.

Use the StrEnum classes for all string comparisons in domain logic — no bare string literals.
"""

import sys
from dataclasses import dataclass
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
    TOOL_GOVERNANCE = "tool_governance"
    PROMPT_EVOLUTION = "prompt_evolution"
    # A shadow challenger that beat baseline. Human-approval-gated (not
    # auto-applied on stream consume): on approval the ProposalApplier both
    # biases the ReasoningAgent toward the winning strategy AND spawns it as a
    # live candidate. See api/services/agents/proposal_applier.py.
    CHALLENGER_PROMOTION = "challenger_promotion"


# Proposal types that must NOT be auto-applied when first seen on
# STREAM_PROPOSALS — the ProposalApplier leaves them pending until an operator
# approves, at which point the approval path republishes them with
# ``FieldName.APPROVED=True`` and the applier acts. Everything else is a
# learning-loop safety reaction that applies on consume.
APPROVAL_GATED_PROPOSAL_TYPES: Final[frozenset[str]] = frozenset(
    {ProposalType.CHALLENGER_PROMOTION}
)


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


class TradeTag(StrEnum):
    """Canonical deterministic scoring labels for mistakes and strengths."""

    LATE_ENTRY = "late_entry"
    POOR_EXIT = "poor_exit"
    BAD_RISK_REWARD = "bad_risk_reward"
    MISALIGNED_SIGNAL = "misaligned_signal"
    PREMATURE_ENTRY = "premature_entry"
    EARLY_EXIT = "early_exit"
    ADVERSE_PRICE_MOVE = "adverse_price_move"
    EXECUTION_DRAG = "execution_drag"
    GOOD_ENTRY_TIMING = "good_entry_timing"
    CLEAN_EXIT = "clean_exit"
    GOOD_RISK_REWARD = "good_risk_reward"
    TREND_ALIGNMENT = "trend_alignment"
    PROFITABLE = "profitable"
    PATIENCE_PAID = "patience_paid"
    CAPTURED_DIRECTIONAL_MOVE = "captured_directional_move"
    CLEAN_EXECUTION = "clean_execution"
    VOLATILITY_MISMATCH = "volatility_mismatch"
    LOW_LIQUIDITY_SKEW = "low_liquidity_skew"
    REGIME_SHIFT = "regime_shift"
    NEWS_DRIVEN_NOISE = "news_driven_noise"
    SIGNAL_LATENCY = "signal_latency"
    FILL_QUALITY_POOR = "fill_quality_poor"
    API_THROTTLE_PENALTY = "api_throttle_penalty"
    DATA_INTEGRITY_ISSUE = "data_integrity_issue"
    SIZE_ADJUSTMENT_ERROR = "size_adjustment_error"
    CORRELATION_CLASH = "correlation_clash"
    OVER_LEVERAGED = "over_leveraged"
    EXCESSIVE_CHURNING = "excessive_churning"
    REVERSION_LUCK = "reversion_luck"
    TRAILING_STOP_CHOPPED = "trailing_stop_chopped"
    FOMO_ENTRY = "fomo_entry"
    AVOIDED_DRAWDOWN = "avoided_drawdown"


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
    # Terminal state for proposals the ProposalApplier has acted on. Audit
    # rows MUST carry this so the review queue never renders an
    # already-applied change as a fresh pending decision.
    APPLIED = "applied"


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

    ACCOUNT_BALANCE = "account_balance"
    ACCURACY = "accuracy"
    ACKNOWLEDGED = "acknowledged"
    ACTION = "action"
    ACTIVE = "active"
    ADVISORY = "advisory"
    ALPHA = "alpha"
    ACTIVE_AGENTS = "active_agents"
    ACTIVE_AGENT_COUNT = "active_agent_count"
    ACTIVE_PROVIDER = "active_provider"
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
    ANOMALY_DETECTED = "anomaly_detected"
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
    ATR_REGIME_RATIO = "atr_regime_ratio"
    ATTRIBUTION = "attribution"
    ARTICLE_COUNT = "article_count"
    AUTO_APPLIED = "auto_applied"
    AVAILABLE_MODELS = "available_models"
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
    BACKTEST = "backtest"
    BAD_RISK_REWARD = "bad_risk_reward"
    BARS = "bars"
    BASELINE = "baseline"
    BASE_URL_HOST = "base_url_host"
    BASELINE_MEAN = "baseline_mean"
    BASELINE_SAMPLES = "baseline_samples"
    BASELINE_STD = "baseline_std"
    BEATS_BASELINE = "beats_baseline"
    BEST_HOURS = "best_hours"
    BEST_TRADE = "best_trade"
    BIAS = "bias"
    BENCHMARK = "benchmark"
    BID = "bid"
    BRANCH = "branch"
    BLOCKED_TOOLS = "blocked_tools"
    BLOCKS = "blocks"
    BLOCKED_REASON = "blocked_reason"
    BODY = "body"
    BOTS = "bots"
    BOT_STATE = "bot_state"
    BROKER_ORDER_ID = "broker_order_id"
    BROKER_STATUS = "broker_status"
    BUYING_POWER = "buying_power"
    BUYS = "buys"
    BY_SEVERITY = "by_severity"
    BY_STREAM = "by_stream"
    CACHED = "cached"
    CACHED_UNTIL_EPOCH = "cached_until_epoch"
    CANDIDATE = "candidate"
    CASH = "cash"
    CHALLENGERS = "challengers"
    CHALLENGER_CONFIG = "challenger_config"
    CHALLENGER_ID = "challenger_id"
    # Forward-looking challenger-config overrides surfaced by the reasoning
    # cockpit: a challenger MAY carry a prompt variant and/or a tool-name
    # override list in its config to differ from the champion. Absent today
    # (challengers differ by params only) but read so the UI lights up the
    # moment a producer starts setting them.
    PROMPT_VARIANT = "prompt_variant"
    TOOL_OVERRIDES = "tool_overrides"
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
    CALL_COUNT = "call_count"
    CLOSE = "close"
    CORRELATION = "correlation"
    CORRELATIONS = "correlations"
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
    DAILY_CHANGE_PCT = "daily_change_pct"
    DAILY_PNL = "daily_pnl"
    DATA = "data"
    DATABASE = "database"
    DATABASE_CONNECTED = "database_connected"
    DATABASE_HEALTH = "database_health"
    DATABASE_MODE = "database_mode"
    DATA_FRESHNESS_MS = "data_freshness_ms"
    DATA_KEYS = "data_keys"
    DATA_INTEGRITY_ISSUE = "data_integrity_issue"
    DATA_METRICS = "data_metrics"
    DATE = "date"
    DAY = "day"
    DB_AVAILABLE = "db_available"
    DB_HEALTH = "db_health"
    DB_POOL_STATUS = "db_pool_status"
    DB_SCHEMA_VERSION = "db_schema_version"
    DB_STATUS = "db_status"
    DEADLINE = "deadline"
    DECAYING = "decaying"
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
    DELTA = "delta"
    DESCRIPTION = "description"
    DETAILS = "details"
    DIMENSION = "dimension"
    DIRECTIVE = "directive"
    DIRECTION = "direction"
    DISCREPANCY = "discrepancy"
    DISPLAY = "display"
    DLQ_COUNT = "dlq_count"
    DOWNGRADE_REASON = "downgrade_reason"
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
    EQUITY = "equity"
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
    ENABLED = "enabled"
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
    FAILURE_RATE = "failure_rate"
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
    GENERATED_AT = "generated_at"
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
    IMBALANCE = "imbalance"
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
    IN_USE_CONNECTIONS = "in_use_connections"
    IS_DIFFERENT = "is_different"
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
    KELLY_SIZE = "kelly_size"
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
    LAST_LOCAL_ERROR = "last_local_error"
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
    LLM_FALLBACK_ENABLED = "llm_fallback_enabled"
    LLM_HEALTH_SCORE = "llm_health_score"
    LLM_PROVIDER = "llm_provider"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_SUCCEEDED = "llm_succeeded"
    LLM_SUCCESS_RATE_PCT = "llm_success_rate_pct"
    LLM_TIMEOUT_COUNT = "llm_timeout_count"
    LM_STUDIO = "lm_studio"
    LM_STUDIO_ENABLED = "lm_studio_enabled"
    LM_STUDIO_HEALTHY = "lm_studio_healthy"
    LOCAL_FALLBACK_COUNT = "local_fallback_count"
    LOCAL_INFERENCE_ENABLED = "local_inference_enabled"
    LOCAL_INFERENCE_HEALTHY = "local_inference_healthy"
    LOCAL_LATENCY_MS = "local_latency_ms"
    LOCAL_MODEL = "local_model"
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
    MAX_CONNECTIONS = "max_connections"
    MAX_CORRELATION = "max_correlation"
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
    MODELS = "models"
    MODEL_PERFORMANCE = "model_performance"
    MODEL_USED = "model_used"
    MODEL_VAR = "model_var"
    DECISION_COST_USD = "decision_cost_usd"
    TOTAL_COST = "total_cost"
    NET_ROI = "net_roi"
    MACRO_REGIME = "macro_regime"
    MOMENTUM = "momentum"
    MOMENTUM_PCT = "momentum_pct"
    MONITORING_ACTIVE = "monitoring_active"
    MOST_CORRELATED = "most_correlated"
    MSG_ID = "msg_id"
    N = "n"
    NAME = "name"
    NEW_AVG_COST = "new_avg_cost"
    NEW_QUANTITY = "new_quantity"
    NEW_VALUE = "new_value"
    NEWS_SENTIMENT = "news_sentiment"
    NEXT_TIMEFRAME = "next_timeframe"
    NET_EV = "net_ev"
    NORM_RETURN = "norm_return"
    NOTE = "note"
    NOTIFICATIONS = "notifications"
    NOTIFICATIONS_COUNT = "notifications_count"
    NOTIFICATION_ID = "notification_id"
    NOTIFICATION_SUMMARY = "notification_summary"
    NODE = "node"
    NOTIFICATION_TYPE = "notification_type"
    NOTIONAL = "notional"
    OBSERVED_MSG_ID = "observed_msg_id"
    OFFSET = "offset"
    OK = "ok"
    OLDEST_PENDING_AGE_SECONDS = "oldest_pending_age_seconds"
    OLDEST_PENDING_SCORE_AGE_SECONDS = "oldest_pending_score_age_seconds"
    OPEN = "open"
    OLD_VALUE = "old_value"
    OPENAI = "openai"
    OPENED_AT = "opened_at"
    OPEN_POSITION_QTY = "open_position_qty"
    OPEN_POSITIONS = "open_positions"
    ORCHESTRATOR = "orchestrator"
    ORDERS = "orders"
    ORDERS_LAST_HOUR = "orders_last_hour"
    ORDER_BOOK = "order_book"
    ORDER_ID = "order_id"
    ORDER_TYPE = "order_type"
    ORIGINAL_ID = "original_id"
    ORIGINAL_STREAM = "original_stream"
    OTEL_SPAN_ID = "otel_span_id"
    OTEL_TRACE_ID = "otel_trace_id"
    OUTCOME = "outcome"
    OUTPUT = "output"
    OUTPUT_DATA = "output_data"
    OUTPUTS = "outputs"
    OVERALL_SCORE = "overall_score"
    OVERALL_STATUS = "overall_status"
    P95_LATENCY_MS = "p95_latency_ms"
    PARAMETER = "parameter"
    PATTERNS = "patterns"
    PAYLOAD = "payload"
    PCT = "pct"
    PEAK_PNL_PCT = "peak_pnl_pct"
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
    POSITION_SIDE = "position_side"
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
    PR_URL = "pr_url"
    PROCESSED_COUNT = "processed_count"
    PROCESSED_EVENTS_LAST_HOUR = "processed_events_last_hour"
    PROCESSING_ATTEMPT = "processing_attempt"
    PROPOSALS = "proposals"
    PROPOSAL_TYPE = "proposal_type"
    PROPOSED_VALUE = "proposed_value"
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
    RATIONALE = "rationale"
    RAW_DATA = "raw_data"
    REACHABLE = "reachable"
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
    REDIS_POOL = "redis_pool"
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
    REJECTION_REASON = "rejection_reason"
    REMOTE_LOCALHOST_MISMATCH = "remote_localhost_mismatch"
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
    RSI = "rsi"
    RULES = "rules"
    RUN = "run"
    RUNNING = "running"
    RUNS = "runs"
    RUNTIME_DB_HEALTH = "runtime_db_health"
    RUNTIME_STORE = "runtime_store"
    RUN_ID = "run_id"
    RUN_TYPE = "run_type"
    SATURATED = "saturated"
    SCHEMA_VERSION = "schema_version"
    SCOPE = "scope"
    SCORE = "score"
    SCORE_PCT = "score_pct"
    SCORE_TREND = "score_trend"
    SPREAD_PCT = "spread_pct"
    SCORING = "scoring"
    SCORING_FAILED = "scoring_failed"
    SCORING_PENDING = "scoring_pending"
    SECONDS_AGO = "seconds_ago"
    SELF_CORRECTION = "self_correction"
    SELLS = "sells"
    SESSION_ID = "session_id"
    SEVERITY = "severity"
    SEVERITY_COUNTS = "severity_counts"
    SHADOW_EDGE = "shadow_edge"
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
    SLIPPAGE_BPS = "slippage_bps"
    SLIPPAGE_VARIANCE = "slippage_variance"
    SLOPE = "slope"
    SENTIMENT = "sentiment"
    SNIPPET = "snippet"
    SOURCE = "source"
    SPREAD_BPS = "spread_bps"
    STAGE = "stage"
    STAGES = "stages"
    STALE_SYMBOLS = "stale_symbols"
    STARTED_AT = "started_at"
    STARTING_CASH = "starting_cash"
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
    SUGGESTIONS = "suggestions"
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
    TIMEFRAMES = "timeframes"
    TIMEOUT = "timeout"
    TIMEOUTS = "timeouts"
    TIMEOUT_COUNT = "timeout_count"
    TIMESTAMP = "timestamp"
    TIME_IN_FORCE = "time_in_force"
    TIME_OF_DAY = "time_of_day"
    TIME_OF_DAY_PATTERNS = "time_of_day_patterns"
    TIMING_SCORE = "timing_score"
    TITLE = "title"
    TODAY = "today"
    TODAY_PNL = "today_pnl"
    TOKENS_USED = "tokens_used"
    TONE = "tone"
    TOOL = "tool"
    TOOLS = "tools"
    TOOLS_USED = "tools_used"
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
    TRAJECTORY = "trajectory"
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
    VERSION = "version"
    VOLUME = "volume"
    VOLUME_RATIO = "volume_ratio"
    VWAP_PLAN = "vwap_plan"
    WARNING = "warning"
    WEIGHT = "weight"
    WEIGHTS = "weights"
    WEIGHT_SCALE = "weight_scale"
    WINDOW_SECONDS = "window_seconds"
    WINNING_FACTORS = "winning_factors"
    WINNING_TRADES = "winning_trades"
    WINS = "wins"
    WIN_COUNT = "win_count"
    WIN_RATE = "win_rate"
    WIN_RATE_PERCENT = "win_rate_percent"
    WORKER_HEARTBEATS = "worker_heartbeats"
    WORST_HOURS = "worst_hours"
    WORST_TRADE = "worst_trade"
    # MCP dashboard-consistency diagnostic payload keys (api/mcp/read_tools.py).
    ACTION_DISTRIBUTION = "action_distribution"
    BROKER_OPEN_COUNT = "broker_open_count"
    BROKER_QTY = "broker_qty"
    DOWNGRADED_SELLS = "downgraded_sells"
    EQUITY_CONSISTENT = "equity_consistent"
    FLAT_IN_RAW_STORE = "flat_in_raw_store"
    HELD_LONG_SYMBOLS = "held_long_symbols"
    ISSUES = "issues"
    MISMATCHES = "mismatches"
    MISSING_IN_STORE = "missing_in_store"
    OPEN_TRADES_EXCLUDED = "open_trades_excluded"
    SCRATCH_TRADES_EXCLUDED = "scratch_trades_excluded"
    STALE_STORE_ONLY = "stale_store_only"
    STORE_OPEN_COUNT = "store_open_count"
    STORE_QTY = "store_qty"
    UNTAGGED_PHANTOM_SELLS = "untagged_phantom_sells"
    WINDOW = "window"
    Z_SCORE = "z_score"
    # Per-agent performance grading payload keys
    # (api/services/dashboard/agent_performance.py).
    COMPLETED_RUNS = "completed_runs"
    DATA_AVAILABLE = "data_available"
    DIMENSIONS = "dimensions"
    DISPLAY_NAME = "display_name"
    FAILED_RUNS = "failed_runs"
    HEARTBEAT = "heartbeat"
    LATENCY = "latency"
    LEARNINGS = "learnings"
    LIVENESS = "liveness"
    PROMOTED = "promoted"
    THROUGHPUT = "throughput"
    TIER = "tier"
    TOTAL_RUNS = "total_runs"
    GRADE_STREAK = "grade_streak"
    TARGET_TRUST = "target_trust"
    TRUST = "trust"
    ALPHA_SCORE = "alpha_score"


class StatusValue(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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


class MacroRegime(StrEnum):
    """Market-wide risk posture derived from a benchmark's recent trend.

    Powers the ``fetch_macro_regime`` perception tool (BTC proxies crypto, SPY
    proxies equities). These are payload VALUES, not dict keys.
    """

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"


class MarketState(StrEnum):
    """Current state of the US equity cash session (NYSE / NASDAQ).

    The single vocabulary every stock subsystem uses to gate work. Crypto is
    24/7 and never CLOSED; these states describe equities only. ``MarketStatusService``
    in ``api/services/market_status.py`` is the sole producer.
    """

    OPEN = "open"  # Regular session — polling, signals, execution allowed
    PREMARKET = "premarket"  # 04:00–09:30 ET — session-adjacent, equities gated
    AFTER_HOURS = "after_hours"  # 16:00–20:00 ET (or early-close→20:00) — gated
    CLOSED = "closed"  # Overnight / weekend — fully dark
    HOLIDAY = "holiday"  # Exchange holiday — fully dark for the whole day


class StrategyStatus(StrEnum):
    """Lifecycle stage of a strategy version in the evolution pipeline.

    A version advances exactly one stage at a time and can never skip ahead, so
    nothing reaches live production without passing every risk-containment gate.
    RETIRED is terminal and reachable from any stage (a strategy can always be
    pulled).
    """

    PROPOSED = "proposed"
    BACKTESTED = "backtested"
    SHADOW = "shadow"
    CANARY = "canary"
    LIVE = "live"
    RETIRED = "retired"


class ToolPhase(StrEnum):
    """DAG phase a runtime tool belongs to.

    The Tool Registry exposes only the tools whose phase matches the current
    reasoning node, so the LLM never sees the full catalog at once (the Runtime
    Tool Governance directive). Phases run perception → memory → risk →
    execution, with optimization tools available to the offline challenger.
    """

    PERCEPTION = "perception"
    MEMORY = "memory"
    RISK = "risk"
    EXECUTION = "execution"
    OPTIMIZATION = "optimization"


# ---------------------------------------------------------------------------
# Runtime tool identities + state-flag gates (Tool Registry contract)
# ---------------------------------------------------------------------------
# Tool names and gating flags are a cross-module contract: the Tool Registry
# seeds the catalog with these names (api/services/tool_registry.py) and the
# ReasoningAgent records telemetry against the SAME names when it exercises a
# tool. A literal typo on either side would silently mis-attribute telemetry,
# so both sides import from here.

TOOL_STREAM_CONFLUENCE = "get_stream_confluence_metrics"
TOOL_MACRO_REGIME = "fetch_macro_regime"
TOOL_SECTOR_CORRELATION = "scan_sector_correlation"
TOOL_QUERY_SIMILAR_TRADES = "query_similar_trades"
TOOL_GET_IC_WEIGHTS = "get_ic_weights"
TOOL_RISK_CAGE = "evaluate_risk_cage"
TOOL_VWAP_EXECUTION = "calculate_vwap_execution"
TOOL_BRACKET_ORDER = "execute_bracket_order"
TOOL_REPLAY_REGRESSION = "replay_regression_check"
TOOL_ORDER_BOOK_DEPTH = "get_order_book_depth"
TOOL_NEWS_SENTIMENT = "get_news_sentiment"
TOOL_CORRELATION_CHECK = "check_cross_asset_correlation"

# State-flag gates a tool requires before it becomes eligible at a node.
TOOL_FLAG_CONFLUENCE_LOADED = "confluence_loaded"
TOOL_FLAG_RISK_APPROVED = "risk_approved"
TOOL_FLAG_THESIS_COMMITTED = "thesis_committed"

# The reasoning DAG node reasons over perception + memory and discards any
# tool whose alpha attribution is negative, so the buy/sell LLM only ever sees
# the governed, positive-edge subset (never the full catalog).
REASONING_NODE = "reasoning"
REASONING_TOOL_MIN_ALPHA = 0.0


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
SOURCE_RISK_GUARDIAN: Final[str] = "risk_guardian"

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
# Per-agent performance grading (api/services/dashboard/agent_performance.py)
# Each pipeline agent is graded on its OWN telemetry — heartbeat liveness, run
# success rate, recent throughput, and (when the DB records it) latency —
# rather than the single system-wide grade GradeAgent emits for the trading
# loop. The overall [0, 1] score is a weighted blend of whichever dimensions
# have data, mapped to a letter grade via services.agents.scoring.score_to_grade.
AGENT_PERF_W_LIVENESS: Final[float] = 0.40
AGENT_PERF_W_SUCCESS: Final[float] = 0.30
AGENT_PERF_W_THROUGHPUT: Final[float] = 0.15
AGENT_PERF_W_LATENCY: Final[float] = 0.15
# Realized-PnL dimension — only applies to the trading agents (see
# PNL_GRADED_AGENTS). Weighted heavily because, for a trading agent, making
# money is the point; it dominates the blended score once enough trades exist.
AGENT_PERF_W_PNL: Final[float] = 0.50

# Liveness dimension score by heartbeat state (ACTIVE vs STALE/IDLE).
AGENT_PERF_LIVENESS_ACTIVE: Final[float] = 1.0
AGENT_PERF_LIVENESS_STALE: Final[float] = 0.45

# event_count at which the throughput dimension saturates to 1.0. High enough
# that a few dozen events cannot max the dimension — sustained flow is required.
AGENT_PERF_THROUGHPUT_SATURATION: Final[int] = 100

# Promotion tiers, ordered best → worst. Mirrored by the frontend badge map.
TIER_PROMOTED: Final[str] = "PROMOTED"
TIER_TRUSTED: Final[str] = "TRUSTED"
TIER_STANDARD: Final[str] = "STANDARD"
TIER_PROBATION: Final[str] = "PROBATION"
TIER_UNDER_REVIEW: Final[str] = "UNDER_REVIEW"
TIER_UNRATED: Final[str] = "UNRATED"

# Letter grade → promotion tier. An agent is "promoted" iff its tier is PROMOTED.
# Sustained A/A+ work earns promotion; D/F drops to review.
GRADE_TO_TIER: Final[dict[str, str]] = {
    "A+": TIER_PROMOTED,
    "A": TIER_PROMOTED,
    "B": TIER_TRUSTED,
    "C": TIER_STANDARD,
    "D": TIER_PROBATION,
    "F": TIER_UNDER_REVIEW,
}

# Maps the lowercase source identifier written on agent_runs / agent_logs to the
# SCREAMING_SNAKE_CASE agent-name constant used by heartbeats and ALL_AGENT_NAMES.
# Lets per-agent grading attribute runs to the agent that produced them.
SOURCE_TO_AGENT: Final[dict[str, str]] = {
    SOURCE_SIGNAL: AGENT_SIGNAL,
    SOURCE_REASONING: AGENT_REASONING,
    SOURCE_EXECUTION: AGENT_EXECUTION,
    SOURCE_GRADE: AGENT_GRADE,
    SOURCE_IC_UPDATER: AGENT_IC_UPDATER,
    SOURCE_REFLECTION: AGENT_REFLECTION,
    SOURCE_STRATEGY_PROPOSER: AGENT_STRATEGY_PROPOSER,
    SOURCE_NOTIFICATION: AGENT_NOTIFICATION,
    SOURCE_PROPOSAL_APPLIER: AGENT_PROPOSAL_APPLIER,
}

# Durable tool telemetry. The ToolRegistry is an in-process singleton with no
# persistence, so a redeploy/restart wipes every tool's accumulated call_count /
# alpha / latency back to its seeded prior — which makes a live system look like
# it has "never used" its tools. This Redis snapshot is loaded on startup and
# flushed periodically so real usage survives restarts.
REDIS_KEY_TOOL_TELEMETRY: Final[str] = "tools:telemetry"
TOOL_TELEMETRY_FLUSH_INTERVAL_SECONDS: Final[int] = 60

# Durable per-agent grade history (Redis list per agent, via RedisStore). A
# snapshot is appended at most once per AGENT_GRADE_SNAPSHOT_INTERVAL_SECONDS (or
# whenever the letter grade changes), so the list spans hours, not seconds.
REDIS_KEY_AGENT_GRADE_HISTORY: Final[str] = "agent:grade_history:{name}"
AGENT_GRADE_HISTORY_MAX: Final[int] = 50  # capped list length per agent
AGENT_GRADE_HISTORY_DISPLAY: Final[int] = 20  # recent snapshots returned to the UI
AGENT_GRADE_SNAPSHOT_INTERVAL_SECONDS: Final[int] = 300  # throttle: ≤1 write / 5 min

# Promotion requires SUSTAINED top performance: the agent must hold an A/A+
# grade for this many consecutive snapshots before it earns the PROMOTED tier
# (a single good window shows TRUSTED until the streak is built).
AGENT_PROMOTION_STREAK: Final[int] = 5

# ── Realized-PnL agent grading (durable in Redis — no Postgres) ──────────────
# The agents whose decisions produce realized PnL. GradeAgent attributes each
# closed trade's PnL to these, and agent_performance grades them on it.
PNL_GRADED_AGENTS: Final[frozenset[str]] = frozenset(
    {AGENT_SIGNAL, AGENT_REASONING, AGENT_EXECUTION}
)
# Durable per-agent PnL accumulator (Redis hash, no TTL → survives restarts /
# deploys; InMemoryStore is NOT used because it is wiped on restart).
REDIS_KEY_AGENT_PNL: Final[str] = "agent:pnl:{name}"
# A trading agent must have closed at least this many trades before its PnL
# dimension is scored (avoids grading on a 1-trade fluke) AND before PnL can
# gate promotion. Below this the dimension reads "no data", never fabricated.
AGENT_PNL_MIN_TRADES: Final[int] = 20
# Promotion gate: a trading agent cannot reach PROMOTED unless its realized win
# rate clears this bar (with ≥ AGENT_PNL_MIN_TRADES trades) AND its total
# realized PnL is positive — a winning rate that still loses money must not
# promote. Stops an agent being promoted on liveness/throughput while its
# trades bleed money.
AGENT_PNL_PROMOTION_MIN_WIN_RATE: Final[float] = 0.55

# Behavioral promotion — per-agent trust weight (control plane). ReasoningAgent
# multiplies its signal_weight_scale by this when AGENT_TRUST_WEIGHTING_ENABLED
# is on; bounded so a promoted agent gains, and a struggling one loses, only a
# capped amount of influence. Written by the explicit promotion-apply action.
REDIS_KEY_AGENT_TRUST: Final[str] = "learning:agent_trust:{name}"
AGENT_TRUST_DEFAULT: Final[float] = 1.0
AGENT_TRUST_MIN: Final[float] = 0.5
AGENT_TRUST_MAX: Final[float] = 1.25

# Promotion tier → trust weight written to the control plane on apply.
TIER_TO_TRUST: Final[dict[str, float]] = {
    TIER_PROMOTED: 1.15,
    TIER_TRUSTED: 1.0,
    TIER_STANDARD: 1.0,
    TIER_PROBATION: 0.8,
    TIER_UNDER_REVIEW: 0.6,
    TIER_UNRATED: AGENT_TRUST_DEFAULT,
}

# ---------------------------------------------------------------------------
# Redis key patterns
REDIS_KEY_PAPER_CASH: Final[str] = "paper:cash"
REDIS_KEY_PAPER_POSITION: Final[str] = "paper:positions:{symbol}"
REDIS_KEY_PAPER_ORDER: Final[str] = "paper:order:{broker_order_id}"
REDIS_KEY_ORDER_LOCK: Final[str] = "order_lock:{symbol}"
REDIS_KEY_ORDER_DEDUP: Final[str] = "order:dedup:{idempotency_key}"
REDIS_KEY_IN_FLIGHT_ORDER: Final[str] = "execution:in_flight"
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
# Proposal-creation guardrails (StrategyProposer). Date-keyed like the LLM
# budget so they reset each day and old keys roll off via TTL. The count key is
# a per-day total proposal counter (daily cap); the dedup key is a per-day SET
# of proposal fingerprints so the same candidate change is not emitted twice in
# a day. Written by api/services/agents/proposal_guardrails.py.
REDIS_KEY_PROPOSALS_DAILY_COUNT: Final[str] = "proposals:count:{date}"
REDIS_KEY_PROPOSALS_DEDUP: Final[str] = "proposals:dedup:{date}"
PROPOSAL_GUARDRAIL_TTL_SECONDS: Final[int] = 172_800  # 48h — survives the day, self-cleans
REDIS_KEY_KILL_SWITCH: Final[str] = "kill_switch:active"
REDIS_KEY_KILL_SWITCH_UPDATED_AT: Final[str] = "kill_switch:updated_at"
REDIS_KEY_IC_WEIGHTS: Final[str] = "alpha:ic_weights"
# Trailing-stop ratchet state — owner: RiskGuardian. One JSON value per open
# position: {peak_pnl_pct, avg_cost}. avg_cost identifies the position; a basis
# change (new entry / add) resets the ratchet. Deleted when the guardian closes
# the position; the TTL (refreshed on every scan) reaps keys orphaned by closes
# the guardian didn't issue (opposite-signal exits via ReasoningAgent).
REDIS_KEY_RISK_PEAK_PNL: Final[str] = "risk:peak_pnl:{symbol}"
REDIS_RISK_PEAK_TTL_SECONDS: Final[int] = 604_800  # 7 days — outlives any position

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

# ---------------------------------------------------------------------------
# Regression gate — hard thresholds a challenger must clear before promotion.
# These are deterministic and non-negotiable: a candidate is rejected if it is
# worse than the champion on ANY gate beyond these tolerances. No exceptions.
# How many recent github_prs stream entries the pending-param-changes endpoint
# scans (the GitHub Action de-dupes, so this only bounds the read window).
PARAM_PR_REQUESTS_SCAN_LIMIT: Final[int] = 200

# ---------------------------------------------------------------------------
# Candidate Sharpe may be at most this far BELOW the champion's.
REGRESSION_MIN_SHARPE_DELTA: Final[float] = -0.10
# Candidate max-drawdown may be at most this many percentage-points WORSE
# (drawdown is stored negative, so "worse" = more negative).
REGRESSION_MAX_DRAWDOWN_DELTA_PCT: Final[float] = 1.0
# Candidate false-positive rate may exceed the champion's by at most this much.
REGRESSION_MAX_FALSE_POSITIVE_DELTA: Final[float] = 0.05
# Candidate average slippage may exceed the champion's by at most this many bps.
REGRESSION_MAX_SLIPPAGE_DELTA_BPS: Final[float] = 2.0
# A replay needs at least this many trades to be considered statistically valid.
REGRESSION_MIN_REPLAY_TRADES: Final[int] = 10
# A shadow challenger must accumulate at least this many shadow trades before it
# may emit a (human-approvable) promotion proposal — enough evidence that "beats
# baseline" is signal, not noise. Decouples challenger learning from the live-fill
# starvation that otherwise gates grades/retirement on trades that never close.
CHALLENGER_MIN_SHADOW_TRADES: Final[int] = 40
# Beating baseline alone is not enough: the challenger's OWN shadow record must
# also be objectively good — minimum win rate, positive realized shadow PnL,
# and positive Sharpe over the window. Without these, "beats baseline" can just
# mean "lost less than a losing baseline".
CHALLENGER_MIN_SHADOW_WIN_RATE: Final[float] = 0.55
# Hard cap on concurrently RUNNING shadow challengers, with one-per-strategy
# dedup, enforced by ChallengerSpawner. Without these, the promotion loop
# (auto-applied promotion → spawn clone of same strategy → clone beats
# baseline → promotes again) appended near-identical challengers to the live
# fleet without bound.
MAX_CONCURRENT_CHALLENGERS: Final[int] = 3

REDIS_KEY_PRICES: Final[str] = "prices:{symbol}"  # use .format(symbol=symbol)
# Market-intel caches (Category 1 market-data cache) — written by the reasoning
# node's new perception tools after a live Alpaca fetch, so repeated decisions
# inside the cache window reuse one API call instead of re-hitting Alpaca.
REDIS_KEY_NEWS_SENTIMENT: Final[str] = "news_sentiment:{symbol}"  # use .format(symbol=symbol)
REDIS_KEY_CORRELATION: Final[str] = "correlation:{symbol}"  # use .format(symbol=symbol)
REDIS_KEY_MACRO_REGIME: Final[str] = "macro_regime:{symbol}"  # use .format(symbol=benchmark)
REDIS_KEY_WORKER_HEARTBEAT: Final[str] = "worker:heartbeat"
# Self-evolving prompt store (Category 2 computed configuration). The active
# learned "adaptive directive" per reasoning node + a capped history for audit
# and rollback. Written by ProposalApplier on an approved PROMPT_EVOLUTION
# proposal; read by ReasoningAgent at prompt-assembly time (as challenger_variant
# beneath the immutable constitution). No TTL — a learned directive persists.
REDIS_KEY_PROMPT_DIRECTIVE: Final[str] = "prompt:directive:{node}"  # .format(node=node)
REDIS_KEY_PROMPT_DIRECTIVE_HISTORY: Final[str] = "prompt:directive:history:{node}"
PROMPT_DIRECTIVE_HISTORY_CAP: Final[int] = 20  # prior versions kept for rollback
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
# Closed round-trips (LPUSH, LTRIM cap) — the trade history behind the header
# PnL. The PaperBroker equity survives restarts (Redis), so the trades that
# produced it must too, or the dashboard shows a PnL no visible trade explains.
REDIS_KEY_CLOSED_TRADES_RECENT: Final[str] = "closed_trades:recent"
REDIS_CLOSED_TRADES_MAX: Final[int] = 100
# Cooling-off: recent trade PnL outcomes (LPUSH, LTRIM cap COOLING_OFF_WINDOW+5)
REDIS_KEY_RECENT_OUTCOMES: Final[str] = "trading:recent_outcomes"
REDIS_RECENT_OUTCOMES_MAXLEN: Final[int] = 10
REDIS_NOTIFICATIONS_MAX: Final[int] = 20
REDIS_DECISIONS_MAX: Final[int] = 50

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
STREAM_SELL_REJECTED: Final[str] = "sell_rejected"

# The four streams shown on the dashboard pipeline view
PIPELINE_STREAMS: Final[tuple[str, ...]] = (
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
)


# Canonical list of all runtime streams for diagnostics/telemetry readers.
STREAMS: Final[tuple[str, ...]] = (
    STREAM_MARKET_TICKS,
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
    STREAM_ORDERS,
    STREAM_EXECUTIONS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_PERFORMANCE,
    STREAM_RISK_ALERTS,
    STREAM_LEARNING_EVENTS,
    STREAM_SYSTEM_METRICS,
    STREAM_AGENT_LOGS,
    STREAM_AGENT_GRADES,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_PROPOSALS,
    STREAM_NOTIFICATIONS,
    STREAM_GITHUB_PRS,
    STREAM_TRADE_LIFECYCLE,
    STREAM_DLQ,
    STREAM_SELL_REJECTED,
)

# Default values
DEFAULT_PAPER_CASH: Final[float] = 100_000.0
ORDER_LOCK_TTL_SECONDS: Final[int] = 5
IN_FLIGHT_TTL_SECONDS: Final[int] = 10  # Safety valve: clears if fill callback never runs
WORKER_HEARTBEAT_TTL_SECONDS: Final[int] = 120  # Background worker liveness key TTL
# How long price cache entries live. MUST exceed the longest poll interval
# (STOCK_POLL_INTERVAL_SECONDS = 60s) — otherwise the cache expires before the
# poller can refresh it, leaving prices:{symbol} empty between polls (dashboard
# shows blank/stale stock prices). 150s survives one missed poll with margin.
# (The buy/sell momentum delta no longer depends on this TTL — the poller keeps
# its own in-memory prev-price anchor. See docs/troubleshooting/price-poller.md.)
REDIS_PRICES_TTL_SECONDS: Final[int] = 150
# News moves far slower than ticks; correlation is slow-moving and the bar
# fetch is the heaviest of the three — cache both to bound Alpaca calls.
REDIS_NEWS_SENTIMENT_TTL_SECONDS: Final[int] = 300  # 5 min
REDIS_CORRELATION_TTL_SECONDS: Final[int] = 120  # 2 min
REDIS_MACRO_REGIME_TTL_SECONDS: Final[int] = 300  # 5 min — macro regime moves slowly
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
EXECUTION_DECISION_THRESHOLD_MEMORY: Final[float] = 0.55

# Risk Guardian constants — position-level and portfolio-level risk limits
# Close position if unrealized loss exceeds this fraction of entry price
STOP_LOSS_PCT: Final[float] = 0.05
# Close position if unrealized gain exceeds this fraction of entry price
TAKE_PROFIT_PCT: Final[float] = 0.10
# Activate kill switch if today's realized PnL < -(portfolio_value * this)
DAILY_LOSS_LIMIT_PCT: Final[float] = 0.02
# How often (seconds) RiskGuardian scans open positions
RISK_CHECK_INTERVAL_SECONDS: Final[int] = 30
# Trailing-stop profit ratchet. Without it a +9% winner that reverses rides all
# the way back to the -5% hard stop — a 14-point round trip given back. Once a
# position's peak unrealized PnL reaches ARM_PCT the ratchet arms; it then
# closes the position when current PnL falls below peak * (1 - GIVEBACK_FRAC),
# so an armed winner always banks at least ARM_PCT * (1 - GIVEBACK_FRAC).
# Hard STOP_LOSS_PCT / TAKE_PROFIT_PCT bounds still apply on either side.
TRAILING_STOP_ARM_PCT: Final[float] = 0.03
TRAILING_STOP_GIVEBACK_FRAC: Final[float] = 0.40
# Stale-position reaper: a position older than MAX_AGE whose PnL is still inside
# the dead band (|pnl| < BAND_PCT) is going nowhere — momentum has decayed. Close
# it to free the capital instead of letting chop bleed it into the hard stop.
# Only enforced where the position payload carries opened_at (paper broker).
STALE_POSITION_MAX_AGE_SECONDS: Final[int] = 14_400  # 4 hours
STALE_POSITION_PNL_BAND_PCT: Final[float] = 0.01
# Signal confidence gate — trades below this confidence are blocked pre-execution.
# Set just below the MOMENTUM tier (signal composite score 0.55) so MOMENTUM and
# STRONG signals can trade while LOW/noise (0.30) stays blocked. It MUST stay <=
# the MOMENTUM score: a higher value silently nullifies the execution-score gate,
# which is deliberately tuned (historical_perf=0.6) so MOMENTUM clears the 0.55
# threshold — see tests/agents/test_momentum_gate.py. At 0.65 the two gates
# contradicted each other so NO momentum trade could ever execute.
SIGNAL_CONFIDENCE_MIN_GATE: Final[float] = 0.50
# Kelly sizing — use quarter Kelly for conservatism
KELLY_FRACTION_SCALE: Final[float] = 0.25
# Maximum risk per trade as fraction of equity
MAX_RISK_PER_TRADE_PCT: Final[float] = 0.015

# Circuit breaker — live-strategy trip thresholds. Breaching any one trips the
# breaker: kill switch ON + roll the live strategy back to its previous version.
CIRCUIT_BREAKER_MAX_DRAWDOWN_PCT: Final[float] = 0.15
CIRCUIT_BREAKER_MAX_CONSECUTIVE_FAILURES: Final[int] = 5
CIRCUIT_BREAKER_MAX_DIVERGENCE: Final[float] = 0.5
CIRCUIT_BREAKER_MAX_LATENCY_MS: Final[float] = 5000.0

# Backtest dashboard cache — how often the background loop recomputes it.
BACKTEST_REFRESH_INTERVAL_SECONDS: Final[int] = 3600
# Estimated slippage per side (0.05%)
SLIPPAGE_PCT_PER_SIDE: Final[float] = 0.0005
# ATR period for regime filter
REGIME_ATR_PERIOD: Final[int] = 14
# Period for ATR moving average in regime filter
REGIME_ATR_AVG_PERIOD: Final[int] = 20
# Number of recent trades to consider for cooling-off
COOLING_OFF_WINDOW: Final[int] = 5
# Exponential decay weight for cooling-off scoring
COOLING_OFF_DECAY: Final[float] = 0.7
# Minimum acceptable risk-reward ratio
MIN_RR_RATIO: Final[float] = 2.0

# LLM fallback modes
LLM_FALLBACK_MODE_SKIP_REASONING: Final[str] = "skip_reasoning"
LLM_FALLBACK_MODE_REJECT_SIGNAL: Final[str] = "reject_signal"
LLM_FALLBACK_MODE_USE_LAST_REFLECTION: Final[str] = "use_last_reflection"
# Data-plane deterministic policy (Level-3 split): when the LLM is unavailable,
# the fast local policy decides instead of rejecting every signal — so trades keep
# flowing and the learning loop never starves. The LLM moves to the control plane
# (it tunes the policy params), off the per-signal critical path.
LLM_FALLBACK_MODE_LOCAL_POLICY: Final[str] = "local_policy"
LLM_FALLBACK_MODE: Final[str] = LLM_FALLBACK_MODE_REJECT_SIGNAL  # fail closed — no naive trades

# Decision mode (Level-3 data-plane / control-plane split) — who decides per signal.
DECISION_MODE_LLM: Final[str] = "llm"  # LLM decides; policy runs in shadow + is fallback
DECISION_MODE_POLICY: Final[str] = "policy"  # deterministic policy decides; LLM off the hot path
DECISION_MODE_HYBRID: Final[str] = "hybrid"  # LLM primary; policy is the always-on safety net
MODEL_LABEL_POLICY: Final[str] = "policy"  # model_used stamp when the data-plane policy decided

# Alpaca HTTP transport hardening — price_poller fetch layer
# Root cause addressed: SSLZeroReturnError(6) from stale keepalive reuse under Render NAT.
# keepalive_expiry (20 s) intentionally below Render NAT idle timeout (~60 s) so connections
# are preemptively closed rather than silently dropped server-side.
ALPACA_DATA_BASE_URL: Final[str] = "https://data.alpaca.markets"
ALPACA_HTTP_CONNECT_TIMEOUT_SECONDS: Final[int] = 5  # TCP + TLS handshake budget per attempt
ALPACA_HTTP_READ_TIMEOUT_SECONDS: Final[int] = 10  # response read budget per attempt
ALPACA_HTTP_KEEPALIVE_EXPIRY_SECONDS: Final[float] = 20.0  # drop idle conns before NAT does
ALPACA_CIRCUIT_BREAKER_THRESHOLD: Final[int] = 5  # consecutive failures to open circuit
ALPACA_CIRCUIT_BREAKER_RESET_SECONDS: Final[int] = 60  # seconds before circuit auto-closes

# LM Studio provider identifier — used in provider fields of inference responses
LM_STUDIO_PROVIDER: Final[str] = "lmstudio"

# LLM call parameters — cloud providers (groq / gemini / anthropic / openai)
# call_llm() — structured JSON trading decision; 0.0 = fully deterministic output
LLM_MAX_TOKENS_TRADING: Final[int] = 300
LLM_TEMPERATURE_TRADING: Final[float] = 0.0
# call_llm_with_system() — free-text reasoning / reflection; slight variation is fine
LLM_MAX_TOKENS_ANALYSIS: Final[int] = 800
LLM_TEMPERATURE_ANALYSIS: Final[float] = 0.3

# LM Studio token budgets are controlled by LM_STUDIO_MAX_TOKENS* env vars (api/config.py).

# LM Studio task type identifiers — select the right token budget per call site
LLM_TASK_PRICE_ANALYSIS: Final[str] = "price_analysis"
LLM_TASK_TRADE_EXECUTION: Final[str] = "trade_execution"
LLM_TASK_HEALTH_CHECK: Final[str] = "health_check"

# Stop sequences for LM Studio — defence against thinking-mode preambles.
# "Thinking Process:" guards against any model that ignores enable_thinking=False.
# Does not affect instruct-only models (Llama 3.1) — never triggers but costs nothing.
LLM_STOP_SEQUENCES: Final[list[str]] = ["Thinking Process:"]

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


# ---------------------------------------------------------------------------
# Telemetry governance — approved telemetry-attribute registry (v1)
#
# Single source of truth for which `trading.*` span/metric attributes the app
# may emit and use as RED dimensions, plus each one's cardinality budget. The
# telemetry sibling of FieldName (which governs payload/DB-row keys): a producer
# registers an attribute here BEFORE emitting it, and the build-time guardrail
# (tests/core/test_telemetry_schema_governance.py) fails CI when api/telemetry.py
# emits an unregistered key or the collector's spanmetrics dimension allowlist
# references one. Design: docs/platform/telemetry-governance.md.
#
# cardinality_budget = max distinct values before drift is an incident. The 0
# sentinel marks a deliberately UNBOUNDED key that must stay a span attribute and
# NEVER become a metric label (e.g. trace_id).
TELEMETRY_ATTR_PREFIX: Final[str] = "trading."


@dataclass(frozen=True)
class TelemetryAttr:
    """One approved telemetry attribute: cardinality budget + ownership."""

    key: str
    cardinality_budget: int
    is_red_dimension: bool
    owner: str
    note: str


TELEMETRY_SCHEMA: Final[dict[str, TelemetryAttr]] = {
    attr.key: attr
    for attr in (
        TelemetryAttr("trading.symbol", 50, True, "backend", "approved trading universe"),
        TelemetryAttr(
            "trading.agent", 200, True, "backend", "7-agent fleet + normalized challenger-<id>"
        ),
        TelemetryAttr("trading.operation", 30, True, "backend", "broker / agent operation names"),
        TelemetryAttr("trading.side", 4, True, "backend", "buy / sell / none"),
        TelemetryAttr("trading.stream", 30, True, "backend", "Redis stream names"),
        TelemetryAttr("trading.component", 40, True, "backend", "error-source components"),
        TelemetryAttr("trading.broker", 5, True, "backend", "paper / alpaca"),
        TelemetryAttr(
            "trading.signal_type", 20, False, "backend", "metric label only; not a RED dimension"
        ),
        TelemetryAttr(
            "trading.success", 3, False, "backend", "broker-call outcome flag; not a RED dimension"
        ),
        TelemetryAttr(
            "trading.trace_id",
            0,
            False,
            "backend",
            "UNBOUNDED sentinel — span attribute for lifecycle search only, never a metric label",
        ),
    )
}


# Telemetry drift auditor (governance Layer B — docs/platform/telemetry-governance.md §2).
# The bounded drift SIGNAL: one counter labelled only by a 2-value kind; the
# offending key rides in a log line, never as a metric label (a per-key label
# would make the detector the cardinality bomb it polices).
TELEMETRY_DRIFT_METRIC: Final[str] = "telemetry_schema_drift_total"
DRIFT_KIND_LABEL: Final[str] = "drift_kind"  # metric label key (2 bounded values)
DRIFT_KIND_UNKNOWN_KEY: Final[str] = "unknown_key"
DRIFT_KIND_BUDGET_EXCEEDED: Final[str] = "budget_exceeded"
# Redis SET of already-reported "{kind}:{attribute}" tags, so a standing
# violation pages once across restarts. No TTL — owner: telemetry drift auditor.
REDIS_KEY_TELEMETRY_DRIFT_REPORTED: Final[str] = "telemetry:drift:reported"


# ---------------------------------------------------------------------------
# Learning-loop parameter overrides (applied LAST, over the defaults above).
#
# The values above are the hand-authored defaults. The GitOps learning loop tunes
# a small allowlist of them by writing config/param_overrides.json (plain DATA —
# the bot never edits this source file). We apply that file here, once, at import:
# each override is validated against api.services.param_evolution.PARAM_BOUNDS, so
# an unknown key or out-of-bounds value is dropped and the default stands. A bad
# override file therefore degrades to "use defaults", never to a crash.
#
# Import is local to avoid any import-time cycle and to keep this file importable
# even if the services package is unavailable (e.g. minimal tooling contexts).
def _apply_param_overrides() -> dict[str, float]:
    try:
        from api.services.param_overrides import load_overrides  # noqa: PLC0415
    except Exception:
        return {}
    applied: dict[str, float] = {}
    overrides = load_overrides()
    _g = globals()
    for name, value in overrides.items():
        if name in _g:  # only override an existing default
            _g[name] = value
            applied[name] = value
    return applied


# Names the learning loop has overridden this process (empty when none). Surfaced
# by the dashboard so operators can see which params are running off-default.
ACTIVE_PARAM_OVERRIDES: dict[str, float] = _apply_param_overrides()
