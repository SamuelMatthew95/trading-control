#!/usr/bin/env python3
"""
Complete System Startup - V3 Agents + Web API

Starts both the V3 event-driven agent system AND the FastAPI web server
in the same process for production deployment.
"""

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from api.v3_production_system import V3ProductionSystem, send_test_events, verify_system_state
from api.main import app
from api.observability import log_structured

if TYPE_CHECKING:
    from redis.asyncio import Redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CompleteSystemManager:
    """Manages both V3 agents and FastAPI server together."""

    def __init__(self):
        self.v3_system = V3ProductionSystem()
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.web_server = None

    async def start_complete_system(self):
        """Start both V3 agents and web server."""
        try:
            print("=" * 80)
            print("🚀 STARTING COMPLETE SYSTEM")
            print("=" * 80)
            print("✅ V3 Event-Driven Agents")
            print("✅ FastAPI Web Server")
            print("✅ Integrated Dashboard")
            print("✅ Real-time WebSocket Updates")
            print("=" * 80)

            # Start V3 system first
            print("[SYSTEM] Starting V3 agents...")
            await self.v3_system.start()
            print("[SYSTEM] ✅ V3 agents started")

            # Send test events
            await send_test_events(self.v3_system.redis)
            await verify_system_state(self.v3_system.redis)

            # Setup signal handlers
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self.shutdown_event.set)

            # Start web server in background
            print("[SYSTEM] Starting FastAPI web server...")
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=8000,
                log_level="info",
                access_log=True
            )
            self.web_server = uvicorn.Server(config)
            
            # Run web server in background task
            web_task = asyncio.create_task(self.web_server.serve())
            print("[SYSTEM] ✅ FastAPI server started on http://localhost:8000")

            print("\n[SYSTEM] 🎯 COMPLETE SYSTEM IS LIVE!")
            print("📊 Dashboard: http://localhost:8000/dashboard")
            print("🔗 API Docs: http://localhost:8000/docs")
            print("📡 WebSocket: ws://localhost:8000/ws")
            print("[SYSTEM] ⏹️  Press Ctrl+C to shutdown gracefully")

            # Wait for shutdown
            await self.shutdown_event.wait()

        except Exception as e:
            print(f"[SYSTEM] ❌ Startup failed: {e}")
            log_structured("error", "complete_system_startup_failed", error=str(e))
            raise

    async def stop_complete_system(self):
        """Stop both V3 agents and web server."""
        print("\n[SYSTEM] 🛑 Shutting down complete system...")

        # Stop web server
        if self.web_server:
            print("[SYSTEM] Stopping FastAPI server...")
            self.web_server.should_exit = True
            # Give web server time to shutdown gracefully
            await asyncio.sleep(1)
            print("[SYSTEM] ✅ FastAPI server stopped")

        # Stop V3 system
        await self.v3_system.stop()
        print("[SYSTEM] ✅ V3 agents stopped")

        print("[SYSTEM] ✅ Complete system shutdown")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager for V3 system integration."""
    # This runs when FastAPI starts
    print("[API] FastAPI application starting...")
    yield
    # This runs when FastAPI stops
    print("[API] FastAPI application shutting down...")


async def main():
    """Main entry point for complete system."""
    system = CompleteSystemManager()
    
    try:
        await system.start_complete_system()
    except KeyboardInterrupt:
        print("\n[SYSTEM] ⌨️  Keyboard interrupt received")
    except Exception as e:
        log_structured("error", "system_error", error=str(e))
        print(f"\n[SYSTEM] ❌ Unexpected error: {e}")
    finally:
        await system.stop_complete_system()


if __name__ == "__main__":
    print("🚀 STARTING COMPLETE TRADING SYSTEM")
    print("=" * 80)
    print("✅ V3 Event-Driven Agents")
    print("✅ FastAPI Web Server") 
    print("✅ Real-time Dashboard")
    print("✅ WebSocket Updates")
    print("✅ Production Ready")
    print("=" * 80)
    
    asyncio.run(main())
