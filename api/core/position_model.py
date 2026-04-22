"""
Position model clarity - FIFO vs position-based closing rules.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

POSITION MODEL:
- Clear FIFO rules for position closing
- Position ID-based tracking
- Explicit closing logic for all scenarios
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, validator
from enum import Enum

from api.observability import log_structured


class PositionClosingMethod(Enum):
    FIFO = "fifo"  # First In, First Out
    LIFO = "lifo"  # Last In, First Out
    POSITION_ID = "position_id"  # Specific position targeting


class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIALLY_CLOSED = "partially_closed"


class Position(BaseModel):
    """Canonical position model."""
    position_id: str = Field(..., description="Unique position identifier")
    symbol: str = Field(..., min_length=1, max_length=10, description="Trading symbol")
    agent_id: str = Field(..., description="Agent identifier")
    status: PositionStatus = Field(..., description="Position status")
    
    # Position quantities
    original_quantity: Decimal = Field(..., gt=0, description="Original position size")
    current_quantity: Decimal = Field(..., ge=0, description="Current remaining quantity")
    
    # Price information
    entry_price: Decimal = Field(..., gt=0, description="Entry price")
    average_price: Decimal = Field(..., gt=0, description="Average price for partial fills")
    
    # Timing
    opened_at: datetime = Field(..., description="Position open timestamp")
    closed_at: Optional[datetime] = Field(None, description="Position close timestamp")
    
    # Metadata
    closing_method: PositionClosingMethod = Field(..., description="Position closing method")
    parent_trades: List[str] = Field(default_factory=list, description="Parent trade IDs")
    
    @validator('symbol')
    def validate_symbol(cls, v):
        if not v or not v.isalpha():
            raise ValueError(f"Invalid symbol: {v}")
        return v.upper()
    
    @validator('current_quantity')
    def validate_current_quantity(cls, v, values):
        if 'original_quantity' in values and v > values['original_quantity']:
            raise ValueError("Current quantity cannot exceed original quantity")
        return v
    
    @property
    def is_open(self) -> bool:
        """Check if position is open."""
        return self.status == PositionStatus.OPEN
    
    @property
    def is_closed(self) -> bool:
        """Check if position is closed."""
        return self.status == PositionStatus.CLOSED
    
    @property
    def is_partially_closed(self) -> bool:
        """Check if position is partially closed."""
        return self.status == PositionStatus.PARTIALLY_CLOSED
    
    @property
    def remaining_quantity(self) -> Decimal:
        """Get remaining quantity to close."""
        return self.current_quantity
    
    @property
    def closed_quantity(self) -> Decimal:
        """Get quantity already closed."""
        return self.original_quantity - self.current_quantity


class PositionManager:
    """Manages positions with clear closing rules."""
    
    def __init__(self, closing_method: PositionClosingMethod = PositionClosingMethod.FIFO):
        self.closing_method = closing_method
        self._positions: Dict[str, Position] = {}
    
    def open_position(
        self,
        position_id: str,
        symbol: str,
        agent_id: str,
        quantity: Decimal,
        entry_price: Decimal,
    ) -> Position:
        """Open a new position."""
        position = Position(
            position_id=position_id,
            symbol=symbol,
            agent_id=agent_id,
            status=PositionStatus.OPEN,
            original_quantity=quantity,
            current_quantity=quantity,
            entry_price=entry_price,
            average_price=entry_price,
            opened_at=datetime.now(timezone.utc),
            closing_method=self.closing_method,
        )
        
        self._positions[position_id] = position
        
        log_structured(
            "info",
            "position_opened",
            position_id=position_id,
            symbol=symbol,
            agent_id=agent_id,
            quantity=float(quantity),
            entry_price=float(entry_price),
            closing_method=self.closing_method.value,
        )
        
        return position
    
    def close_position(
        self,
        position_id: Optional[str] = None,
        symbol: Optional[str] = None,
        agent_id: Optional[str] = None,
        quantity: Optional[Decimal] = None,
        exit_price: Optional[Decimal] = None,
    ) -> List[Dict[str, Any]]:
        """Close position(s) based on closing method."""
        if self.closing_method == PositionClosingMethod.POSITION_ID:
            return self._close_by_position_id(position_id, quantity, exit_price)
        elif self.closing_method == PositionClosingMethod.FIFO:
            return self._close_fifo(symbol, agent_id, quantity, exit_price)
        elif self.closing_method == PositionClosingMethod.LIFO:
            return self._close_lifo(symbol, agent_id, quantity, exit_price)
        else:
            raise ValueError(f"Unsupported closing method: {self.closing_method}")
    
    def _close_by_position_id(
        self,
        position_id: str,
        quantity: Optional[Decimal],
        exit_price: Optional[Decimal],
    ) -> List[Dict[str, Any]]:
        """Close specific position by ID."""
        if position_id not in self._positions:
            raise ValueError(f"Position not found: {position_id}")
        
        position = self._positions[position_id]
        
        if not position.is_open and not position.is_partially_closed:
            raise ValueError(f"Position already closed: {position_id}")
        
        closing_quantity = quantity or position.current_quantity
        
        if closing_quantity > position.current_quantity:
            raise ValueError(f"Closing quantity {closing_quantity} exceeds remaining {position.current_quantity}")
        
        # Update position
        position.current_quantity -= closing_quantity
        
        if position.current_quantity == 0:
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.now(timezone.utc)
        else:
            position.status = PositionStatus.PARTIALLY_CLOSED
        
        log_structured(
            "info",
            "position_closed_by_id",
            position_id=position_id,
            closing_quantity=float(closing_quantity),
            remaining_quantity=float(position.current_quantity),
            exit_price=float(exit_price) if exit_price else None,
            status=position.status.value,
        )
        
        return [{
            "position_id": position_id,
            "symbol": position.symbol,
            "agent_id": position.agent_id,
            "closing_quantity": float(closing_quantity),
            "remaining_quantity": float(position.current_quantity),
            "exit_price": float(exit_price) if exit_price else None,
            "status": position.status.value,
        }]
    
    def _close_fifo(
        self,
        symbol: str,
        agent_id: str,
        quantity: Optional[Decimal],
        exit_price: Optional[Decimal],
    ) -> List[Dict[str, Any]]:
        """Close positions using FIFO method."""
        open_positions = [
            pos for pos in self._positions.values()
            if pos.symbol == symbol and 
               pos.agent_id == agent_id and 
               (pos.is_open or pos.is_partially_closed)
        ]
        
        # Sort by opened_at (oldest first)
        open_positions.sort(key=lambda x: x.opened_at)
        
        if not open_positions:
            raise ValueError(f"No open positions found for {symbol}")
        
        closing_quantity = quantity or sum(pos.current_quantity for pos in open_positions)
        results = []
        remaining_to_close = closing_quantity
        
        for position in open_positions:
            if remaining_to_close <= 0:
                break
            
            close_amount = min(remaining_to_close, position.current_quantity)
            
            position.current_quantity -= close_amount
            remaining_to_close -= close_amount
            
            if position.current_quantity == 0:
                position.status = PositionStatus.CLOSED
                position.closed_at = datetime.now(timezone.utc)
            else:
                position.status = PositionStatus.PARTIALLY_CLOSED
            
            results.append({
                "position_id": position.position_id,
                "symbol": position.symbol,
                "agent_id": position.agent_id,
                "closing_quantity": float(close_amount),
                "remaining_quantity": float(position.current_quantity),
                "exit_price": float(exit_price) if exit_price else None,
                "status": position.status.value,
                "fifo_order": position.opened_at.isoformat(),
            })
        
        log_structured(
            "info",
            "positions_closed_fifo",
            symbol=symbol,
            agent_id=agent_id,
            total_closing_quantity=float(closing_quantity),
            positions_affected=len(results),
        )
        
        return results
    
    def _close_lifo(
        self,
        symbol: str,
        agent_id: str,
        quantity: Optional[Decimal],
        exit_price: Optional[Decimal],
    ) -> List[Dict[str, Any]]:
        """Close positions using LIFO method."""
        open_positions = [
            pos for pos in self._positions.values()
            if pos.symbol == symbol and 
               pos.agent_id == agent_id and 
               (pos.is_open or pos.is_partially_closed)
        ]
        
        # Sort by opened_at (newest first)
        open_positions.sort(key=lambda x: x.opened_at, reverse=True)
        
        if not open_positions:
            raise ValueError(f"No open positions found for {symbol}")
        
        closing_quantity = quantity or sum(pos.current_quantity for pos in open_positions)
        results = []
        remaining_to_close = closing_quantity
        
        for position in open_positions:
            if remaining_to_close <= 0:
                break
            
            close_amount = min(remaining_to_close, position.current_quantity)
            
            position.current_quantity -= close_amount
            remaining_to_close -= close_amount
            
            if position.current_quantity == 0:
                position.status = PositionStatus.CLOSED
                position.closed_at = datetime.now(timezone.utc)
            else:
                position.status = PositionStatus.PARTIALLY_CLOSED
            
            results.append({
                "position_id": position.position_id,
                "symbol": position.symbol,
                "agent_id": position.agent_id,
                "closing_quantity": float(close_amount),
                "remaining_quantity": float(position.current_quantity),
                "exit_price": float(exit_price) if exit_price else None,
                "status": position.status.value,
                "lifo_order": position.opened_at.isoformat(),
            })
        
        log_structured(
            "info",
            "positions_closed_lifo",
            symbol=symbol,
            agent_id=agent_id,
            total_closing_quantity=float(closing_quantity),
            positions_affected=len(results),
        )
        
        return results
    
    def get_open_positions(self, symbol: Optional[str] = None, agent_id: Optional[str] = None) -> List[Position]:
        """Get open positions."""
        positions = [
            pos for pos in self._positions.values()
            if (pos.is_open or pos.is_partially_closed) and
               (symbol is None or pos.symbol == symbol) and
               (agent_id is None or pos.agent_id == agent_id)
        ]
        
        return positions
    
    def get_position_summary(self, symbol: Optional[str] = None, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Get position summary."""
        open_positions = self.get_open_positions(symbol, agent_id)
        
        total_exposure = sum(pos.current_quantity for pos in open_positions)
        total_positions = len(open_positions)
        
        return {
            "symbol_filter": symbol,
            "agent_id_filter": agent_id,
            "total_open_positions": total_positions,
            "total_exposure": float(total_exposure),
            "closing_method": self.closing_method.value,
            "positions": [
                {
                    "position_id": pos.position_id,
                    "symbol": pos.symbol,
                    "agent_id": pos.agent_id,
                    "quantity": float(pos.current_quantity),
                    "entry_price": float(pos.entry_price),
                    "status": pos.status.value,
                    "opened_at": pos.opened_at.isoformat(),
                }
                for pos in open_positions
            ],
            "summary_timestamp": datetime.now(timezone.utc).isoformat(),
        }
