"""
Agent models - clean architecture.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func, text

from .base import Base


class AgentPool(Base):
    __tablename__ = "agent_pool"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String, unique=True, nullable=False, index=True)
    agent_type = Column(
        Enum("analysis", "execution", "learning", "monitoring", name="agent_type"),
        nullable=False,
        index=True,
    )
    description = Column(Text, nullable=True)
    config = Column(MutableDict.as_mutable(JSONB), default=dict, server_default=text("'{}'::jsonb"))
    capabilities = Column(
        MutableDict.as_mutable(JSONB), default=dict, server_default=text("'[]'::jsonb")
    )
    status = Column(
        Enum("active", "inactive", "archived", name="pool_status"),
        nullable=False,
        default="active",
        index=True,
    )
    version = Column(String, nullable=False, default="1.0.0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("idx_agent_pool_type_status", "agent_type", "status"),)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_pool.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trace_id = Column(String, nullable=False, index=True)
    run_type = Column(
        Enum("analysis", "execution", "learning", name="run_type"),
        nullable=False,
        index=True,
    )
    trigger_event = Column(String, nullable=True)
    input_data = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    output_data = Column(MutableDict.as_mutable(JSONB), nullable=True)
    schema_version = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    status = Column(
        Enum("running", "completed", "failed", "cancelled", name="run_status"),
        nullable=False,
        default="running",
        index=True,
    )
    error_message = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    tokens_used = Column(Integer, server_default="0", nullable=False)
    cost_usd = Column(Numeric(18, 8), server_default="0", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_agent_runs_agent_created", "agent_id", "created_at"),
        Index("idx_agent_runs_trace", "trace_id"),
        Index("idx_agent_runs_schema_version", "schema_version"),
        CheckConstraint("schema_version = 'v3'", name="check_agent_runs_schema_v3"),
    )


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    log_level = Column(
        Enum("debug", "info", "warning", "error", name="log_level"),
        nullable=False,
        default="info",
        index=True,
    )
    message = Column(Text, nullable=False)
    step_name = Column(String, nullable=True, index=True)
    step_data = Column(
        MutableDict.as_mutable(JSONB), default=dict, server_default=text("'{}'::jsonb")
    )
    trace_id = Column(String, nullable=True, index=True)
    schema_version = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )  # Add timestamp field
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_agent_logs_run_created", "agent_run_id", "created_at"),
        Index("idx_agent_logs_trace", "trace_id"),
        Index("idx_agent_logs_schema_version", "schema_version"),
        CheckConstraint("schema_version = 'v3'", name="check_agent_logs_schema_v3"),
    )


class AgentGrades(Base):
    __tablename__ = "agent_grades"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_pool.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grade_type = Column(
        Enum("accuracy", "efficiency", "safety", "overall", name="grade_type"),
        nullable=False,
        index=True,
    )
    score = Column(Numeric(3, 2), nullable=False)
    metrics = Column(
        MutableDict.as_mutable(JSONB), default=dict, server_default=text("'{}'::jsonb")
    )
    feedback = Column(Text, nullable=True)
    schema_version = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_agent_grades_agent_type", "agent_id", "grade_type"),
        Index("idx_agent_grades_run", "agent_run_id"),
        Index("idx_agent_grades_schema_version", "schema_version"),
        CheckConstraint("schema_version = 'v3'", name="check_agent_grades_schema_v3"),
    )
