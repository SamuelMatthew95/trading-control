"""
Hard Risk agent enforcement - not advisory.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

HARD ENFORCEMENT:
- Risk output is mandatory, not advisory
- Executor CANNOT override risk constraints
- Final permission: ALLOW | DENY
- Strict position size limits
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from enum import Enum

from api.observability import log_structured


class RiskPermission(Enum):
    ALLOW = "allow"
    DENY = "deny"


class HardRiskDecision(BaseModel):
    """Hard risk decision - mandatory enforcement."""
    signal_id: str = Field(..., description="Signal identifier")
    agent_id: str = Field(..., description="Risk agent ID")
    symbol: str = Field(..., description="Trading symbol")
    
    # Risk assessment
    risk_score: float = Field(..., ge=0, le=100, description="Risk score 0-100")
    
    # Hard enforcement fields
    final_permission: RiskPermission = Field(..., description="Final permission - cannot be overridden")
    max_position_size: Optional[Decimal] = Field(None, gt=0, description="Max position size - enforced")
    adjusted_confidence: Optional[float] = Field(None, ge=0, le=100, description="Risk-adjusted confidence")
    
    # Metadata
    reasoning: str = Field(..., max_length=500, description="Risk reasoning")
    enforced_at: datetime = Field(default_factory=datetime.utcnow, description="Enforcement timestamp")
    
    @validator('risk_score')
    def validate_risk_score(cls, v):
        if not 0 <= v <= 100:
            raise ValueError("Risk score must be 0-100")
        return v
    
    @validator('max_position_size')
    def validate_max_position_size(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Max position size must be positive")
        return v
    
    @validator('adjusted_confidence')
    def validate_adjusted_confidence(cls, v):
        if v is not None and not 0 <= v <= 100:
            raise ValueError("Adjusted confidence must be 0-100")
        return v
    
    @property
    def is_allowed(self) -> bool:
        """Check if risk allows execution."""
        return self.final_permission == RiskPermission.ALLOW
    
    @property
    def is_denied(self) -> bool:
        """Check if risk denies execution."""
        return self.final_permission == RiskPermission.DENY
    
    def to_enforcement_payload(self) -> Dict[str, Any]:
        """Convert to enforcement payload."""
        return {
            "signal_id": self.signal_id,
            "agent_id": self.agent_id,
            "symbol": self.symbol,
            "final_permission": self.final_permission.value,
            "max_position_size": float(self.max_position_size) if self.max_position_size else None,
            "adjusted_confidence": self.adjusted_confidence,
            "risk_score": self.risk_score,
            "reasoning": self.reasoning,
            "enforced_at": self.enforced_at.isoformat(),
            "enforcement_type": "hard_risk_enforcement",
        }


class HardRiskEnforcer:
    """Hard risk enforcement - cannot be overridden."""
    
    def __init__(self, session):
        self.session = session
        self._risk_rules = self._load_risk_rules()
    
    def _load_risk_rules(self) -> Dict[str, Any]:
        """Load risk enforcement rules."""
        return {
            "max_risk_score": 80,  # Above this = auto-deny
            "default_max_position": Decimal("10.0"),  # Default position limit
            "confidence_reduction_factor": 0.7,  # Reduce confidence by this factor
            "mandatory_fields": ["signal_id", "symbol", "risk_score", "final_permission"],
        }
    
    async def assess_and_enforce(
        self, 
        analyst_output: Dict[str, Any],
        execution_intent: Dict[str, Any]
    ) -> HardRiskDecision:
        """
        Assess risk and enforce hard constraints.
        
        This is MANDATORY enforcement - executor cannot override.
        """
        try:
            # Extract data
            signal_id = analyst_output.get("signal_id", "")
            symbol = analyst_output.get("symbol", "")
            original_confidence = analyst_output.get("confidence", 0)
            
            # Calculate risk factors
            agent_performance = await self._get_agent_performance(analyst_output.get("agent_id", ""))
            market_volatility = await self._get_market_volatility(symbol)
            current_exposure = await self._get_current_exposure(symbol, analyst_output.get("agent_id", ""))
            
            # Calculate risk score
            risk_score = self._calculate_risk_score(
                agent_performance,
                market_volatility,
                current_exposure,
                original_confidence
            )
            
            # Apply hard rules
            final_permission, max_position_size, adjusted_confidence = self._apply_hard_rules(
                risk_score,
                execution_intent,
                current_exposure
            )
            
            # Create hard decision
            decision = HardRiskDecision(
                signal_id=signal_id,
                agent_id="risk_enforcer_001",
                symbol=symbol,
                risk_score=risk_score,
                final_permission=final_permission,
                max_position_size=max_position_size,
                adjusted_confidence=adjusted_confidence,
                reasoning=self._generate_reasoning(risk_score, final_permission, max_position_size),
            )
            
            # Store for audit
            await self._store_risk_decision(decision)
            
            log_structured(
                "info",
                "hard_risk_enforced",
                signal_id=signal_id,
                symbol=symbol,
                final_permission=final_permission.value,
                max_position_size=float(max_position_size) if max_position_size else None,
                risk_score=risk_score,
            )
            
            return decision
            
        except Exception as e:
            log_structured(
                "error",
                "hard_risk_enforcement_error",
                signal_id=analyst_output.get("signal_id", "unknown"),
                error=str(e),
                exc_info=True,
            )
            
            # Auto-deny on error
            return HardRiskDecision(
                signal_id=analyst_output.get("signal_id", "error"),
                agent_id="risk_enforcer_001",
                symbol=analyst_output.get("symbol", "ERROR"),
                risk_score=100.0,  # Max risk on error
                final_permission=RiskPermission.DENY,
                max_position_size=Decimal("0"),
                adjusted_confidence=0,
                reasoning=f"Risk enforcement failed: {str(e)}",
            )
    
    def _calculate_risk_score(
        self,
        agent_performance: Dict[str, Any],
        market_volatility: float,
        current_exposure: Decimal,
        original_confidence: float
    ) -> float:
        """Calculate comprehensive risk score."""
        # Agent performance factor (0-40 points)
        performance_score = agent_performance.get("win_rate", 50) * 0.4
        
        # Market volatility factor (0-30 points)
        volatility_score = min(market_volatility * 30, 30)
        
        # Current exposure factor (0-20 points)
        exposure_score = min(float(current_exposure) * 2, 20)
        
        # Confidence factor (0-10 points)
        confidence_score = (100 - original_confidence) * 0.1
        
        total_risk = performance_score + volatility_score + exposure_score + confidence_score
        return min(total_risk, 100)
    
    def _apply_hard_rules(
        self,
        risk_score: float,
        execution_intent: Dict[str, Any],
        current_exposure: Decimal
    ) -> tuple[RiskPermission, Optional[Decimal], Optional[float]]:
        """Apply hard risk rules."""
        rules = self._risk_rules
        
        # Rule 1: Auto-deny high risk
        if risk_score > rules["max_risk_score"]:
            return RiskPermission.DENY, Decimal("0"), 0
        
        # Rule 2: Position size limits
        requested_quantity = Decimal(str(execution_intent.get("quantity", "1")))
        max_position = rules["default_max_position"]
        
        if requested_quantity > max_position:
            return RiskPermission.DENY, max_position, None
        
        # Rule 3: Confidence adjustment
        original_confidence = execution_intent.get("confidence", 100)
        adjusted_confidence = original_confidence * rules["confidence_reduction_factor"]
        
        # Rule 4: Exposure limits
        if current_exposure + requested_quantity > max_position:
            return RiskPermission.DENY, max_position - current_exposure, adjusted_confidence
        
        # Allow with constraints
        return RiskPermission.ALLOW, max_position, adjusted_confidence
    
    def _generate_reasoning(
        self,
        risk_score: float,
        final_permission: RiskPermission,
        max_position_size: Optional[Decimal]
    ) -> str:
        """Generate reasoning for risk decision."""
        if final_permission == RiskPermission.DENY:
            if risk_score > self._risk_rules["max_risk_score"]:
                return f"High risk score ({risk_score}) exceeds threshold ({self._risk_rules['max_risk_score']})"
            else:
                return f"Position size or exposure limits exceeded"
        else:
            return f"Risk acceptable (score: {risk_score}). Max position: {max_position_size}"
    
    async def _get_agent_performance(self, agent_id: str) -> Dict[str, Any]:
        """Get agent performance metrics."""
        # Mock implementation - would query DB in production
        return {
            "win_rate": 65.0,
            "total_trades": 100,
            "avg_pnl": 50.0,
        }
    
    async def _get_market_volatility(self, symbol: str) -> float:
        """Get market volatility for symbol."""
        # Mock implementation - would query market data in production
        return 0.3  # 30% volatility
    
    async def _get_current_exposure(self, symbol: str, agent_id: str) -> Decimal:
        """Get current exposure for agent/symbol."""
        # Mock implementation - would query positions in production
        return Decimal("2.0")
    
    async def _store_risk_decision(self, decision: HardRiskDecision) -> None:
        """Store risk decision for audit trail."""
        # In production, this would store in database
        log_structured(
            "info",
            "risk_decision_stored",
            signal_id=decision.signal_id,
            final_permission=decision.final_permission.value,
            max_position_size=float(decision.max_position_size) if decision.max_position_size else None,
        )
    
    async def validate_executor_compliance(
        self,
        execution_intent: Dict[str, Any],
        risk_decision: HardRiskDecision
    ) -> Dict[str, Any]:
        """
        Validate executor compliance with risk decision.
        
        Executor CANNOT override risk constraints.
        """
        try:
            # Check permission compliance
            if risk_decision.is_denied:
                return {
                    "compliant": False,
                    "violation": "executor_overrode_risk_deny",
                    "risk_permission": risk_decision.final_permission.value,
                    "executor_action": execution_intent.get("action", "unknown"),
                }
            
            # Check position size compliance
            requested_quantity = Decimal(str(execution_intent.get("quantity", "1")))
            if risk_decision.max_position_size and requested_quantity > risk_decision.max_position_size:
                return {
                    "compliant": False,
                    "violation": "executor_exceeded_position_limit",
                    "max_allowed": float(risk_decision.max_position_size),
                    "requested": float(requested_quantity),
                }
            
            # Check confidence compliance
            if risk_decision.adjusted_confidence:
                executor_confidence = execution_intent.get("confidence", 100)
                if executor_confidence > risk_decision.adjusted_confidence:
                    return {
                        "compliant": False,
                        "violation": "executor_ignored_confidence_adjustment",
                        "max_allowed": risk_decision.adjusted_confidence,
                        "requested": executor_confidence,
                    }
            
            return {
                "compliant": True,
                "validation": "executor_complies_with_risk_constraints",
            }
            
        except Exception as e:
            log_structured(
                "error",
                "executor_compliance_validation_error",
                signal_id=execution_intent.get("signal_id", "unknown"),
                error=str(e),
                exc_info=True,
            )
            
            return {
                "compliant": False,
                "violation": "validation_error",
                "error": str(e),
            }
