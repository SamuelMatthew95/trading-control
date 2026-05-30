"""Tests for SignalGenerator's noise-floor publish throttle.

Locked-in invariants (the "too many signals" remediation):
  - The first tick of a symbol always publishes (warmup + downstream wiring).
  - Sub-threshold LOW ticks publish only once every SIGNAL_EVERY_N_TICKS ticks.
  - A tradeable (non-LOW) move always publishes, even mid-throttle.
  - A throttled tick still writes a heartbeat so the agent never ages to STALE.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import STREAM_SIGNALS, FieldName
from api.services.signal_generator import SignalGenerator

pytestmark = pytest.mark.asyncio


def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="1-0")
    bus.redis = MagicMock()
    bus.redis.set = AsyncMock()
    return bus


def _make_dlq() -> MagicMock:
    dlq = MagicMock()
    dlq.send = AsyncMock()
    return dlq


def _payload(pct: float, symbol: str = "BTC/USD") -> dict:
    return {
        "payload": json.dumps(
            {"symbol": symbol, "price": 43000.0, "pct": pct, "trace_id": "trace-throttle"}
        ),
        "msg_id": "msg-throttle",
    }


def _signal_publishes(bus: MagicMock) -> list[dict]:
    """Every payload published to STREAM_SIGNALS (heartbeats don't go through publish)."""
    return [
        call.args[1]
        for call in bus.publish.await_args_list
        if call.args and call.args[0] == STREAM_SIGNALS
    ]


@pytest.fixture(autouse=True)
def _small_throttle(monkeypatch):
    """Use a tiny window so tests stay short and explicit."""
    monkeypatch.setattr("api.services.signal_generator.settings.SIGNAL_EVERY_N_TICKS", 3)


async def test_low_ticks_publish_first_then_every_n():
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    # 7 consecutive sub-threshold (LOW) ticks, N=3 → publish on ticks 1, 4, 7.
    for _ in range(7):
        await sg.process(_payload(pct=0.4))
    assert len(_signal_publishes(sg.bus)) == 3


async def test_momentum_always_publishes_mid_throttle():
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    await sg.process(_payload(pct=0.4))  # tick 1 LOW → publishes (first)
    await sg.process(_payload(pct=0.4))  # tick 2 LOW → throttled
    await sg.process(_payload(pct=2.0))  # MOMENTUM → publishes despite throttle
    await sg.process(_payload(pct=0.4))  # LOW → throttled (counter reset by momentum)
    published = _signal_publishes(sg.bus)
    assert len(published) == 2
    assert published[1][FieldName.TYPE] == "MOMENTUM"


async def test_throttle_is_per_symbol():
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    # Each symbol's first tick publishes independently.
    await sg.process(_payload(pct=0.4, symbol="BTC/USD"))
    await sg.process(_payload(pct=0.4, symbol="ETH/USD"))
    published = _signal_publishes(sg.bus)
    assert {p[FieldName.SYMBOL] for p in published} == {"BTC/USD", "ETH/USD"}


async def test_throttled_tick_still_heartbeats(monkeypatch):
    hb = AsyncMock()
    monkeypatch.setattr("api.services.signal_generator.write_heartbeat", hb)
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    await sg.process(_payload(pct=0.4))  # tick 1 → publishes (+ heartbeat)
    await sg.process(_payload(pct=0.4))  # tick 2 → throttled (heartbeat only)
    # Exactly one signal published, but a heartbeat fired on BOTH ticks.
    assert len(_signal_publishes(sg.bus)) == 1
    assert hb.await_count == 2
