"""Reasoning Agent - reads signals and produces trading decisions."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.events.bus import EventBus, DEFAULT_GROUP
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.database import AsyncSessionFactory
from api.services.agents.pipeline_agents import MultiStreamAgent


class ReasoningAgent(MultiStreamAgent):
    """Consumes signals and produces trading decisions with reasoning."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["signals"], consumer="reasoning-agent", redis_client=redis_client)

    async def _apply_reasoning_rules(self, signal_type: str, direction: str, confidence: float) -> tuple[str, float]:
        """Apply rule-based reasoning to generate action and confidence."""
        
        if signal_type == 'STRONG_MOMENTUM':
            if direction == 'bullish':
                return 'BUY', 0.75
            else:  # bearish
                return 'SELL', 0.75
        elif signal_type == 'MOMENTUM':
            if direction == 'bullish':
                return 'WATCH', 0.55
            else:  # bearish
                return 'WATCH', 0.45
        else:  # PRICE_UPDATE
            return 'HOLD', 0.30

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        """Process a signal and produce trading decision."""
        try:
            # Parse signal
            payload = json.loads(data.get("payload", "{}"))
            signal_type = payload.get("type")
            symbol = payload.get("symbol")
            price = payload.get("price")
            direction = payload.get("direction")
            trace_id = payload.get("trace_id", str(uuid.uuid4()))
            
            if not signal_type or not symbol or price is None:
                log_structured("warning", "invalid_signal", data=data)
                return
            
            # Apply reasoning rules
            action, confidence = await self._apply_reasoning_rules(signal_type, direction, 0.5)
            
            # Create decision
            decision = {
                "payload": json.dumps({
                    "action": action,
                    "symbol": symbol,
                    "confidence": confidence,
                    "reasoning": f"{signal_type} detected: {direction} at {price}",
                    "signal_type": signal_type,
                    "trace_id": trace_id,
                    "ts": int(time.time()),
                    "source": "REASONING_AGENT"
                })
            }
            
            # Publish to decisions stream
            await self.bus.xadd("decisions", decision)
            
            log_structured("info", "decision_generated", 
                         symbol=symbol, action=action, confidence=confidence)
            
        except Exception as e:
            log_structured("error", "reasoning_processing_error", exc_info=True)
            raise
