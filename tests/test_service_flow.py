from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.routes.ws import router as ws_router
from api.services.agents.reasoning_agent import ReasoningAgent
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine
from api.services.market_ingestor import MarketIngestor


class FakeResult:
    def __init__(self, rows=None, first_row=None, mapping_rows=None, scalar=None):
        self._rows = rows or []
        self._first_row = first_row
        self._mapping_rows = mapping_rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._mapping_rows or self._rows

    def first(self):
        if self._mapping_rows:
            return self._mapping_rows[0]
        return self._first_row

    def scalar_one(self):
        return self._scalar


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        return self.handler(sql, params)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


class FakeRedis:
    def __init__(self):
        self.values = defaultdict(str)
        self.xread_calls = 0
        self.xread_messages = []

    async def setnx(self, key, value):
        if key in self.values:
            return False
        self.values[key] = str(value)
        return True

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)
        return 1

    async def incrby(self, key, amount):
        self.values[key] = str(int(float(self.values.get(key, 0) or 0)) + amount)
        return self.values[key]

    async def incrbyfloat(self, key, amount):
        self.values[key] = str(float(self.values.get(key, 0) or 0.0) + amount)
        return self.values[key]

    async def incr(self, key):
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        return int(self.values[key])

    async def expire(self, key, ttl):
        return True

    async def hset(self, key, field, value):
        return 1

    async def hgetall(self, key):
        return {}

    async def hget(self, key, field):
        return None

    async def hdel(self, key, field):
        return 1

    async def xadd(self, stream, payload):
        return "1-0"

    async def xread(self, last_ids, block=1000, count=50):
        self.xread_calls += 1
        if self.xread_calls == 1:
            return self.xread_messages
        raise RuntimeError("stop")


class RecordingBus(EventBus):
    def __init__(self, redis_client):
        super().__init__(redis_client)
        self.published = []

    async def publish(self, stream, event):
        self.published.append((stream, event))
        return "1-0"


class FakeBroker:
    async def place_order(self, symbol, side, qty, price):
        return {
            "broker_order_id": "broker-1",
            "status": "filled",
            "fill_price": 101.25,
        }


@pytest.mark.asyncio
async def test_paper_broker_updates_cash_and_position(monkeypatch):
    redis = FakeRedis()
    broker = PaperBroker(redis)
    monkeypatch.setattr(
        "api.services.execution.brokers.paper.random.uniform", lambda a, b: 0.0002
    )

    order = await broker.place_order("BTC/USD", "buy", 2, 100)
    position = await broker.get_position("BTC/USD")
    cash = await broker.get_cash()

    assert order["status"] == "filled"
    assert position["side"] == "long"
    assert float(position["qty"]) == 2.0
    assert cash < broker.DEFAULT_CASH


@pytest.mark.asyncio
async def test_execution_engine_respects_kill_switch():
    redis = FakeRedis()
    redis.values["kill_switch:active"] = "1"
    bus = RecordingBus(redis)
    dlq = DLQManager(redis, bus)
    engine = ExecutionEngine(bus, dlq, redis, FakeBroker())

    with pytest.raises(RuntimeError, match="KillSwitchActive"):
        await engine.process(
            {
                "strategy_id": "s1",
                "symbol": "BTC/USD",
                "side": "buy",
                "qty": 1,
                "price": 100,
            }
        )


@pytest.mark.asyncio
async def test_execution_engine_publishes_fill_metadata(monkeypatch):
    import api.services.execution.execution_engine as execution_module

    session = FakeSession(_execution_handler)
    monkeypatch.setattr(
        execution_module, "AsyncSessionFactory", FakeSessionFactory(session)
    )

    redis = FakeRedis()
    bus = RecordingBus(redis)
    dlq = DLQManager(redis, bus)
    engine = ExecutionEngine(bus, dlq, redis, FakeBroker())

    await engine.process(
        {
            "strategy_id": "strategy-1",
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 1,
            "price": 100,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": "trace-abc",
        }
    )

    execution_event = bus.published[-1][1]
    assert execution_event["type"] == "order_filled"
    assert execution_event["trace_id"] == "trace-abc"
    assert execution_event["fill_price"] == 101.25
    assert "filled_at" in execution_event


@pytest.mark.asyncio
async def test_reasoning_agent_fallback_publishes_logs_and_orders(monkeypatch):
    import api.services.agents.reasoning_agent as reasoning_module
    from api.config import settings

    session = FakeSession(_reasoning_handler)
    monkeypatch.setattr(
        reasoning_module, "AsyncSessionFactory", FakeSessionFactory(session)
    )
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODE", "skip_reasoning")

    redis = FakeRedis()
    bus = RecordingBus(redis)
    dlq = DLQManager(redis, bus)
    agent = ReasoningAgent(bus, dlq, redis)

    await agent.process(
        {
            "strategy_id": "strategy-1",
            "symbol": "BTC/USD",
            "price": 100.0,
            "composite_score": 0.82,
            "signal": "buy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    streams = [stream for stream, _ in bus.published]
    assert "agent_logs" in streams
    assert "orders" in streams


@pytest.mark.asyncio
async def test_execution_engine_updates_existing_short_position_with_signed_math(
    monkeypatch,
):
    import api.services.execution.execution_engine as execution_module

    class CaptureSession(FakeSession):
        pass

    updates = []

    def handler(sql, params):
        if "SELECT id, side, qty FROM positions" in sql:
            return FakeResult(
                mapping_rows=[{"id": "pos-1", "side": "short", "qty": 5.0}]
            )
        if sql.startswith("UPDATE positions SET side"):
            updates.append(params)
            return FakeResult()
        return FakeResult()

    session = CaptureSession(handler)
    redis = FakeRedis()
    bus = RecordingBus(redis)
    dlq = DLQManager(redis, bus)
    engine = ExecutionEngine(bus, dlq, redis, FakeBroker())

    await engine._upsert_position(session, "strategy-1", "BTC/USD", "buy", 2.0, 101.0)

    assert updates[0]["side"] == "short"
    assert updates[0]["qty"] == 3.0


def test_trade_evaluator_skips_realized_pnl_for_same_direction_fills():
    from api.services.learning.evaluator import TradeEvaluator

    evaluator = TradeEvaluator(bus=None, dlq=None, redis_client=None)
    prior_long = {
        "side": "buy",
        "qty": 1.0,
        "price": 100.0,
        "filled_at": datetime.now(timezone.utc).isoformat(),
    }
    prior_short = {
        "side": "sell",
        "qty": 1.0,
        "price": 100.0,
        "filled_at": datetime.now(timezone.utc).isoformat(),
    }

    same_long = evaluator._compute_trade_metrics(
        prior_trade=prior_long,
        side="buy",
        qty=1.0,
        fill_price=105.0,
        filled_at=datetime.now(timezone.utc),
    )
    same_short = evaluator._compute_trade_metrics(
        prior_trade=prior_short,
        side="sell",
        qty=1.0,
        fill_price=95.0,
        filled_at=datetime.now(timezone.utc),
    )

    assert same_long[:2] == (0.0, 0)
    assert same_short[:2] == (0.0, 0)


def test_market_ingestor_validates_ticks():
    bus = RecordingBus(FakeRedis())
    ingestor = MarketIngestor(bus)

    valid_tick = {
        "symbol": "BTC/USD",
        "price": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    invalid_tick = {
        "symbol": "BTC/USD",
        "price": -1,
        "bid": -2,
        "ask": -1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    assert ingestor._is_valid_tick(valid_tick) is True
    assert ingestor._is_valid_tick(invalid_tick) is False


@pytest.mark.asyncio
async def test_dashboard_ws_closes_without_redis_client():
    from api.routes.ws import dashboard_ws

    class FakeApp:
        def __init__(self):
            self.state = type("State", (), {"redis_client": None})()

    class FakeWebSocket:
        def __init__(self):
            self.app = FakeApp()
            self.accepted = False
            self.closed = None

        async def accept(self):
            self.accepted = True

        async def close(self, code):
            self.closed = code

    websocket = FakeWebSocket()
    await dashboard_ws(websocket)

    assert websocket.accepted is True
    assert websocket.closed == 1013


def _execution_handler(sql: str, params):
    if "FROM orders WHERE idempotency_key" in sql:
        return FakeResult(mapping_rows=[])
    if "RETURNING id" in sql:
        return FakeResult(scalar="order-123")
    return FakeResult()


def _reasoning_handler(sql: str, params):
    if "FROM vector_memory" in sql:
        return FakeResult(mapping_rows=[])
    if "SELECT payload FROM agent_logs" in sql:
        return FakeResult(first_row=None)
    return FakeResult()
