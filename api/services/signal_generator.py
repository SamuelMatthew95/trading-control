"""Signal generator - bridges market_ticks -> signals stream."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured


class SignalGenerator(BaseStreamConsumer):
    """
    Reads market_ticks, fires a signal every SIGNAL_EVERY_N_TICKS ticks
    per symbol. With 10s tick interval and N=10, fires every ~100 seconds.
    Result: ~864 LLM calls/day = 6% of Groq free limit.
    """
    SIGNAL_EVERY_N_TICKS: int = 10

    def __init__(self, bus: EventBus, dlq: DLQManager):
        super().__init__(
            bus, dlq,
            stream="market_ticks",
            group=DEFAULT_GROUP,
            consumer="signal-generator",
        )
        self._tick_count: dict[str, int] = {}

    async def process(self, data: dict[str, Any]) -> None:
        symbol = data.get("symbol")
        price = float(data.get("price", 0))
        if not symbol or price <= 0:
            return

        count = self._tick_count.get(symbol, 0) + 1
        self._tick_count[symbol] = count

        if count % self.SIGNAL_EVERY_N_TICKS != 0:
            return

        signal = {
            "symbol": symbol,
            "price": price,
            "action": "hold",
            "signal_type": "periodic",
            "composite_score": 0.5,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_id": f"periodic-{symbol.lower().replace('/', '-')}",
            "qty": 1.0,
            "size_pct": 0.01,
            "stop_atr_x": 1.5,
            "rr_ratio": 2.0,
            "context": {"tick_count": count},
        }

        await self.bus.publish("signals", signal)
        log_structured(
            "info", "Signal generated",
            symbol=symbol, price=price, tick_count=count,
        )
