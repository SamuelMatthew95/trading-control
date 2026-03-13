from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from api.database import Base


class TradeRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol (e.g., AAPL)")
    price: float = Field(..., gt=0, description="Current price of the asset")
    signals: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class TradeModel(BaseModel):
    date: str
    asset: str
    direction: str = Field(..., pattern="^(LONG|SHORT|FLAT)$")
    size: float = Field(..., gt=0)
    entry: float = Field(..., gt=0)
    stop: float = Field(..., gt=0)
    target: float = Field(..., gt=0)
    rr_ratio: float = Field(..., gt=0)
    exit: Optional[float] = None
    pnl: Optional[float] = None
    outcome: str = Field("OPEN", pattern="^(OPEN|WIN|LOSS)$")


class TradeDecision(BaseModel):
    symbol: str
    decision: str = Field(..., pattern="^(LONG|SHORT|FLAT)$")
    confidence: float = Field(..., ge=0, le=1)
    reasoning: str
    timestamp: datetime
    position_size: Optional[float] = Field(None, ge=0, le=1)
    risk_assessment: Optional[Dict[str, Any]] = None


class AgentPerformanceView(BaseModel):
    agent_name: str
    total_calls: int
    successful_calls: int
    avg_response_time: float
    accuracy_score: float
    improvement_areas: List[str] = Field(default_factory=list)


class OptionsGenerateRequest(BaseModel):
    flow: List[Dict[str, Any]] = Field(default_factory=list)
    screener: List[Dict[str, Any]] = Field(default_factory=list)
    learning_context: List[Dict[str, Any]] = Field(default_factory=list, alias="learningContext")


class ClosedPlayEvalRequest(BaseModel):
    play: Dict[str, Any]
    pnl: float
    recent_flow: List[Dict[str, Any]] = Field(default_factory=list, alias="recentFlow")


class LearningSummaryRequest(BaseModel):
    history: List[Dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: str
    timestamp: datetime


class HealthResponse(BaseModel):
    status: str
    orchestrator: bool
    database: str
    timestamp: datetime
    config_source: Optional[str] = None


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, nullable=False)
    asset = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    size = Column(Float, nullable=False)
    entry = Column(Float, nullable=False)
    stop = Column(Float, nullable=False)
    target = Column(Float, nullable=False)
    rr_ratio = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    outcome = Column(String, default="OPEN")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentPerformance(Base):
    __tablename__ = "agent_performance"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String, nullable=False, unique=True)
    total_calls = Column(Integer, default=0)
    successful_calls = Column(Integer, default=0)
    avg_response_time = Column(Float, default=0.0)
    accuracy_score = Column(Float, default=0.0)
    improvement_areas = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, nullable=False, index=True)
    decision_json = Column(Text, nullable=False)
    trace_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
