from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import Boolean, Column, DateTime, Date, Float, Integer, Numeric, String, Text, UUID, text
try:
    from sqlalchemy.dialects.postgresql.json import JSONB
    from pgvector.sqlalchemy import Vector
    POSTGRES_AVAILABLE = True
except ImportError:
    # Fallback for SQLite compatibility
    JSONB = Text
    Vector = Text
    POSTGRES_AVAILABLE = False

from api.database import Base


class TradeRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol (e.g., AAPL)")
    price: float = Field(..., gt=0, description="Current price of the asset")
    signals: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class TradeModel(BaseModel):
    date: str
    asset: str
    direction: str = Field(..., pattern="^(LONG|SHORT|FLAT)$")
    size: float = Field(..., gt=0)
    entry: float = Field(..., gt=0)
    stop: float = Field(..., gt=0)
    target: float = Field(..., gt=0)
    rr_ratio: float = Field(..., gt=0)
    exit: Optional[float] = None
    pnl: Optional[float] = None
    outcome: str = Field("OPEN", pattern="^(OPEN|WIN|LOSS)$")


class TradeDecision(BaseModel):
    symbol: str
    decision: str = Field(..., pattern="^(LONG|SHORT|FLAT)$")
    confidence: float = Field(..., ge=0, le=1)
    reasoning: str
    timestamp: datetime
    position_size: Optional[float] = Field(None, ge=0, le=1)
    risk_assessment: Optional[Dict[str, Any]] = None


class AgentPerformanceView(BaseModel):
    agent_name: str
    total_calls: int
    successful_calls: int
    avg_response_time: float
    accuracy_score: float
    improvement_areas: List[str] = Field(default_factory=list)


class ReinforceRequest(BaseModel):
    run_id: int


class ReinforceResponse(BaseModel):
    run_id: int
    status: str
    negative_memories: int
    few_shot_memories: int
    promoted_rules: List[str] = Field(default_factory=list)
    dna_delta_usd: float
    prompt_cache_key: str


class AnnotationCreate(BaseModel):
    run_id: int
    node_name: str
    tool_call: Optional[str] = None
    transcript: Optional[str] = None
    is_hallucination: bool = False
    coach_reason: Optional[str] = None
    is_starred: bool = False
    override_payload: Optional[Dict[str, Any]] = None
    promoted_rule_key: Optional[str] = None


class InsightView(BaseModel):
    id: int
    tag: str
    confidence: float
    summary: str
    run_id: int
    needs_more_data: bool
    supporting_run_count: int
    created_at: datetime


class ProposedRun(BaseModel):
    task_type: str
    reason: str
    priority: int = Field(..., ge=1, le=3)
    suggested_params: Dict[str, Any] = Field(default_factory=dict)


class FeedbackJobStatusView(BaseModel):
    id: str
    run_id: int
    status: str
    error: Optional[str] = None
    completed_at: Optional[datetime] = None


class PnlResponse(BaseModel):
    total_pnl: float
    pnl_today: float
    pnl_today_pct_change: float
    avg_slippage_saved: float
    execution_cost: float
    net_alpha: float


class LearningVelocityResponse(BaseModel):
    passk_series: List[Optional[float]]
    coherence_series: List[Optional[float]]
    passk_trend: Literal["improving", "plateauing", "regressing"]
    annotations_this_week: int
    avg_sessions_to_correction: Optional[float]
    memory_guard_effectiveness_pct: float
    scoring_lag_warning: bool = False


class HealthSignalView(BaseModel):
    key: str
    label: str
    value: str
    status: Literal["green", "amber", "red", "blue"]
    interpretation: str


class RunSummaryRowView(BaseModel):
    task_type: str
    task_slug: str
    runs_7d: int
    win_rate_pct: float
    avg_steps: float
    baseline_avg_steps: float
    avg_pnl: float
    sparkline: List[float]


class SignalView(BaseModel):
    id: str
    priority: Literal["urgent", "review", "info"]
    message: str
    action_label: str
    action_type: Literal["flag", "reinforce", "view_run", "dismiss"]
    run_id: Optional[str]
    created_at: datetime
    dismissed: bool


class SystemHealth(BaseModel):
    feedback_jobs_pending: int
    feedback_jobs_failed: int
    scoring_pending: int
    scoring_failed: int
    scoring_failed_last_24h: int
    scoring_abandoned_count: int
    last_signal_generation: Optional[datetime] = None
    last_signal_generation_status: Literal["success", "failed", "never"] = "never"
    last_prompt_rebuild: Optional[datetime] = None
    last_successful_score_at: Optional[datetime] = None
    oldest_pending_score_age_seconds: Optional[float] = None
    signal_scheduler_running: bool


class ErrorResponse(BaseModel):
    error: str
    detail: str
    timestamp: datetime

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat()


class HealthResponse(BaseModel):
    status: str
    orchestrator: bool
    database: str
    timestamp: datetime
    config_source: Optional[str] = None


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, nullable=False)
    asset = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    size = Column(Float, nullable=False)
    entry = Column(Float, nullable=False)
    stop = Column(Float, nullable=False)
    target = Column(Float, nullable=False)
    rr_ratio = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    outcome = Column(String, default="OPEN")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AgentPerformance(Base):
    __tablename__ = "agent_performance"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String, nullable=False, unique=True)
    total_calls = Column(Integer, default=0)
    successful_calls = Column(Integer, default=0)
    avg_response_time = Column(Float, default=0.0)
    accuracy_score = Column(Float, default=0.0)
    improvement_areas = Column(Text, default="[]")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, nullable=False, index=True)
    task_type = Column(String, nullable=False, index=True, default="general")
    status = Column(String, nullable=False, index=True, default="failed")
    pnl = Column(Float, default=0.0)
    step_count = Column(Integer, default=0)
    token_cost_usd = Column(Float, default=0.0)
    ghost_run_id = Column(String, nullable=True)
    ghost_slippage = Column(Float, nullable=True)
    actual_slippage = Column(Float, nullable=True)
    reasoning_coherence_score = Column(Float, nullable=True)
    scoring_status = Column(String, nullable=False, default="pending", index=True)
    scoring_attempt_count = Column(Integer, nullable=False, default=0)
    last_scoring_attempt_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    scoring_abandoned_at = Column(DateTime(timezone=True), nullable=True)
    correction_verification_status = Column(
        String, nullable=False, default="pending", index=True
    )
    decision_json = Column(Text, nullable=False)
    trace_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(String, nullable=True, index=True)
    symbol = Column(String(64), nullable=True)
    signal_data = Column(JSONB, nullable=True)
    action = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=True)
    primary_edge = Column(Text, nullable=True)
    risk_factors = Column(JSONB, nullable=True)
    size_pct = Column(Float, nullable=True)
    stop_atr_x = Column(Float, nullable=True)
    rr_ratio = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    trace_id = Column(String(255), nullable=True, index=True)
    fallback = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class TraceStep(Base):
    __tablename__ = "trace_steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    node_name = Column(String, nullable=False)
    tool_call = Column(Text, nullable=True)
    transcript = Column(Text, nullable=True)
    is_hallucination = Column(Boolean, default=False)
    coach_reason = Column(Text, nullable=True)
    is_starred = Column(Boolean, default=False)
    override_payload = Column(Text, nullable=True)
    promoted_rule_key = Column(String, nullable=True)
    feedback_status = Column(String, default="pending", index=True)
    step_type = Column(String, nullable=True, index=True)
    tool_name = Column(String, nullable=True, index=True)
    tokens_used = Column(Integer, nullable=True)
    context_limit = Column(Integer, nullable=True)
    token_cost_usd = Column(Float, default=0.0)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class VectorMemoryRecord(Base):
    __tablename__ = "vector_memory_records"

    id = Column(Integer, primary_key=True, index=True)
    store_type = Column(String, nullable=False, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    node_name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    embedding_json = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    correction_verified_at = Column(DateTime(timezone=True), nullable=True)


class StrategyDNA(Base):
    __tablename__ = "strategy_dna"

    id = Column(Integer, primary_key=True, index=True)
    rule_key = Column(String, nullable=False, unique=True, index=True)
    segment_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=False, index=True)
    value_delta_usd = Column(Float, default=0.0)
    baseline_version = Column(String, nullable=True)
    state = Column(String, nullable=False, default="active")
    last_promoted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Insight(Base):
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    tag = Column(String, nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    summary = Column(Text, nullable=False)
    payload_json = Column(Text, nullable=True)
    supporting_run_count = Column(Integer, default=1)
    dismissed = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class FeedbackJob(Base):
    __tablename__ = "feedback_jobs"

    id = Column(String, primary_key=True, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(String, primary_key=True, index=True)
    priority = Column(String, nullable=False, index=True)
    message = Column(Text, nullable=False)
    action_label = Column(String, nullable=False)
    action_type = Column(String, nullable=False)
    run_id = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    dismissed = Column(Boolean, default=False, index=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    source_entity_id = Column(String, nullable=True, index=True)
    signal_type = Column(String, nullable=True, index=True)
    condition_changed_at = Column(DateTime(timezone=True), nullable=True)


class TaskTypeBaseline(Base):
    __tablename__ = "task_type_baselines"

    task_type = Column(String, primary_key=True, index=True)
    baseline_slippage = Column(Float, nullable=False)
    established_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_feedback_run_at = Column(DateTime(timezone=True), nullable=True)


class SystemState(Base):
    __tablename__ = "system_state"

    id = Column(Integer, primary_key=True, default=1)
    last_signal_generation = Column(DateTime(timezone=True), nullable=True)
    last_signal_generation_status = Column(String, nullable=False, default="never")


class Order(Base):
    __tablename__ = "orders"

    id = Column(
        String, primary_key=True, index=True
    )  # UUID stored as String for SQLite compatibility
    strategy_id = Column(
        String, nullable=False, index=True
    )  # UUID stored as String for SQLite compatibility
    symbol = Column(String(64), nullable=False)
    side = Column(String(16), nullable=False)
    qty = Column(Numeric(precision=18, scale=8), nullable=False)
    price = Column(Numeric(precision=18, scale=8), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)
    broker_order_id = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    filled_at = Column(DateTime(timezone=True), nullable=True)


class SystemMetric(Base):
    __tablename__ = "system_metrics"

    id = Column(
        String, primary_key=True, index=True
    )  # UUID stored as String for SQLite compatibility
    metric_name = Column(String(255), nullable=False, index=True)
    value = Column(Float, nullable=False)
    labels = Column(Text, nullable=True)  # JSONB stored as Text in SQLite
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )


class VectorMemory(Base):
    __tablename__ = "vector_memory"

    id = Column(
        String, primary_key=True, index=True,
        default=lambda: str(uuid4()),
        server_default=text("gen_random_uuid()::text")
    )
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    metadata_ = Column(JSONB, nullable=True)
    outcome = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(
        String, primary_key=True, index=True,
        default=lambda: str(uuid4()),
        server_default=text("gen_random_uuid()::text")
    )
    trace_id = Column(String(255), nullable=False)
    log_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LLMCostTracking(Base):
    __tablename__ = "llm_cost_tracking"

    id = Column(
        String, primary_key=True, index=True,
        default=lambda: str(uuid4()),
        server_default=text("gen_random_uuid()::text")
    )
    date = Column(Date, nullable=False)
    tokens_used = Column(Integer, server_default="0")
    cost_usd = Column(Float, server_default="0.0")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
