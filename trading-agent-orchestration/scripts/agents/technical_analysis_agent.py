"""
Stateless Technical Analysis Agent
Narrow scope: Calculate technical indicators from price data
Intelligence lives in orchestration, not here
"""

from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, validator
from datetime import datetime


class TechnicalAnalysisInput(BaseModel):
    """Strict input contract for technical analysis agent"""
    symbol: str = Field(..., description="Stock ticker symbol")
    price_data: List[Dict[str, Any]] = Field(..., description="Historical price data")
    indicators: list[str] = Field(default=["RSI", "MACD", "BB"], description="Indicators to calculate")
    time_period: int = Field(default=14, description="Analysis period")
    

class IndicatorResult(BaseModel):
    """Structured indicator result"""
    name: str = Field(..., description="Indicator name")
    value: float = Field(..., description="Indicator value")
    signal: str = Field(..., description="Trading signal")
    confidence: float = Field(..., description="Signal confidence")
    
    @validator('signal')
    def validate_signal(cls, v):
        allowed = ['buy', 'sell', 'hold', 'neutral']
        if v not in allowed:
            raise ValueError(f'signal must be one of {allowed}')
        return v
    
    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError('confidence must be between 0 and 1')
        return v


class TechnicalAnalysisOutput(BaseModel):
    """Strict output contract for technical analysis agent"""
    symbol: str = Field(..., description="Stock ticker symbol")
    indicators: List[IndicatorResult] = Field(..., description="Calculated indicators")
    overall_signal: str = Field(..., description="Overall trading signal")
    analysis_timestamp: str = Field(..., description="Analysis timestamp")
    data_quality: str = Field(..., description="Input data quality assessment")
    
    @validator('overall_signal')
    def validate_overall_signal(cls, v):
        allowed = ['strong_buy', 'buy', 'hold', 'sell', 'strong_sell']
        if v not in allowed:
            raise ValueError(f'overall_signal must be one of {allowed}')
        return v


class TechnicalAnalysisAgent:
    """Stateless technical analysis worker agent"""
    
    def __init__(self):
        self.agent_id = "technical_analysis_worker"
        self.version = "1.0.0"
        # No internal state - completely stateless
    
    async def execute(self, input_data: TechnicalAnalysisInput) -> TechnicalAnalysisOutput:
        """
        Execute technical analysis with strict I/O contracts
        No internal reasoning - just deterministic calculations
        """
        try:
            # Validate input data quality
            data_quality = self._assess_data_quality(input_data.price_data)
            if data_quality == "poor":
                raise ValueError("Insufficient data quality for analysis")
            
            # Calculate indicators deterministically
            indicators = []
            for indicator_name in input_data.indicators:
                if indicator_name == "RSI":
                    result = self._calculate_rsi(input_data.price_data, input_data.time_period)
                    indicators.append(result)
                elif indicator_name == "MACD":
                    result = self._calculate_macd(input_data.price_data)
                    indicators.append(result)
                elif indicator_name == "BB":
                    result = self._calculate_bollinger_bands(input_data.price_data, input_data.time_period)
                    indicators.append(result)
            
            # Generate overall signal
            overall_signal = self._generate_overall_signal(indicators)
            
            return TechnicalAnalysisOutput(
                symbol=input_data.symbol,
                indicators=indicators,
                overall_signal=overall_signal,
                analysis_timestamp=datetime.now().isoformat(),
                data_quality=data_quality
            )
            
        except Exception as e:
            # Return structured error, not natural language
            raise ValueError(f"Technical analysis failed: {str(e)}")
    
    def _assess_data_quality(self, price_data: List[Dict[str, Any]]) -> str:
        """Assess input data quality - deterministic rules"""
        if len(price_data) < 20:
            return "poor"
        elif len(price_data) < 50:
            return "fair"
        else:
            return "good"
    
    def _calculate_rsi(self, price_data: List[Dict[str, Any]], period: int) -> IndicatorResult:
        """Calculate RSI - deterministic algorithm"""
        if len(price_data) < period + 1:
            return IndicatorResult(
                name="RSI",
                value=50.0,
                signal="neutral",
                confidence=0.0
            )
        
        # Extract closing prices
        closes = [float(bar.get('close', 0)) for bar in price_data]
        
        # Calculate price changes
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        # Calculate average gains and losses
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # Generate signal based on RSI
        if rsi > 70:
            signal = "sell"
            confidence = min((rsi - 70) / 30, 1.0)
        elif rsi < 30:
            signal = "buy"
            confidence = min((30 - rsi) / 30, 1.0)
        else:
            signal = "hold"
            confidence = 0.5
        
        return IndicatorResult(
            name="RSI",
            value=rsi,
            signal=signal,
            confidence=confidence
        )
    
    def _calculate_macd(self, price_data: List[Dict[str, Any]]) -> IndicatorResult:
        """Calculate MACD - deterministic algorithm"""
        if len(price_data) < 26:
            return IndicatorResult(
                name="MACD",
                value=0.0,
                signal="neutral",
                confidence=0.0
            )
        
        closes = [float(bar.get('close', 0)) for bar in price_data]
        
        # Simple MACD calculation (simplified)
        ema_12 = sum(closes[-12:]) / 12
        ema_26 = sum(closes[-26:]) / 26
        macd_line = ema_12 - ema_26
        
        # Generate signal
        if macd_line > 0:
            signal = "buy"
            confidence = min(abs(macd_line) / 2.0, 1.0)
        else:
            signal = "sell"
            confidence = min(abs(macd_line) / 2.0, 1.0)
        
        return IndicatorResult(
            name="MACD",
            value=macd_line,
            signal=signal,
            confidence=confidence
        )
    
    def _calculate_bollinger_bands(self, price_data: List[Dict[str, Any]], period: int) -> IndicatorResult:
        """Calculate Bollinger Bands - deterministic algorithm"""
        if len(price_data) < period:
            return IndicatorResult(
                name="BB",
                value=0.0,
                signal="neutral",
                confidence=0.0
            )
        
        closes = [float(bar.get('close', 0)) for bar in price_data[-period:]]
        
        # Calculate moving average and standard deviation
        sma = sum(closes) / len(closes)
        variance = sum((price - sma) ** 2 for price in closes) / len(closes)
        std_dev = variance ** 0.5
        
        # Current price position relative to bands
        current_price = closes[-1]
        upper_band = sma + (2 * std_dev)
        lower_band = sma - (2 * std_dev)
        
        # Generate signal
        if current_price > upper_band:
            signal = "sell"
            confidence = min((current_price - upper_band) / std_dev, 1.0)
        elif current_price < lower_band:
            signal = "buy"
            confidence = min((lower_band - current_price) / std_dev, 1.0)
        else:
            signal = "hold"
            confidence = 0.5
        
        return IndicatorResult(
            name="BB",
            value=current_price - sma,  # Distance from SMA
            signal=signal,
            confidence=confidence
        )
    
    def _generate_overall_signal(self, indicators: List[IndicatorResult]) -> str:
        """Generate overall signal - deterministic aggregation"""
        if not indicators:
            return "hold"
        
        # Weight signals by confidence
        buy_weight = 0.0
        sell_weight = 0.0
        hold_weight = 0.0
        
        for indicator in indicators:
            weight = indicator.confidence
            if indicator.signal == "buy":
                buy_weight += weight
            elif indicator.signal == "sell":
                sell_weight += weight
            else:
                hold_weight += weight
        
        # Determine overall signal
        max_weight = max(buy_weight, sell_weight, hold_weight)
        
        if max_weight == 0:
            return "hold"
        elif buy_weight == max_weight:
            if buy_weight > 0.7:
                return "strong_buy"
            else:
                return "buy"
        elif sell_weight == max_weight:
            if sell_weight > 0.7:
                return "strong_sell"
            else:
                return "sell"
        else:
            return "hold"


# Agent metadata for governance
AGENT_METADATA = {
    "agent_id": "technical_analysis_worker",
    "version": "1.0.0",
    "scope": "technical_analysis",
    "stateless": True,
    "input_contract": "TechnicalAnalysisInput",
    "output_contract": "TechnicalAnalysisOutput",
    "permissions": ["read_price_data", "write_analysis_results"],
    "max_execution_time_ms": 2000,
    "retry_count": 1
}
