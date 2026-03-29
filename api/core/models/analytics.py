"""
Analytics models - clean architecture.
"""

from pgvector.sqlalchemy import VECTOR  # Required for production
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


class TradePerformance(Base):
    __tablename__ = 'trade_performance'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey('strategies.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey('agent_pool.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    trade_id = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    entry_time = Column(DateTime(timezone=True), nullable=False, index=True)
    exit_time = Column(DateTime(timezone=True), nullable=True)
    entry_price = Column(Numeric(18, 8), nullable=False)
    exit_price = Column(Numeric(18, 8), nullable=True)
    quantity = Column(Numeric(18, 8), nullable=False)
    pnl = Column(Numeric(18, 8), nullable=True)
    pnl_percent = Column(Numeric(18, 8), nullable=True)
    holding_period_minutes = Column(Integer, nullable=True)
    max_drawdown = Column(Numeric(18, 8), nullable=True)
    max_runup = Column(Numeric(18, 8), nullable=True)
    sharpe_ratio = Column(Numeric(18, 8), nullable=True)
    trade_type = Column(Enum('long', 'short', name='trade_type'), nullable=False, index=True)
    exit_reason = Column(String, nullable=True)
    regime = Column(String, nullable=True, index=True)
    hour_utc = Column(Integer, nullable=True, index=True)
    performance_metrics = Column(
        MutableDict.as_mutable(JSONB),
        default=dict,
        server_default=text("'{}'::jsonb")
    )
    schema_version = Column(String, nullable=False, server_default="v2", index=True)
    source = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_trade_performance_agent_created', 'agent_id', 'created_at'),
        Index('idx_trade_performance_symbol_created', 'symbol', 'created_at'),
        Index('idx_trade_performance_regime_hour', 'regime', 'hour_utc'),
        Index('idx_trade_strategy_time', 'strategy_id', 'entry_time'),
        Index('idx_trade_unique', 'strategy_id', 'trade_id', unique=True),
        Index('idx_trade_performance_schema_version', 'schema_version'),
        CheckConstraint('schema_version = \'v2\'', name='check_trade_performance_schema_v2'),
    )


class VectorMemory(Base):
    __tablename__ = 'vector_memory'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agent_pool.id', ondelete='CASCADE'), nullable=True, index=True)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey('strategies.id', ondelete='CASCADE'), nullable=True, index=True)
    content = Column(Text, nullable=False)
    content_type = Column(Enum('insight', 'memory', 'feedback', 'note', name='content_type'), nullable=False, index=True)
    embedding = Column(VECTOR(1536), nullable=False)  # Vector embeddings for search - required
    vector_metadata = Column(MutableDict.as_mutable(JSONB), default=dict, server_default=text("'{}'::jsonb"))
    outcome = Column(MutableDict.as_mutable(JSONB), default=dict, server_default=text("'{}'::jsonb"))
    schema_version = Column(String, nullable=False, server_default="v2", index=True)
    source = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_vector_memory_agent_type', 'agent_id', 'content_type'),
        Index('idx_vector_memory_symbol', 'strategy_id'),
        Index('idx_vector_memory_schema_version', 'schema_version'),
        Index('idx_vector_memory_embedding', 'embedding', postgresql_using='ivfflat',
              postgresql_ops={'embedding': 'vector_cosine_ops'}, postgresql_with={'lists': 100}),
        CheckConstraint('schema_version = \'v2\'', name='check_vector_memory_schema_v2'),
    )


class SystemMetrics(Base):
    __tablename__ = 'system_metrics'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    metric_name = Column(String, nullable=False, index=True)
    metric_value = Column(Numeric(18, 8), nullable=False)
    metric_unit = Column(String, nullable=True)
    tags = Column(MutableDict.as_mutable(JSONB), default=dict, server_default=text("'{}'::jsonb"))
    schema_version = Column(String, nullable=False, server_default="v2", index=True)
    source = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_metrics_name_timestamp', 'metric_name', 'timestamp'),
        Index('idx_metrics_schema_version', 'schema_version'),
        CheckConstraint('schema_version = \'v2\'', name='check_system_metrics_schema_v2'),
    )
