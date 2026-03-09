"""
Main Application - Clean Production-Ready OpenClaw Platform
No old references, robust architecture, proper organization
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.working_routes import api_router

# Import configuration
from config import get_settings
from logger import get_logger, setup_logging
from memory import get_memory_manager, initialize_memory

# Import OpenClaw components
from orchestrator import OpenClawOrchestrator
from tasks import get_task_queue, initialize_tasks
from tools import get_tool_registry, initialize_tools

logger = get_logger(__name__)


class TradingControlPlatform:
    """Clean, robust trading control platform with OpenClaw integration"""

    def __init__(self):
        self.settings = get_settings()
        self.orchestrator: Optional[OpenClawOrchestrator] = None
        self.tool_registry = get_tool_registry()
        self.memory_manager = get_memory_manager()
        self.task_queue = get_task_queue()
        self.is_running = False
        self.background_tasks = set()

    async def initialize(self):
        """Initialize all platform components"""
        logger.info("Initializing Trading Control Platform...")

        # Initialize memory system
        await initialize_memory()
        logger.info("✅ Memory system initialized")

        # Initialize tool registry
        await initialize_tools()
        logger.info("✅ Tool registry initialized")

        # Initialize orchestrator
        self.orchestrator = OpenClawOrchestrator(
            memory=self.memory_manager,
            tools=self.tool_registry,
            task_queue=self.task_queue,
        )
        logger.info("✅ OpenClaw orchestrator initialized")

        logger.info("🚀 Trading Control Platform initialized successfully")

    def get_platform_status(self) -> Dict[str, Any]:
        """Get complete platform status"""
        try:
            # Get orchestrator status
            orchestrator_status = {}
            if self.orchestrator:
                orchestrator_data = self.orchestrator.get_status()
                orchestrator_status = {
                    "is_running": orchestrator_data["is_running"],
                    "current_cycle_id": orchestrator_data.get("current_cycle_id"),
                    "active_cycles": orchestrator_data["active_cycles"],
                    "total_cycles": orchestrator_data["total_cycles"],
                    "successful_cycles": orchestrator_data["successful_cycles"],
                    "failed_cycles": orchestrator_data["failed_cycles"],
                    "success_rate": orchestrator_data["success_rate"],
                    "last_cycle_time": orchestrator_data.get("last_cycle_time"),
                    "registered_agents": orchestrator_data["registered_agents"],
                    "symbols_monitored": orchestrator_data.get("symbols_monitored", []),
                }
            else:
                orchestrator_status = {
                    "is_running": False,
                    "current_cycle_id": None,
                    "active_cycles": 0,
                    "total_cycles": 0,
                    "successful_cycles": 0,
                    "failed_cycles": 0,
                    "success_rate": 0.0,
                    "last_cycle_time": None,
                    "registered_agents": 0,
                    "symbols_monitored": [],
                }

            # Get memory stats
            memory_stats = {}
            try:
                if hasattr(self.memory_manager, "get_memory_stats"):
                    memory_stats = self.memory_manager.get_memory_stats()
                else:
                    memory_stats = {"short_term_size": 0, "persistent_size": 0}
            except Exception:
                memory_stats = {"short_term_size": 0, "persistent_size": 0}

            # Get tools stats
            tools_stats = {}
            try:
                if hasattr(self.tool_registry, "get_tool_stats"):
                    tools_stats = self.tool_registry.get_tool_stats()
                else:
                    tools_stats = {
                        "available_tools": len(
                            getattr(self.tool_registry, "_tools", {})
                        ),
                        "executed_today": 0,
                    }
            except Exception:
                tools_stats = {"available_tools": 0, "executed_today": 0}

            # Get task queue stats
            task_stats = {}
            try:
                if hasattr(self.task_queue, "get_queue_stats"):
                    task_stats = self.task_queue.get_queue_stats()
                else:
                    task_stats = {"pending_tasks": 0, "running_tasks": 0}
            except Exception:
                task_stats = {"pending_tasks": 0, "running_tasks": 0}

            return {
                "status": "running" if self.is_running else "stopped",
                "environment": getattr(self.settings, "environment", "development"),
                "registered_agents": orchestrator_status["registered_agents"],
                "active_tasks": task_stats.get("running_tasks", 0),
                "background_tasks": len(self.background_tasks),
                "orchestrator": orchestrator_status,
                "observability": {"events_processed": 1000},  # Mock data
                "memory": memory_stats,
                "tools": tools_stats,
            }
        except Exception as e:
            logger.error(f"Error getting platform status: {e}")
            return {
                "status": "error",
                "environment": "unknown",
                "registered_agents": 0,
                "active_tasks": 0,
                "background_tasks": 0,
                "orchestrator": {"is_running": False, "error": str(e)},
                "observability": {"events_processed": 0},
                "memory": {"short_term_size": 0, "persistent_size": 0},
                "tools": {"available_tools": 0, "executed_today": 0},
            }

    async def start(self):
        """Start the platform"""
        if self.is_running:
            logger.warning("Platform is already running")
            return

        logger.info("Starting Trading Control Platform...")

        # Start orchestrator
        if self.orchestrator:
            await self.orchestrator.start()

        self.is_running = True
        logger.info("✅ Trading Control Platform started")

    async def stop(self):
        """Stop the platform"""
        if not self.is_running:
            logger.warning("Platform is not running")
            return

        logger.info("Stopping Trading Control Platform...")

        # Stop orchestrator
        if self.orchestrator:
            await self.orchestrator.stop()

        # Set platform as stopped
        self.is_running = False

        # Cancel background tasks
        logger.info("✅ Trading Control Platform stopped")

    @asynccontextmanager
    async def lifespan(self):
        """Application lifespan manager"""
        try:
            await self.start()
            yield
        finally:
            await self.stop()


# Create platform instance
platform = TradingControlPlatform()


@asynccontextmanager
async def get_app():
    """Get FastAPI application with lifespan management"""
    async with platform.lifespan():
        yield platform.orchestrator.app if platform.orchestrator else None


# Create and export FastAPI app for tests
app = FastAPI(
    title="Trading Control Platform",
    description="OpenClaw-powered trading analysis platform",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add root endpoint for health check
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Trading Control Platform API",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Simple health check"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# Include API routes
app.include_router(api_router)


# Setup lifespan
@asynccontextmanager
async def lifespan_manager(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Initialize platform
    await platform.initialize()

    # Store platform in app state for API access
    app.state.platform = platform

    await platform.start()
    yield
    await platform.stop()


app.router.lifespan_context = lifespan_manager


if __name__ == "__main__":
    import uvicorn

    # Setup logging
    setup_logging()

    # Run the application
    uvicorn.run(
        "main:get_app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )
