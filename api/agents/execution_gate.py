"""
Execution gating layer to prevent bad trades.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

GATING LAYER:
- Validates agent outputs before execution
- Enforces role-based permissions
- Blocks invalid or risky trades
- Provides deterministic decision flow
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from api.agents.contracts import AgentOutputValidator, AgentPermissions, AgentRole
from api.core.events import SignalEvent
from api.observability import log_structured


class GateDecision(Enum):
    APPROVE = "approve"
    BLOCK = "block"
    MODIFY = "modify"
    REJECT = "reject"


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class GateResult:
    """Result of execution gate validation."""

    decision: GateDecision
    reason: str | None = None
    modified_signal: dict[str, Any] | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    confidence_adjustment: float | None = None


class ExecutionGate:
    """Execution gating layer to prevent bad trades."""

    def __init__(self, session):
        self.session = session
        self.validator = AgentOutputValidator({})
        self._recent_decisions = []

    async def evaluate_signal(
        self, signal: SignalEvent, agent_permissions: AgentPermissions
    ) -> GateResult:
        """Evaluate signal against execution gate rules."""

        try:
            # Step 1: Basic signal validation
            validation_result = self.validator.enforce_signal_contract(signal.dict())
            if validation_result.get("validation_failed"):
                return GateResult(
                    decision=GateDecision.REJECT,
                    reason=f"Signal validation failed: {validation_result.get('error')}",
                    risk_level=RiskLevel.CRITICAL,
                )

            # Step 2: Role-based permission check
            if agent_permissions.role == AgentRole.ANALYST:
                return self._evaluate_analyst_signal(signal, agent_permissions)
            if agent_permissions.role == AgentRole.RISK:
                return self._evaluate_risk_signal(signal, agent_permissions)
            if agent_permissions.role == AgentRole.EXECUTOR:
                return self._evaluate_executor_signal(signal, agent_permissions)
            return GateResult(
                decision=GateDecision.REJECT,
                reason=f"Unknown agent role: {agent_permissions.role}",
                risk_level=RiskLevel.CRITICAL,
            )

        except Exception as e:
            log_structured(
                "error",
                "gate_evaluation_error",
                signal_id=signal.signal_id,
                error=str(e),
            )
            return GateResult(
                decision=GateDecision.REJECT,
                reason=f"Gate evaluation error: {str(e)}",
                risk_level=RiskLevel.CRITICAL,
            )

    def _evaluate_analyst_signal(
        self, signal: SignalEvent, permissions: AgentPermissions
    ) -> GateResult:
        """Evaluate analyst agent signal - can only analyze, not trade."""
        if signal.action not in ["HOLD", "ANALYZE"]:
            return GateResult(
                decision=GateDecision.REJECT,
                reason="Analyst agents can only output HOLD or ANALYZE actions",
                risk_level=RiskLevel.HIGH,
            )

        # Analysts cannot have high confidence for trading signals
        if signal.action in ["BUY", "SELL"] and signal.confidence and signal.confidence > 70:
            return GateResult(
                decision=GateDecision.MODIFY,
                reason="Analyst confidence too high for trading signal",
                confidence_adjustment=min(50, signal.confidence),
                risk_level=RiskLevel.MEDIUM,
            )

        return GateResult(
            decision=GateDecision.APPROVE,
            reason="Analyst signal approved",
            risk_level=RiskLevel.LOW,
        )

    def _evaluate_risk_signal(
        self, signal: SignalEvent, permissions: AgentPermissions
    ) -> GateResult:
        """Evaluate risk agent signal - can block or modify."""

        # Check if risk agent is allowed to trade this symbol
        if permissions.allowed_symbols and signal.symbol not in permissions.allowed_symbols:
            return GateResult(
                decision=GateDecision.BLOCK,
                reason=f"Symbol {signal.symbol} not in allowed symbols list",
                risk_level=RiskLevel.HIGH,
            )

        # Check position size limits
        if permissions.max_position_size and signal.metadata.get("quantity"):
            quantity = Decimal(str(signal.metadata.get("quantity", "1")))
            if quantity > permissions.max_position_size:
                return GateResult(
                    decision=GateDecision.MODIFY,
                    reason=f"Position size {quantity} exceeds limit {permissions.max_position_size}",
                    modified_signal={
                        **signal.dict(),
                        "metadata": {
                            **signal.metadata,
                            "quantity": str(permissions.max_position_size),
                        },
                    },
                    risk_level=RiskLevel.MEDIUM,
                )

        # Risk agents can reduce confidence but not below minimum
        if signal.confidence is not None and signal.confidence < 10:
            return GateResult(
                decision=GateDecision.MODIFY,
                reason="Risk agent confidence below minimum 10%",
                confidence_adjustment=10,
                risk_level=RiskLevel.MEDIUM,
            )

        return GateResult(
            decision=GateDecision.APPROVE,
            reason="Risk agent signal approved",
            risk_level=RiskLevel.LOW,
        )

    def _evaluate_executor_signal(
        self, signal: SignalEvent, permissions: AgentPermissions
    ) -> GateResult:
        """Evaluate executor agent signal - only role that can execute trades."""
        if signal.action not in ["BUY", "SELL"]:
            return GateResult(
                decision=GateDecision.REJECT,
                reason="Executor agents can only output BUY or SELL actions",
                risk_level=RiskLevel.CRITICAL,
            )

        # Check position size limits
        if permissions.max_position_size and signal.metadata.get("quantity"):
            quantity = Decimal(str(signal.metadata.get("quantity", "1")))
            if quantity > permissions.max_position_size:
                return GateResult(
                    decision=GateDecision.MODIFY,
                    reason=f"Executor position size {quantity} exceeds limit {permissions.max_position_size}",
                    modified_signal={
                        **signal.dict(),
                        "metadata": {
                            **signal.metadata,
                            "quantity": str(permissions.max_position_size),
                        },
                    },
                    risk_level=RiskLevel.MEDIUM,
                )

        # Executors must have reasonable confidence
        if signal.confidence is not None and signal.confidence > 95:
            return GateResult(
                decision=GateDecision.MODIFY,
                reason="Executor confidence above 95% - requires manual review",
                confidence_adjustment=95,
                risk_level=RiskLevel.MEDIUM,
            )

        return GateResult(
            decision=GateDecision.APPROVE,
            reason="Executor signal approved",
            risk_level=RiskLevel.LOW,
        )

    async def apply_gate_modifications(
        self, signal: SignalEvent, gate_result: GateResult
    ) -> SignalEvent:
        """Apply gate modifications to signal."""
        if gate_result.modified_signal:
            return SignalEvent(
                signal_id=signal.signal_id,
                agent_id=signal.agent_id,
                symbol=signal.symbol,
                action=signal.action,
                price=signal.price,
                confidence=gate_result.confidence_adjustment or signal.confidence,
                timestamp=signal.timestamp,
                metadata=gate_result.modified_signal.get("metadata", signal.metadata),
            )

        return signal

    def log_gate_decision(self, signal: SignalEvent, gate_result: GateResult) -> None:
        """Log gate decision for audit trail."""
        log_structured(
            "info",
            "execution_gate_decision",
            signal_id=signal.signal_id,
            agent_id=signal.agent_id,
            decision=gate_result.decision.value,
            reason=gate_result.reason,
            risk_level=gate_result.risk_level.value,
            original_action=signal.action.value,
            original_confidence=signal.confidence,
            modified_confidence=gate_result.confidence_adjustment,
        )
