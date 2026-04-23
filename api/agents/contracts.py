"""
Strict agent contract and schema validation layer.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

AGENT ROLES:
- Analyst: Only outputs bias + confidence, CANNOT trade
- Risk: Can block signals, can reduce size/confidence, CANNOT trade
- Executor: ONLY role allowed to emit BUY/SELL signals
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, validator

from api.observability import log_structured


class AgentRole(Enum):
    ANALYST = "analyst"
    RISK = "risk"
    EXECUTOR = "executor"


class AgentPermission(Enum):
    READ_POSITIONS = "read_positions"
    READ_TRADES = "read_trades"
    ANALYZE_MARKET = "analyze_market"
    GENERATE_SIGNALS = "generate_signals"
    EXECUTE_TRADES = "execute_trades"
    BLOCK_SIGNALS = "block_signals"
    MODIFY_CONFIDENCE = "modify_confidence"


class AgentOutput(BaseModel):
    """Strict agent output contract."""

    signal_id: str = Field(..., description="Unique signal identifier for idempotency")
    agent_id: str = Field(..., description="Agent identifier")
    role: AgentRole = Field(..., description="Agent role")
    symbol: str = Field(..., min_length=1, max_length=10, description="Trading symbol")
    action: str = Field(..., pattern="^(BUY|SELL|HOLD)$", description="Trading action")
    confidence: float | None = Field(None, ge=0, le=100, description="Confidence score 0-100")
    reason: str | None = Field(None, max_length=500, description="Decision reason")
    timestamp: datetime = Field(..., description="Signal timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional metadata")

    @validator("symbol")
    def validate_symbol(self, v):
        """Validate trading symbol format."""
        if not v or not v.isalpha():
            raise ValueError(f"Invalid symbol: {v}")
        return v.upper()

    @validator("action")
    def validate_action(self, v):
        """Validate trading action."""
        if v not in ["BUY", "SELL", "HOLD"]:
            raise ValueError(f"Invalid action: {v}")
        return v

    @validator("confidence")
    def validate_confidence(self, v):
        """Validate confidence range."""
        if v is not None and (v < 0 or v > 100):
            raise ValueError(f"Confidence must be 0-100: {v}")
        return v


class AgentPermissions(BaseModel):
    """Agent permission configuration."""

    agent_id: str
    role: AgentRole
    permissions: list[AgentPermission]
    rate_limits: dict[str, int] = Field(default_factory=dict)
    max_position_size: Decimal | None = Field(None, gt=0)
    allowed_symbols: list[str] | None = None
    risk_limits: dict[str, Any] = Field(default_factory=dict)


class AgentOutputValidator:
    """Validates agent output against strict contract."""

    def __init__(self, permissions: dict[str, AgentPermissions]):
        self.permissions = permissions
        self.validation_errors = []

    def validate_output(self, agent_id: str, output: dict[str, Any]) -> AgentOutput:
        """Validate agent output against contract and permissions."""
        try:
            # Create AgentOutput instance for validation
            validated_output = AgentOutput(**output)

            # Check agent permissions
            agent_perms = self.permissions.get(agent_id)
            if not agent_perms:
                raise ValueError(f"Agent {agent_id} not found in permissions")

            # Role-based validation
            if agent_perms.role == AgentRole.ANALYST:
                return self._validate_analyst_output(validated_output)
            if agent_perms.role == AgentRole.RISK:
                return self._validate_risk_output(validated_output, agent_perms)
            if agent_perms.role == AgentRole.EXECUTOR:
                return self._validate_executor_output(validated_output, agent_perms)
            raise ValueError(f"Unknown agent role: {agent_perms.role}")

        except Exception as e:
            log_structured(
                "error",
                "agent_output_validation_failed",
                agent_id=agent_id,
                error=str(e),
            )
            raise ValueError(f"Agent output validation failed: {str(e)}") from e

    def _validate_analyst_output(self, output: AgentOutput) -> AgentOutput:
        """Validate analyst output - can only analyze, cannot trade."""
        if output.action not in ["HOLD", "ANALYZE"]:
            raise ValueError("Analyst agents can only output HOLD or ANALYZE actions")

        # Analysts cannot have high confidence for trading actions
        if output.action == "BUY" or output.action == "SELL":
            if output.confidence and output.confidence > 70:
                raise ValueError("Analyst agents cannot have >70% confidence for trading signals")

        return output

    def _validate_risk_output(
        self, output: AgentOutput, permissions: AgentPermissions
    ) -> AgentOutput:
        """Validate risk agent output - can block or modify, cannot execute directly."""
        if output.action == "BUY" or output.action == "SELL":
            raise ValueError("Risk agents cannot directly execute trades - only BLOCK or MODIFY")

        # Risk agents can reduce confidence but not below minimum
        if output.confidence is not None and output.confidence < 10:
            raise ValueError("Risk agents cannot set confidence below 10%")

        return output

    def _validate_executor_output(
        self, output: AgentOutput, permissions: AgentPermissions
    ) -> AgentOutput:
        """Validate executor output - only role that can execute trades."""
        if output.action not in ["BUY", "SELL"]:
            raise ValueError("Executor agents can only output BUY or SELL actions")

        # Check position size limits
        if permissions.max_position_size and output.metadata.get("quantity"):
            quantity = Decimal(str(output.metadata.get("quantity", "1")))
            if quantity > permissions.max_position_size:
                raise ValueError(
                    f"Position size {quantity} exceeds limit {permissions.max_position_size}"
                )

        # Check symbol permissions
        if permissions.allowed_symbols and output.symbol not in permissions.allowed_symbols:
            raise ValueError(f"Symbol {output.symbol} not in allowed symbols list")

        return output


class AgentMemoryDiscipline:
    """Enforces DB-only memory model for agents."""

    def __init__(self, session):
        self.session = session

    async def get_agent_positions(self, agent_id: str) -> dict[str, Any]:
        """Get agent's current positions from DB only."""
        from sqlalchemy import select

        from api.core.models.trade_ledger import TradeLedger

        stmt = select(TradeLedger).where(
            TradeLedger.agent_id == agent_id, TradeLedger.status == "OPEN"
        )

        result = await self.session.execute(stmt)
        positions = result.scalars().all()

        return {
            "positions": [
                {
                    "symbol": pos.symbol,
                    "quantity": float(pos.quantity),
                    "entry_price": float(pos.entry_price),
                }
                for pos in positions
            ],
            "source": "database_only",
        }

    async def check_agent_idempotency(self, agent_id: str, signal_id: str) -> bool:
        """Check if agent already processed this signal."""
        from sqlalchemy import select

        from api.core.models.trade_ledger import TradeLedger

        stmt = select(TradeLedger).where(
            TradeLedger.agent_id == agent_id, TradeLedger.trace_id == signal_id
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
