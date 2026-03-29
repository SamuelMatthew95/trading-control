"""
Strategy model - clean architecture.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, Enum, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func, text

from .base import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    config = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    schema_version = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    status = Column(
        Enum("active", "inactive", "archived", name="strategy_status"),
        nullable=False,
        default="active",
        index=True,
    )
    created_by = Column(String, nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_strategies_status_updated", "status", "updated_at"),
        Index("idx_strategies_schema_version", "schema_version"),
        CheckConstraint("schema_version = 'v2'", name="check_strategies_schema_v2"),
    )
