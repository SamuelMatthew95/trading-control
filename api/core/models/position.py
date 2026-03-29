"""
Position model - clean architecture.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func, text

from .base import Base


class Position(Base):
    __tablename__ = 'positions'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    strategy_id = Column(UUID(as_uuid=True), ForeignKey('strategies.id', ondelete='CASCADE'), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    quantity = Column(Numeric(18, 8), nullable=False)
    avg_cost = Column(Numeric(18, 8), nullable=False)
    market_value = Column(Numeric(18, 8), nullable=False)
    unrealized_pnl = Column(Numeric(18, 8), server_default="0", nullable=False)
    last_price = Column(Numeric(18, 8), nullable=True)
    position_metadata = Column(MutableDict.as_mutable(JSONB), nullable=False, server_default=text("'{}'::jsonb"))
    schema_version = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_positions_strategy_symbol', 'strategy_id', 'symbol', unique=True),
        Index('idx_positions_schema_version', 'schema_version'),
        CheckConstraint('schema_version = \'v2\'', name='check_positions_schema_v2'),
    )
