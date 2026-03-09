"""
API Routes Package
"""

# Also import the main API router from parent routes.py
import sys
from pathlib import Path

from .agents import router as agent_router
from .data import router as data_router
from .monitoring import router as monitoring_router
from .orchestrator import router as orchestrator_router

# Add parent directory to path to import routes.py
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from routes import api_router
except ImportError:
    # If routes.py is not accessible, create a minimal router
    from fastapi import APIRouter

    api_router = APIRouter()

__all__ = [
    "agent_router",
    "data_router",
    "orchestrator_router",
    "monitoring_router",
    "api_router",
]
