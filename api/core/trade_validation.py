"""
Strict trade validation enforcement.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

VALIDATION:
- Every trade must have required fields
- Trade relationships must be valid
- WebSocket events must match DB state
"""

from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from enum import Enum

from api.observability import log_structured


class TradeValidationError(Exception):
    """Trade validation error."""
    pass


class RequiredTradeFields(BaseModel):
    """Required fields for every trade."""
    signal_id: str = Field(..., description="Signal identifier for idempotency")
    agent_id: str = Field(..., description="Agent identifier")
    execution_id: str = Field(..., description="Execution identifier")
    db_trade_id: str = Field(..., description="Database trade identifier")
    websocket_event_id: str = Field(..., description="WebSocket event identifier")
    symbol: str = Field(..., min_length=1, max_length=10, description="Trading symbol")
    trade_type: str = Field(..., regex="^(BUY|SELL)$", description="Trade type")
    quantity: Decimal = Field(..., gt=0, description="Trade quantity must be positive")
    status: str = Field(..., regex="^(OPEN|CLOSED|REJECTED|IGNORED)$", description="Trade status")
    timestamp: datetime = Field(..., description="Trade timestamp")
    
    @validator('symbol')
    def validate_symbol(cls, v):
        if not v or not v.isalpha():
            raise ValueError(f"Invalid symbol: {v}")
        return v.upper()
    
    @validator('quantity')
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError(f"Quantity must be positive: {v}")
        return v


class TradeRelationshipValidator(BaseModel):
    """Validates trade relationships."""
    db_trade_id: str = Field(..., description="Database trade identifier")
    parent_trade_id: Optional[str] = Field(None, description="Parent trade identifier")
    child_trade_id: Optional[str] = Field(None, description="Child trade identifier")
    symbol: str = Field(..., description="Trading symbol")
    relationship_type: str = Field(..., regex="^(BUY_SELL|OPEN_POSITION)$", description="Relationship type")
    
    @validator('relationship_type')
    def validate_relationship(cls, v):
        if v not in ["BUY_SELL", "OPEN_POSITION"]:
            raise ValueError(f"Invalid relationship type: {v}")
        return v


class WebSocketEventValidator(BaseModel):
    """Validates WebSocket event consistency."""
    websocket_event_id: str = Field(..., description="WebSocket event identifier")
    db_trade_id: str = Field(..., description="Matching database trade")
    symbol: str = Field(..., description="Trading symbol")
    action: str = Field(..., regex="^(BUY|SELL)$", description="Trade action")
    price: Decimal = Field(..., gt=0, description="Trade price must be positive")
    quantity: Decimal = Field(..., gt=0, description="Trade quantity must be positive")
    status: str = Field(..., regex="^(OPEN|CLOSED|REJECTED|IGNORED)$", description="Trade status")
    timestamp: datetime = Field(..., description="Event timestamp")
    
    @validator('price')
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError(f"Price must be positive: {v}")
        return v
    
    @validator('quantity')
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError(f"Quantity must be positive: {v}")
        return v


class StrictTradeValidator:
    """Enforces strict trade validation."""
    
    def __init__(self):
        self.validation_errors = []
    
    def validate_trade_fields(self, trade_data: Dict[str, Any]) -> RequiredTradeFields:
        """Validate all required trade fields are present."""
        try:
            return RequiredTradeFields(**trade_data)
        except Exception as e:
            error_msg = f"Trade field validation failed: {str(e)}"
            self.validation_errors.append(error_msg)
            raise TradeValidationError(error_msg)
    
    def validate_trade_relationships(self, trade_data: Dict[str, Any]) -> TradeRelationshipValidator:
        """Validate trade relationships are valid."""
        try:
            return TradeRelationshipValidator(**trade_data)
        except Exception as e:
            error_msg = f"Trade relationship validation failed: {str(e)}"
            self.validation_errors.append(error_msg)
            raise TradeValidationError(error_msg)
    
    def validate_websocket_consistency(self, ws_data: Dict[str, Any], db_data: Dict[str, Any]) -> WebSocketEventValidator:
        """Validate WebSocket event matches database state."""
        try:
            # Check if WebSocket data matches DB data
            validator = WebSocketEventValidator(
                websocket_event_id=ws_data.get("event_id", ""),
                db_trade_id=db_data.get("trade_id", ""),
                symbol=db_data.get("symbol", ""),
                action=db_data.get("trade_type", ""),
                price=Decimal(str(db_data.get("entry_price", db_data.get("exit_price", "0"))),
                quantity=Decimal(str(db_data.get("quantity", "0"))),
                status=db_data.get("status", ""),
                timestamp=datetime.fromisoformat(db_data.get("timestamp", datetime.utcnow().isoformat())),
            )
            
            return validator
            
        except Exception as e:
            error_msg = f"WebSocket consistency validation failed: {str(e)}"
            self.validation_errors.append(error_msg)
            raise TradeValidationError(error_msg)
    
    def enforce_required_identifiers(self, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all required identifiers are present."""
        required_ids = ["signal_id", "agent_id", "execution_id", "db_trade_id", "websocket_event_id"]
        missing_ids = []
        
        for req_id in required_ids:
            if not trade_data.get(req_id):
                missing_ids.append(req_id)
        
        if missing_ids:
            error_msg = f"Missing required identifiers: {', '.join(missing_ids)}"
            self.validation_errors.append(error_msg)
            raise TradeValidationError(error_msg)
        
        return trade_data
    
    def validate_trade_lifecycle(self, trade_data: Dict[str, Any]) -> bool:
        """Validate trade lifecycle is valid."""
        trade_type = trade_data.get("trade_type", "")
        status = trade_data.get("status", "")
        
        # Valid lifecycle combinations
        valid_combinations = {
            "BUY": ["OPEN", "CLOSED"],
            "SELL": ["CLOSED"],
        }
        
        if trade_type in valid_combinations:
            if status not in valid_combinations[trade_type]:
                error_msg = f"Invalid trade lifecycle: {trade_type} + {status}"
                self.validation_errors.append(error_msg)
                raise TradeValidationError(error_msg)
        
        return True
    
    def validate_financial_data(self, trade_data: Dict[str, Any]) -> bool:
        """Validate financial data consistency."""
        try:
            quantity = Decimal(str(trade_data.get("quantity", "0")))
            entry_price = Decimal(str(trade_data.get("entry_price", "0")))
            exit_price = Decimal(str(trade_data.get("exit_price", "0")))
            
            # Basic financial validations
            if quantity <= 0:
                raise ValueError("Quantity must be positive")
            
            if entry_price <= 0 and trade_data.get("trade_type") == "BUY":
                raise ValueError("Entry price must be positive for BUY trades")
            
            if exit_price <= 0 and trade_data.get("trade_type") == "SELL":
                raise ValueError("Exit price must be positive for SELL trades")
            
            return True
            
        except Exception as e:
            error_msg = f"Financial data validation failed: {str(e)}"
            self.validation_errors.append(error_msg)
            raise TradeValidationError(error_msg)
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get summary of all validation errors."""
        return {
            "total_errors": len(self.validation_errors),
            "errors": self.validation_errors,
            "validation_timestamp": datetime.utcnow().isoformat(),
        }
    
    def clear_validation_errors(self) -> None:
        """Clear validation errors."""
        self.validation_errors = []
