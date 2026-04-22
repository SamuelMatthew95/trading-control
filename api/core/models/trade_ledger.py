"""
Trade Ledger model - the core of the transaction architecture.
This model pairs BUY and SELL signals to calculate real P&L.
"""

from __future__ import annotations

from decimal import Decimal

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


class TradeLedger(Base):
    __tablename__ = "trade_ledger"

    # Primary identification
    trade_id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    # Trade relationship tracking
    parent_trade_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trade_ledger.trade_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Links SELL to its corresponding BUY"
    )

    # Agent and strategy tracking
    agent_id = Column(String, nullable=False, index=True, comment="Which agent generated this trade")
    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Trade details
    symbol = Column(String, nullable=False, index=True)
    trade_type = Column(
        Enum("BUY", "SELL", name="trade_type"),
        nullable=False,
        index=True,
        comment="BUY opens position, SELL closes position"
    )

    # Pricing and quantity
    quantity = Column(Numeric(18, 8), nullable=False, comment="Number of shares/contracts")
    entry_price = Column(
        Numeric(18, 8),
        nullable=True,
        comment="Price at which trade was executed (filled for BUY, filled for SELL)"
    )
    exit_price = Column(
        Numeric(18, 8),
        nullable=True,
        comment="Only populated for SELL trades - the closing price"
    )

    # P&L calculation (only for closed trades)
    pnl_realized = Column(
        Numeric(18, 8),
        server_default="0",
        nullable=False,
        comment="Realized P&L = (exit_price - entry_price) * quantity"
    )

    # Trade status and execution mode
    status = Column(
        Enum("OPEN", "CLOSED", "CANCELLED", name="trade_status"),
        nullable=False,
        default="OPEN",
        index=True,
        comment="OPEN for BUY, CLOSED when paired with SELL"
    )

    execution_mode = Column(
        Enum("MOCK", "LIVE", name="execution_mode"),
        nullable=False,
        default="MOCK",
        index=True,
        comment="Whether this was a paper trade or real money"
    )

    # Confidence and metadata
    confidence_score = Column(
        Numeric(5, 2),
        nullable=True,
        comment="Agent's confidence in this trade (0-100)"
    )
    trade_metadata = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Additional trade context, signals, etc."
    )

    # System fields
    schema_version = Column(String, nullable=False, server_default="v3", index=True)
    source = Column(String, nullable=False, index=True, comment="System source identifier")
    trace_id = Column(String, nullable=True, index=True, comment="Trace ID for debugging")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    closed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the trade was closed (SELL filled)"
    )

    __table_args__ = (
        # Performance indexes
        Index("idx_trade_ledger_agent_created", "agent_id", "created_at"),
        Index("idx_trade_ledger_symbol_status", "symbol", "status"),
        Index("idx_trade_ledger_strategy_symbol", "strategy_id", "symbol"),
        Index("idx_trade_ledger_parent_trade", "parent_trade_id"),
        Index("idx_trade_ledger_execution_mode", "execution_mode"),
        Index("idx_trade_ledger_trace_id", "trace_id"),
        Index("idx_trade_ledger_schema_version", "schema_version"),

        # Business logic constraints
        CheckConstraint("schema_version = 'v3'", name="check_trade_ledger_schema_v3"),
        CheckConstraint("quantity > 0", name="check_quantity_positive"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="check_confidence_range"),
        CheckConstraint(
            "(trade_type = 'BUY' AND status IN ('OPEN', 'CANCELLED')) OR "
            "(trade_type = 'SELL' AND status IN ('CLOSED', 'CANCELLED'))",
            name="check_trade_type_status_consistency"
        ),
        CheckConstraint(
            "(trade_type = 'BUY' AND entry_price IS NOT NULL AND exit_price IS NULL) OR "
            "(trade_type = 'SELL' AND entry_price IS NOT NULL AND exit_price IS NOT NULL)",
            name="check_price_logic"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"TradeLedger(trade_id={self.trade_id}, "
            f"symbol={self.symbol}, "
            f"trade_type={self.trade_type}, "
            f"status={self.status}, "
            f"pnl_realized={self.pnl_realized})"
        )

    @property
    def is_buy(self) -> bool:
        return self.trade_type == "BUY"

    @property
    def is_sell(self) -> bool:
        return self.trade_type == "SELL"

    @property
    def is_open(self) -> bool:
        return self.status == "OPEN"

    @property
    def is_closed(self) -> bool:
        return self.status == "CLOSED"

    @property
    def is_profitable(self) -> bool | None:
        """Return True if profitable, False if loss, None if not closed."""
        if not self.is_closed or self.pnl_realized is None:
            return None
        return self.pnl_realized > 0

    def calculate_pnl(self) -> Decimal:
        """Calculate P&L for a SELL trade based on its parent BUY."""
        if self.trade_type != "SELL" or not self.entry_price or not self.exit_price:
            return Decimal("0")
        return (self.exit_price - self.entry_price) * self.quantity
