"""
Main Application - Clean Production-Ready OpenClaw Platform
No old references, robust architecture, proper organization
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import OpenClaw components
from orchestrator import OpenClawOrchestrator
from tools import get_tool_registry, initialize_tools
from memory import get_memory_manager, initialize_memory
from tasks import get_task_queue, initialize_tasks
from api.routes import api_router
from logger import get_logger, setup_logging

# Import configuration
from config import get_settings

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


if __name__ == "__main__":
    import uvicorn
    
    # Setup logging
    setup_logging()
    
    # Run the application
    uvicorn.run(
        "main:get_app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
