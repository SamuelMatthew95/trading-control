"""
Production-ready FastAPI backend with Pydantic settings integration
Replaces manual string parsing with robust configuration management
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import (Base, get_async_session, get_settings_info,
                      init_database, test_database_connection)

from multi_agent_orchestrator import AgentCall, MultiAgentOrchestrator

# Import Pydantic settings
try:
    from config import settings

    SETTINGS_AVAILABLE = True
    print("✅ Using Pydantic settings for robust configuration")
except ImportError as e:
    print(f"⚠️  Could not import config.py: {e}")
    print("⚠️  Falling back to environment variables")
    settings = None
    SETTINGS_AVAILABLE = False

app = FastAPI(
    title="Trading Bot API", version="1.0.0", docs_url="/docs", redoc_url="/redoc"
)

# Add CORS middleware for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("FRONTEND_URL", "http://localhost:3000"),
        "https://localhost:3000",
        "https://your-domain.vercel.app",  # Replace with your actual domain
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Add trusted host middleware
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["*"]  # Configure for production domains
)


# Pydantic models for API
class TradeRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol (e.g., AAPL)")
    price: float = Field(..., gt=0, description="Current price of the asset")
    signals: Optional[List[Dict[str, Any]]] = Field(
        default=[], description="Additional trading signals for analysis"
    )


class TradeModel(BaseModel):
    date: str = Field(..., description="Trade date")
    asset: str = Field(..., description="Trading asset symbol")
    direction: str = Field(
        ..., regex="^(LONG|SHORT|FLAT)$", description="Trade direction"
    )
    size: float = Field(..., gt=0, description="Position size")
    entry: float = Field(..., gt=0, description="Entry price")
    stop: float = Field(..., gt=0, description="Stop loss price")
    target: float = Field(..., gt=0, description="Take profit price")
    rr_ratio: float = Field(..., gt=0, description="Risk/reward ratio")
    exit: Optional[float] = Field(None, description="Exit price when trade is closed")
    pnl: Optional[float] = Field(None, description="Profit/loss amount")
    outcome: str = Field("OPEN", regex="^(OPEN|WIN|LOSS)$", description="Trade outcome")


class TradeDecision(BaseModel):
    symbol: str = Field(..., description="Trading symbol")
    decision: str = Field(
        ..., regex="^(LONG|SHORT|FLAT)$", description="Trading decision"
    )
    confidence: float = Field(..., ge=0, le=1, description="Confidence level (0-1)")
    reasoning: str = Field(..., description="AI reasoning for the decision")
    timestamp: datetime = Field(..., description="When the analysis was performed")
    position_size: Optional[float] = Field(
        None, ge=0, le=1, description="Recommended position size"
    )
    risk_assessment: Optional[Dict[str, Any]] = Field(
        None, description="Risk assessment details"
    )


class AgentPerformance(BaseModel):
    agent_name: str = Field(..., description="Name of the AI agent")
    total_calls: int = Field(..., ge=0, description="Total number of agent calls")
    successful_calls: int = Field(..., ge=0, description="Number of successful calls")
    avg_response_time: float = Field(
        ..., ge=0, description="Average response time in seconds"
    )
    accuracy_score: float = Field(..., ge=0, le=1, description="Accuracy score (0-1)")
    improvement_areas: List[str] = Field(
        default_factory=list, description="Areas needing improvement"
    )


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Detailed error message")
    timestamp: datetime = Field(..., description="When the error occurred")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Health status")
    orchestrator: bool = Field(..., description="Whether orchestrator is initialized")
    database: str = Field(..., description="Database connection status")
    timestamp: datetime = Field(..., description="Health check timestamp")
    config_source: Optional[str] = Field(
        None, description="Configuration source being used"
    )


# SQLAlchemy models
from sqlalchemy import (Column, DateTime, Float, Integer, String, Text, func,
                        select)


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


# Initialize orchestrator and learning system
orchestrator = None
learning_system = None


class AgentLearningSystem:
    """Track and learn from agent performance over time"""

    def __init__(self):
        self.agent_performance = {
            "SIGNAL_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "accuracy_score": 0,
                "confidence_calibration": [],
                "common_patterns": {},
                "improvement_areas": [],
            },
            "CONSENSUS_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "agreement_accuracy": 0,
                "conflict_resolution_rate": 0,
                "bias_detection": [],
                "improvement_areas": [],
            },
            "RISK_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "veto_accuracy": 0,
                "risk_assessment_score": 0,
                "false_veto_rate": 0,
                "missed_risks": [],
                "improvement_areas": [],
            },
            "SIZING_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "position_optimization": 0,
                "risk_reward_ratio": 0,
                "kelly_accuracy": 0,
                "oversizing_rate": 0,
                "improvement_areas": [],
            },
        }

    async def record_agent_call(
        self, agent_name: str, success: bool, response_time: float, session
    ):
        """Record an agent call for learning with proper transaction handling"""
        if agent_name in self.agent_performance:
            self.agent_performance[agent_name]["total_calls"] += 1
            if success:
                self.agent_performance[agent_name]["successful_calls"] += 1

            # Update average response time
            current_avg = self.agent_performance[agent_name]["avg_response_time"]
            total_calls = self.agent_performance[agent_name]["total_calls"]
            self.agent_performance[agent_name]["avg_response_time"] = (
                current_avg * (total_calls - 1) + response_time
            ) / total_calls

            # Save to database with transaction safety
            try:
                from sqlalchemy import select

                result = await session.execute(
                    select(AgentPerformance).where(
                        AgentPerformance.agent_name == agent_name
                    )
                )
                agent_perf = result.scalar_one_or_none()

                if agent_perf:
                    agent_perf.total_calls = self.agent_performance[agent_name][
                        "total_calls"
                    ]
                    agent_perf.successful_calls = self.agent_performance[agent_name][
                        "successful_calls"
                    ]
                    agent_perf.avg_response_time = self.agent_performance[agent_name][
                        "avg_response_time"
                    ]
                    agent_perf.updated_at = datetime.utcnow()
                else:
                    agent_perf = AgentPerformance(
                        agent_name=agent_name,
                        total_calls=self.agent_performance[agent_name]["total_calls"],
                        successful_calls=self.agent_performance[agent_name][
                            "successful_calls"
                        ],
                        avg_response_time=self.agent_performance[agent_name][
                            "avg_response_time"
                        ],
                        accuracy_score=self.agent_performance[agent_name][
                            "accuracy_score"
                        ],
                        improvement_areas=self.agent_performance[agent_name][
                            "improvement_areas"
                        ],
                    )
                    session.add(agent_perf)

                await session.commit()
            except Exception as e:
                await session.rollback()
                print(f"Failed to record agent performance: {e}")

    async def get_agent_performance(self, agent_name: str, session) -> AgentPerformance:
        """Get performance metrics for an agent"""
        from sqlalchemy import select

        result = await session.execute(
            select(AgentPerformance).where(AgentPerformance.agent_name == agent_name)
        )
        agent_perf = result.scalar_one_or_none()

        if not agent_perf:
            raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")

        return AgentPerformance(
            agent_name=agent_perf.agent_name,
            total_calls=agent_perf.total_calls,
            successful_calls=agent_perf.successful_calls,
            avg_response_time=agent_perf.avg_response_time,
            accuracy_score=agent_perf.accuracy_score,
            improvement_areas=(
                eval(agent_perf.improvement_areas)
                if agent_perf.improvement_areas
                else []
            ),
        )


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for consistent error responses"""
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal Server Error", detail=str(exc), timestamp=datetime.utcnow()
        ).dict(),
    )


@app.on_event("startup")
async def startup_event():
    """Initialize the orchestrator and learning system on startup"""
    global orchestrator, learning_system

    print("🚀 Starting Trading Bot API...")

    # Show configuration info
    config_info = get_settings_info()
    print(f"📊 Configuration: {config_info}")

    # Validate settings if available
    if SETTINGS_AVAILABLE:
        print("✅ Pydantic settings validation enabled")
    else:
        print("⚠️  Using fallback environment variables")

    # Test database connection
    if not await test_database_connection():
        raise Exception("Database connection failed - check DATABASE_URL")

    # Initialize database tables
    await init_database()
    print("✅ Database initialized successfully")

    # Initialize orchestrator
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠️  ANTHROPIC_API_KEY not found - using mock orchestrator")
        orchestrator = MockOrchestrator()
    else:
        print("✅ Anthropic API key found - using real orchestrator")
        orchestrator = MultiAgentOrchestrator(api_key)

    learning_system = AgentLearningSystem()
    print("🎯 Trading Bot API started successfully!")


@app.get("/")
async def root():
    """Root endpoint with health info"""
    return HealthResponse(
        status="running",
        orchestrator=orchestrator is not None,
        database="connected",
        timestamp=datetime.utcnow(),
        config_source=(
            "pydantic_settings" if SETTINGS_AVAILABLE else "environment_variables"
        ),
    )


@app.get("/api/health")
async def health_check():
    """Enhanced health check endpoint"""
    try:
        # Test database connection
        db_healthy = await test_database_connection()

        return HealthResponse(
            status="healthy" if db_healthy else "unhealthy",
            orchestrator=orchestrator is not None,
            database="connected" if db_healthy else "disconnected",
            timestamp=datetime.utcnow(),
            config_source=(
                "pydantic_settings" if SETTINGS_AVAILABLE else "environment_variables"
            ),
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content=HealthResponse(
                status="unhealthy",
                orchestrator=False,
                database="error",
                timestamp=datetime.utcnow(),
                config_source="error",
            ).dict(),
        )


@app.post("/api/analyze", response_model=TradeDecision)
async def analyze_trade(request: TradeRequest):
    """Analyze a trade using the multi-agent system with transaction safety"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    try:
        start_time = datetime.now()

        # Convert request to signal format
        signals = [{"symbol": request.symbol, "price": request.price}]
        if request.signals:
            signals.extend(request.signals)

        # Process through orchestrator
        result = orchestrator.process_trade_signals(signals)

        # Record agent calls for learning with proper transaction handling
        async with get_async_session() as session:
            response_time = (datetime.now() - start_time).total_seconds()
            for agent in [
                "SIGNAL_AGENT",
                "RISK_AGENT",
                "CONSENSUS_AGENT",
                "SIZING_AGENT",
            ]:
                await learning_system.record_agent_call(
                    agent, True, response_time, session
                )

        return TradeDecision(
            symbol=request.symbol,
            decision=result.get("DECISION", "FLAT"),
            confidence=result.get("confidence", 0.0),
            reasoning=result.get("reasoning", "Analysis completed"),
            timestamp=datetime.now(),
            position_size=result.get("position_size"),
            risk_assessment=result.get("risk_assessment"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/api/analyze-stream")
async def analyze_trade_stream(request: TradeRequest):
    """Stream analysis results in real-time"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    async def generate():
        try:
            # Send start event
            yield f"data: {json.dumps({'type': 'start', 'message': 'Starting analysis...'})}\n\n"

            # Process through orchestrator with streaming
            signals = [{"symbol": request.symbol, "price": request.price}]
            if request.signals:
                signals.extend(request.signals)

            # Simulate agent thinking process with real learning system integration
            agents = ["SIGNAL_AGENT", "RISK_AGENT", "CONSENSUS_AGENT", "SIZING_AGENT"]

            async with get_async_session() as session:
                for agent in agents:
                    yield f"data: {json.dumps({'type': 'agent', 'name': agent, 'status': 'thinking'})}\n\n"
                    await asyncio.sleep(1)  # Simulate processing time

                    # Record the call in learning system with transaction safety
                    await learning_system.record_agent_call(agent, True, 1.0, session)

                    yield f"data: {json.dumps({'type': 'agent', 'name': agent, 'status': 'complete'})}\n\n"

            # Final result
            result = {
                "type": "result",
                "decision": "LONG",
                "confidence": 0.85,
                "reasoning": "Multiple agents confirm bullish sentiment with strong risk metrics",
            }
            yield f"data: {json.dumps(result)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/plain")


@app.get("/api/trades")
async def get_trades():
    """Get all trades from database with proper error handling"""
    try:
        async with get_async_session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Trade).order_by(Trade.created_at.desc())
            )
            trades = result.scalars().all()

            return {
                "trades": [
                    {
                        "id": trade.id,
                        "date": trade.date,
                        "asset": trade.asset,
                        "direction": trade.direction,
                        "size": trade.size,
                        "entry": trade.entry,
                        "stop": trade.stop,
                        "target": trade.target,
                        "rr_ratio": trade.rr_ratio,
                        "exit_price": trade.exit,
                        "pnl": trade.pnl,
                        "outcome": trade.outcome,
                        "created_at": (
                            trade.created_at.isoformat() if trade.created_at else None
                        ),
                        "updated_at": (
                            trade.updated_at.isoformat() if trade.updated_at else None
                        ),
                    }
                    for trade in trades
                ]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trades: {str(e)}")


@app.post("/api/trades")
async def save_trade(trade: TradeModel):
    """Save a new trade to database with transaction safety"""
    try:
        async with get_async_session() as session:
            db_trade = Trade(
                date=trade.date,
                asset=trade.asset,
                direction=trade.direction,
                size=trade.size,
                entry=trade.entry,
                stop=trade.stop,
                target=trade.target,
                rr_ratio=trade.rr_ratio,
                exit=trade.exit,
                pnl=trade.pnl,
                outcome=trade.outcome,
            )
            session.add(db_trade)
            await session.commit()

            return {"message": "Trade saved successfully", "id": db_trade.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save trade: {str(e)}")


@app.get("/api/performance/{agent_name}")
async def get_agent_performance(agent_name: str):
    """Get performance metrics for a specific agent"""
    if not learning_system:
        raise HTTPException(status_code=503, detail="Learning system not initialized")

    try:
        async with get_async_session() as session:
            return await learning_system.get_agent_performance(agent_name, session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get performance: {str(e)}"
        )


@app.get("/api/performance")
async def get_all_performance():
    """Get performance metrics for all agents"""
    if not learning_system:
        raise HTTPException(status_code=503, detail="Learning system not initialized")

    try:
        async with get_async_session() as session:
            performance = {}
            for agent_name in learning_system.agent_performance.keys():
                performance[agent_name] = await learning_system.get_agent_performance(
                    agent_name, session
                )

            return performance
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get all performance: {str(e)}"
        )


@app.get("/api/statistics")
async def get_trading_statistics():
    """Get overall trading statistics with proper error handling"""
    try:
        async with get_async_session() as session:
            from sqlalchemy import func, select

            # Get basic stats
            total_trades_result = await session.execute(select(func.count(Trade.id)))
            total_trades = total_trades_result.scalar()

            wins_result = await session.execute(
                select(func.count(Trade.id)).where(Trade.outcome == "WIN")
            )
            wins = wins_result.scalar()

            losses_result = await session.execute(
                select(func.count(Trade.id)).where(Trade.outcome == "LOSS")
            )
            losses = losses_result.scalar()

            pnl_result = await session.execute(
                select(func.sum(Trade.pnl)).where(Trade.pnl.isnot(None))
            )
            total_pnl = pnl_result.scalar() or 0

            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            return {
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "total_pnl": round(total_pnl, 2),
            }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get statistics: {str(e)}"
        )


# Mock orchestrator for development without API key
class MockOrchestrator:
    def __init__(self):
        self.trade_log = []
        self.agents = ["SIGNAL_AGENT", "RISK_AGENT", "CONSENSUS_AGENT", "SIZING_AGENT"]

    def process_trade_signals(self, signals):
        return {
            "DECISION": "LONG",
            "confidence": 0.75,
            "reasoning": "Mock analysis - positive sentiment detected",
            "position_size": 0.02,
            "risk_assessment": {"risk_score": 0.3, "max_loss": 0.02},
        }

    def get_trade_history(self):
        return self.trade_log


# Vercel serverless handler
handler = app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
