"""AgentPnLStore — the durable (Redis) per-agent realized-PnL accumulator.

Proves the store survives the way Redis does (accumulates, doesn't reset), and
that it degrades to ``None`` (→ "no data") rather than fabricating a record —
the guard against bad in-memory state grading agents on nothing.
"""

from __future__ import annotations

import pytest

from api.constants import FieldName
from api.services.agent_pnl_store import AgentPnLStore

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    """Minimal hash store supporting the HINCR* ops the store uses, via pipeline."""

    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}

    def pipeline(self):
        return _FakePipe(self)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.h.get(key, {}))

    # direct ops (used by the pipeline executor)
    def _hincrby(self, key, field, n):
        cur = int(self.h.setdefault(key, {}).get(field, "0") or "0")
        self.h[key][field] = str(cur + n)

    def _hincrbyfloat(self, key, field, n):
        cur = float(self.h.setdefault(key, {}).get(field, "0") or "0")
        self.h[key][field] = repr(cur + n)

    def _hset(self, key, field, val):
        self.h.setdefault(key, {})[field] = str(val)


class _FakePipe:
    def __init__(self, redis: _FakeRedis) -> None:
        self.redis = redis
        self.ops: list = []

    def hincrby(self, key, field, n):
        self.ops.append(("incr", key, field, n))

    def hincrbyfloat(self, key, field, n):
        self.ops.append(("incrf", key, field, n))

    def hset(self, key, field, val):
        self.ops.append(("set", key, field, val))

    async def execute(self):
        for op in self.ops:
            if op[0] == "incr":
                self.redis._hincrby(op[1], op[2], op[3])
            elif op[0] == "incrf":
                self.redis._hincrbyfloat(op[1], op[2], op[3])
            else:
                self.redis._hset(op[1], op[2], op[3])


async def test_records_and_accumulates_across_trades():
    store = AgentPnLStore(_FakeRedis())
    await store.record_trade("REASONING_AGENT", 100.0)  # win
    await store.record_trade("REASONING_AGENT", -40.0)  # loss
    await store.record_trade("REASONING_AGENT", 60.0)  # win

    stats = await store.get_stats("REASONING_AGENT")
    assert stats is not None
    assert stats[FieldName.TRADE_COUNT] == 3
    assert stats[FieldName.WIN_COUNT] == 2
    assert stats[FieldName.WIN_RATE] == pytest.approx(2 / 3, rel=1e-3)
    assert stats[FieldName.TOTAL_PNL] == pytest.approx(120.0, rel=1e-6)
    assert stats[FieldName.UPDATED_AT] is not None


async def test_no_trades_returns_none_not_zeroed_record():
    """An agent with no trades reads as None (→ UNRATED), never a fake 0% record."""
    store = AgentPnLStore(_FakeRedis())
    assert await store.get_stats("SIGNAL_AGENT") is None


async def test_get_all_omits_agents_with_no_trades():
    store = AgentPnLStore(_FakeRedis())
    await store.record_trade("SIGNAL_AGENT", 10.0)
    out = await store.get_all(["SIGNAL_AGENT", "REASONING_AGENT", "EXECUTION_ENGINE"])
    assert set(out) == {"SIGNAL_AGENT"}  # only the one with trades
    assert out["SIGNAL_AGENT"][FieldName.TRADE_COUNT] == 1
