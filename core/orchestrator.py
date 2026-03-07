"""
Simple orchestrator for testing
"""

import asyncio
from typing import Any, Dict


class TradingOrchestrator:
    """Simple orchestrator for testing"""

    def __init__(self) -> None:
        self.is_running = False

    async def start(self) -> None:
        """Start orchestrator"""
        self.is_running = True

    async def stop(self) -> None:
        """Stop orchestrator"""
        self.is_running = False
