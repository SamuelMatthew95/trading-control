"""
Main Application - Clean Production-Ready Trading System
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import system components
from ..system.professional_trading_orchestrator import create_professional_orchestrator
from .stateful_logging_system import create_stateful_logging_system
from .logger import get_logger, setup_logging
from .config import get_settings

logger = get_logger(__name__)


class TradingControlPlatform:
    """Clean, robust trading control platform with modern architecture"""

    def __init__(self):
        self.settings = get_settings()
        self.orchestrator = None
        self.db_manager = None
        self.logger = None
        self.is_running = False
        self.background_tasks = set()

    async def initialize(self):
        """Initialize all platform components"""
        logger.info("Initializing Trading Control Platform...")

        # Initialize logging system
        self.db_manager, self.logger, test_manager = create_stateful_logging_system()
        logger.info("✅ Logging system initialized")

        # Initialize orchestrator
        self.orchestrator = create_professional_orchestrator()
        logger.info("✅ Professional orchestrator initialized")

        logger.info("🚀 Trading Control Platform initialized successfully")

    async def start(self):
        """Start the platform"""
        if self.is_running:
            logger.warning("Platform is already running")
            return

        logger.info("Starting Trading Control Platform...")

        # Start orchestrator
        if self.orchestrator:
            # Run initial cycle
            await self.orchestrator.run_trading_cycle()

        self.is_running = True
        logger.info("✅ Trading Control Platform started")

    async def stop(self):
        """Stop the platform"""
        if not self.is_running:
            logger.warning("Platform is not running")
            return

        logger.info("Stopping Trading Control Platform...")

        # Cancel background tasks
        for task in self.background_tasks:
            task.cancel()

        self.is_running = False
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
        # Create simple FastAPI app for testing
        app = FastAPI(title="Trading Control Platform")
        
        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "running": platform.is_running}
        
        yield app


async def main():
    """Main application entry point"""
    # Setup logging
    setup_logging()
    
    # Initialize and start platform
    await platform.initialize()
    
    try:
        # Keep platform running
        while platform.is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await platform.stop()


if __name__ == "__main__":
    asyncio.run(main())
