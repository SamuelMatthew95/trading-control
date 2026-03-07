"""
Agents API Routes
Simple REST API for agent management and communication
"""

try:
    import time
    from typing import Any, Dict, List, Optional

    import structlog
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    logger = structlog.get_logger()
    router = APIRouter()

except ImportError as e:
    print(f"Warning: Missing dependencies for agents.py: {e}")

    # Create dummy router for import compatibility
    class DummyRouter:
        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    router = DummyRouter()

    class BaseModel:
        pass

    def HTTPException(*args, **kwargs):
        pass

    logger = None


class MessageRequest(BaseModel):
    """Request to send a message"""

    from_agent: str
    to_agent: str
    message_type: str
    priority: str = "medium"
    data: Dict[str, Any]
    requires_response: bool = False


class ConsensusRequest(BaseModel):
    """Request to build consensus"""

    symbol: str
    task_type: str
    requesting_agent: str


class ConsensusResponse(BaseModel):
    """Response to consensus request"""

    consensus_id: str
    agent: str
    recommendation: Dict[str, Any]
    confidence: float
    reasoning: str


class AlertRequest(BaseModel):
    """Request to broadcast alert"""

    alert: Dict[str, Any]
    from_agent: str


class DataRequest(BaseModel):
    """Request for live data"""

    symbol: str
    from_agent: str


@router.post("/send-message")
async def send_message(message_request: MessageRequest):
    """Send a message between agents"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        from core.agent_manager import AgentMessage

        message = AgentMessage(
            id=f"msg_{int(time.time())}_{message_request.from_agent}",
            from_agent=message_request.from_agent,
            to_agent=message_request.to_agent,
            message_type=message_request.message_type,
            priority=message_request.priority,
            timestamp=time.time(),
            data=message_request.data,
            requires_response=message_request.requires_response,
        )

        message_id = await agent_manager.send_message(message)

        return {"success": True, "message_id": message_id}

    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/request-consensus")
async def request_consensus(consensus_request: ConsensusRequest):
    """Request consensus from multiple agents"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        consensus_id = await agent_manager.request_consensus(
            consensus_request.symbol,
            consensus_request.task_type,
            consensus_request.requesting_agent,
        )

        return {"success": True, "consensus_id": consensus_id}

    except Exception as e:
        logger.error(f"Error requesting consensus: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/respond-consensus")
async def respond_to_consensus(consensus_response: ConsensusResponse):
    """Respond to a consensus request"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        await agent_manager.respond_to_consensus(
            consensus_response.consensus_id,
            consensus_response.agent,
            consensus_response.recommendation,
            consensus_response.confidence,
            consensus_response.reasoning,
        )

        return {"success": True, "message": "Consensus response recorded"}

    except Exception as e:
        logger.error(f"Error responding to consensus: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/broadcast-alert")
async def broadcast_alert(alert_request: AlertRequest):
    """Broadcast alert to all agents"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        await agent_manager.broadcast_alert(
            alert_request.alert, alert_request.from_agent
        )

        return {"success": True, "message": "Alert broadcasted"}

    except Exception as e:
        logger.error(f"Error broadcasting alert: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/request-data")
async def request_live_data(data_request: DataRequest):
    """Request live data for a symbol"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager
        data_manager = app.state.orchestrator.data_manager

        data = await agent_manager.request_live_data(
            data_request.symbol, data_request.from_agent
        )

        return {"success": True, "data": data}

    except Exception as e:
        logger.error(f"Error requesting live data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_agent_status():
    """Get status of all agents"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        status = agent_manager.get_agent_status()

        return {"success": True, "agents": status}

    except Exception as e:
        logger.error(f"Error getting agent status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages")
async def get_messages(agent: Optional[str] = None, limit: int = 50):
    """Get messages for an agent"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        messages = agent_manager.get_messages_for_agent(agent or "", limit)

        # Convert to dict for JSON serialization
        message_list = []
        for msg in messages:
            message_dict = {
                "id": msg.id,
                "from_agent": msg.from_agent,
                "to_agent": msg.to_agent,
                "message_type": msg.message_type,
                "priority": msg.priority,
                "timestamp": msg.timestamp,
                "data": msg.data,
                "requires_response": msg.requires_response,
            }
            message_list.append(message_dict)

        return {"success": True, "messages": message_list}

    except Exception as e:
        logger.error(f"Error getting messages: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consensus")
async def get_consensus_sessions(limit: int = 20):
    """Get recent consensus sessions"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        sessions = agent_manager.get_consensus_sessions(limit)

        return {"success": True, "sessions": sessions}

    except Exception as e:
        logger.error(f"Error getting consensus sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def agent_health_check():
    """Simple health check for agents"""
    try:
        from main import app

        agent_manager = app.state.orchestrator.agent_manager

        status = agent_manager.get_agent_status()

        total_agents = len(status)
        idle_agents = sum(1 for agent in status.values() if agent["status"] == "idle")
        busy_agents = sum(1 for agent in status.values() if agent["status"] == "busy")
        offline_agents = sum(
            1 for agent in status.values() if agent["status"] == "offline"
        )

        return {
            "status": "healthy" if offline_agents < total_agents else "degraded",
            "total_agents": total_agents,
            "idle_agents": idle_agents,
            "busy_agents": busy_agents,
            "offline_agents": offline_agents,
            "average_performance": (
                sum(agent["performance_score"] for agent in status.values())
                / total_agents
                if total_agents > 0
                else 0
            ),
        }

    except Exception as e:
        logger.error(f"Error in agent health check: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}
