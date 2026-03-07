"""
Simplified API Routes for debugging
"""

from typing import Any, Dict

from fastapi import APIRouter

# Create router
api_router = APIRouter(prefix="/api/v1", tags=["OpenClaw API"])


@api_router.get("/", response_model=Dict[str, Any])
async def root_endpoint():
    """Root endpoint with API information"""
    return {
        "name": "OpenClaw Trading Control Platform",
        "version": "1.0.0",
        "description": "AI-powered trading analysis and control platform",
        "endpoints": {
            "health": "/api/v1/health",
            "platform": "/api/v1/platform/status",
            "agents": "/api/v1/agents",
            "tools": "/api/v1/tools",
            "orchestrator": "/api/v1/orchestrator/status",
        },
    }


@api_router.get("/health", response_model=Dict[str, Any])
async def health_check():
    """Simple health check endpoint"""
    return {"status": "healthy", "timestamp": "2024-03-06T14:46:00Z"}


print(f"Routes registered: {[route.path for route in api_router.routes]}")
