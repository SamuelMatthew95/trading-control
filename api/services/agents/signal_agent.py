"""Signal Agent - reads market events and generates trading signals."""

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


class SignalAgent(MultiStreamAgent):
    """Consumes market events and produces trading signals."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["market_events"], consumer="signal-agent", redis_client=redis_client)

    async def _detect_signals(self, symbol: str, price: float, pct: float, trace_id: str) -> list[dict[str, Any]]:
        """Detect trading signals from price data."""
        signals = []
        
        abs_pct = abs(pct)
        direction = 'bullish' if pct > 0 else 'bearish'
        
        if abs_pct >= 3.0:
            signal_type = 'STRONG_MOMENTUM'
            strength = 'HIGH'
        elif abs_pct >= 1.5:
            signal_type = 'MOMENTUM'
            strength = 'NORMAL'
        else:
            signal_type = 'PRICE_UPDATE'
            strength = 'LOW'
        
        signals.append({
            "type": signal_type,
            "symbol": symbol,
            "price": price,
            "pct": pct,
            "direction": direction,
            "strength": strength,
            "trace_id": trace_id,
            "ts": int(time.time()),
            "source": "SIGNAL_AGENT"
        })
        
        return signals
    
    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        """Process a market event and generate signals."""
        try:
            # Parse market event
            payload = json.loads(data.get("payload", "{}"))
            symbol = payload.get("symbol")
            price = payload.get("price")
            pct = payload.get("pct", 0)
            trace_id = payload.get("trace_id", str(uuid.uuid4()))
            
            if not symbol or price is None:
                log_structured("warning", "invalid_market_event", data=data)
                return
            
            # Detect signals - pass the same trace_id through
            signals = await self._detect_signals(symbol, float(price), float(pct), trace_id)
            
            # Publish signals to stream
            for signal in signals:
                await self.bus.xadd("signals", {
                    "payload": json.dumps(signal)
                })
            
            # Write to events table for signal generation
            async with AsyncSessionFactory() as session:
                await session.execute(
                    """
                    INSERT INTO events (id, event_type, entity_type, idempotency_key,
                                        processed, data, schema_version, source, created_at)
                    VALUES (gen_random_uuid(), 'signal.generated', 'signal', %s,
                            %s, %s, 'v2', 'SIGNAL_AGENT', NOW())
                    """,
                    (f"signal-{symbol}-{trace_id}", json.dumps(signal))
                )
                await session.commit()
            
            log_structured("info", "signals_generated", 
                         symbol=symbol, signal_count=len(signals), trace_id=trace_id)
            
        except Exception as e:
            log_structured("error", "signal_processing_error", exc_info=True)
            raise
