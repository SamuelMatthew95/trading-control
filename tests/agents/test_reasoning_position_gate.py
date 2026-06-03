"""Item 5 invariant: the ReasoningAgent is position-aware before it publishes.

A SELL recommendation for a symbol with no open long is downgraded to HOLD
(tagged with a reason), reading the same PaperBroker the ExecutionEngine
rejects against — so the advisory feed never advertises a SELL that can't
execute, and we only ever sell what we actually hold.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from api.constants import AgentAction, FieldName
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.reasoning_agent import ReasoningAgent

# No module-level asyncio marker: this file mixes sync (_apply_risk_hierarchy)
# and async (_open_long_qty) tests, and pytest's asyncio_mode=auto runs the
# coroutine tests without marking the sync ones.


def _agent(redis_client):
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return ReasoningAgent(bus=bus, dlq=dlq, redis_client=redis_client)


def _summary(action: str) -> dict:
    return {FieldName.ACTION: action, FieldName.CONFIDENCE: 0.9, FieldName.RISK_FACTORS: []}


def test_sell_with_no_open_long_downgraded_to_hold():
    agent = _agent(AsyncMock())
    out = agent._apply_risk_hierarchy(
        _summary(AgentAction.SELL), {FieldName.OPEN_POSITION_QTY: 0.0}
    )
    assert out[FieldName.ACTION] == AgentAction.HOLD
    assert out[FieldName.DOWNGRADE_REASON] == "sell_without_open_long"
    assert "NO_OPEN_POSITION" in out[FieldName.RISK_FACTORS]


def test_sell_with_open_long_is_allowed():
    agent = _agent(AsyncMock())
    out = agent._apply_risk_hierarchy(
        _summary(AgentAction.SELL),
        {FieldName.OPEN_POSITION_QTY: 5.0, FieldName.IC_WEIGHTS: {}},
    )
    assert out[FieldName.ACTION] == AgentAction.SELL  # we hold it → SELL stands


def test_buy_is_never_touched_by_the_position_guard():
    agent = _agent(AsyncMock())
    out = agent._apply_risk_hierarchy(
        _summary(AgentAction.BUY),
        {FieldName.OPEN_POSITION_QTY: 0.0, FieldName.IC_WEIGHTS: {}},
    )
    assert out[FieldName.ACTION] == AgentAction.BUY


async def test_open_long_qty_reads_the_broker():
    agent = _agent(fakeredis.aioredis.FakeRedis(decode_responses=True))
    assert await agent._open_long_qty("BTC/USD") == 0.0  # flat
    await agent.broker.place_order("BTC/USD", "buy", 2.0, 100.0)
    assert await agent._open_long_qty("BTC/USD") == pytest.approx(2.0)
    assert await agent._open_long_qty(None) == 0.0  # no symbol


async def test_open_long_qty_robust_to_non_dict_reply():
    """A blanket mock redis makes broker.get_position return a non-dict; the
    guard treats that as 'flat' rather than raising."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"0")  # broker.get_position -> json.loads -> 0 (int)
    agent = _agent(redis)
    assert await agent._open_long_qty("BTC/USD") == 0.0


async def test_short_position_does_not_count_as_open_long():
    agent = _agent(fakeredis.aioredis.FakeRedis(decode_responses=True))
    # Open a long then oversell past zero to flip short via the broker directly.
    await agent.broker.place_order("ETH/USD", "buy", 1.0, 100.0)
    await agent.broker.place_order("ETH/USD", "sell", 3.0, 100.0)  # now net short
    assert await agent._open_long_qty("ETH/USD") == 0.0  # long-only: short is not sellable
