"""Tests for SignalGenerator action-classification rules.

Locked-in invariants that prevent the "trade noise" regression:
  - LOW strength (sub-1.5% pct) -> action MUST be 'hold' regardless of direction
  - NEUTRAL direction (pct == 0) -> action MUST be 'hold'
  - MOMENTUM strength + non-zero direction -> action follows direction sign
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import FieldName, STREAM_SIGNALS
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
            {
                "symbol": symbol,
                "price": 43000.0,
                "pct": pct,
                "trace_id": "trace-weak-hold-001",
            }
        ),
        "msg_id": "msg-001",
    }


def _published_action(bus: MagicMock) -> str | None:
    """Find the STREAM_SIGNALS publish call and return its action field."""
    for call in bus.publish.await_args_list:
        args, _ = call
        if args and args[0] == STREAM_SIGNALS:
            payload = args[1]
            return payload.get(FieldName.ACTION)
    return None


async def test_weak_signal_holds_even_when_direction_positive():
    """A 0.5% bullish move is below the LOW strength threshold — never trade."""
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    await sg.process(_payload(pct=0.5))
    assert _published_action(sg.bus) == "hold"


async def test_weak_signal_holds_even_when_direction_negative():
    """Tiny bearish moves get HOLD too."""
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    await sg.process(_payload(pct=-0.5))
    assert _published_action(sg.bus) == "hold"


async def test_zero_pct_is_neutral_and_holds():
    """Exact zero direction -> HOLD; never sell on 'no change'."""
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    await sg.process(_payload(pct=0.0))
    assert _published_action(sg.bus) == "hold"


async def test_momentum_buy_on_strong_bullish():
    """A 2.0% (MOMENTUM) move keeps the original buy-on-up behavior."""
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    await sg.process(_payload(pct=2.0))
    assert _published_action(sg.bus) == "buy"


async def test_momentum_sell_on_strong_bearish():
    """A -2.0% (MOMENTUM) move keeps the original sell-on-down behavior."""
    sg = SignalGenerator(bus=_make_bus(), dlq=_make_dlq())
    await sg.process(_payload(pct=-2.0))
    assert _published_action(sg.bus) == "sell"
