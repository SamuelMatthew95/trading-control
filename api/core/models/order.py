"""
Order model - clean architecture.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func, text

from .base import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_order_id = Column(String, unique=True, nullable=True, index=True)
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(Enum("buy", "sell", name="order_side"), nullable=False, index=True)
    order_type = Column(
        Enum("market", "limit", "stop", "stop_limit", name="order_type"), nullable=False
    )
    quantity = Column(Numeric(18, 8), nullable=False)
    price = Column(Numeric(18, 8), nullable=True)
    filled_quantity = Column(Numeric(18, 8), server_default="0", nullable=False)
    filled_price = Column(Numeric(18, 8), nullable=True)
    status = Column(
        Enum("pending", "filled", "cancelled", "rejected", name="order_status"),
        nullable=False,
        default="pending",
        index=True,
    )
    exchange = Column(String, nullable=True, index=True)
    commission = Column(Numeric(18, 8), server_default="0", nullable=False)
    order_metadata = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    schema_version = Column(String, nullable=False, server_default="v2", index=True)
    source = Column(String, nullable=False, index=True)
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
        Index("idx_orders_strategy_created", "strategy_id", "created_at"),
        Index("idx_orders_symbol_created", "symbol", "created_at"),
        Index("idx_orders_status_created", "status", "created_at"),
        Index("idx_orders_strategy_status", "strategy_id", "status"),
        Index("idx_orders_schema_version", "schema_version"),
        CheckConstraint("schema_version = 'v2'", name="check_orders_schema_v2"),
    )
