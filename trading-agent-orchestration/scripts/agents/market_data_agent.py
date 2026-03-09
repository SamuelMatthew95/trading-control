"""
Stateless Market Data Agent
Narrow scope: Fetch and normalize market data
Intelligence lives in orchestration, not here
"""

from __future__ import annotations
import json
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from datetime import datetime


class MarketDataInput(BaseModel):
    """Strict input contract for market data agent"""
    symbol: str = Field(..., description="Stock ticker symbol")
    data_sources: list[str] = Field(default=["alpha_vantage", "yahoo_finance"], description="Preferred data sources")
    timeout_seconds: int = Field(default=30, description="Request timeout")


class MarketDataOutput(BaseModel):
    """Strict output contract for market data agent"""
    symbol: str = Field(..., description="Stock ticker symbol")
    price: float = Field(..., description="Current price")
    change: float = Field(..., description="Price change")
    change_percent: float = Field(..., description="Percentage change")
    volume: int = Field(..., description="Trading volume")
    timestamp: str = Field(..., description="Data timestamp")
    source: str = Field(..., description="Data source used")
    data_quality: str = Field(..., description="Data quality assessment")
    
    @validator('data_quality')
    def validate_quality(cls, v):
        allowed = ['high', 'medium', 'low']
        if v not in allowed:
            raise ValueError(f'data_quality must be one of {allowed}')
        return v


class MarketDataAgent:
    """Stateless market data worker agent"""
    
    def __init__(self):
        self.agent_id = "market_data_worker"
        self.version = "1.0.0"
        # No internal state - completely stateless
    
    async def execute(self, input_data: MarketDataInput) -> MarketDataOutput:
        """
        Execute market data fetch with strict I/O contracts
        No internal reasoning - just data retrieval and normalization
        """
        try:
            # Fetch from preferred sources in order
            raw_data = None
            source_used = None
            
            for source in input_data.data_sources:
                raw_data = await self._fetch_from_source(source, input_data.symbol)
                if raw_data:
                    source_used = source
                    break
            
            if not raw_data:
                raise ValueError(f"No data available for symbol {input_data.symbol}")
            
            # Normalize to standard output format
            normalized_data = self._normalize_data(raw_data, source_used)
            
            return MarketDataOutput(
                symbol=input_data.symbol,
                price=normalized_data['price'],
                change=normalized_data['change'],
                change_percent=normalized_data['change_percent'],
                volume=normalized_data['volume'],
                timestamp=normalized_data['timestamp'],
                source=source_used,
                data_quality=self._assess_data_quality(normalized_data, source_used)
            )
            
        except Exception as e:
            # Return structured error, not natural language
            raise ValueError(f"Market data fetch failed: {str(e)}")
    
    async def _fetch_from_source(self, source: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch raw data from specific source - no business logic here"""
        if source == "alpha_vantage":
            return await self._fetch_alpha_vantage(symbol)
        elif source == "yahoo_finance":
            return await self._fetch_yahoo_finance(symbol)
        return None
    
    async def _fetch_alpha_vantage(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch from Alpha Vantage - pure data retrieval"""
        # Implementation would go here
        # For now, return mock data
        return {
            "symbol": symbol,
            "price": 175.43,
            "change": 1.25,
            "change_percent": "0.72%",
            "volume": 1000000,
            "timestamp": "2024-01-15"
        }
    
    async def _fetch_yahoo_finance(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch from Yahoo Finance - pure data retrieval"""
        # Implementation would go here
        return {
            "symbol": symbol,
            "price": 175.45,
            "change": 1.27,
            "change_percent": 0.73,
            "volume": 1050000,
            "timestamp": datetime.now().isoformat()
        }
    
    def _normalize_data(self, raw_data: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Normalize data to standard format - deterministic transformation"""
        return {
            "price": float(raw_data["price"]),
            "change": float(raw_data["change"]),
            "change_percent": float(str(raw_data["change_percent"]).replace("%", "")),
            "volume": int(raw_data["volume"]),
            "timestamp": raw_data["timestamp"]
        }
    
    def _assess_data_quality(self, data: Dict[str, Any], source: str) -> str:
        """Assess data quality - deterministic rules"""
        if source == "alpha_vantage":
            return "high"
        elif source == "yahoo_finance":
            return "medium"
        else:
            return "low"


# Agent metadata for governance
AGENT_METADATA = {
    "agent_id": "market_data_worker",
    "version": "1.0.0",
    "scope": "market_data_retrieval",
    "stateless": True,
    "input_contract": "MarketDataInput",
    "output_contract": "MarketDataOutput",
    "permissions": ["read_market_data"],
    "max_execution_time_ms": 5000,
    "retry_count": 2
}
