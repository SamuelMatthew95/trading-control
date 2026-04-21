from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.pipeline_agents import GradeAgent, ReflectionAgent
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

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.executed = []
        self._in_transaction = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        """Return a transaction context manager for async with session.begin()"""
        return self._TransactionContext(self)

    class _TransactionContext:
        """Inner class to handle transaction context management"""

        def __init__(self, session):
            self.session = session
            self._in_transaction = False

        async def __aenter__(self):
            self.session._in_transaction = True
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            self.session._in_transaction = False
            if exc_type is not None:
                # On exception, rollback would happen here
                pass
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

    async def get_position(self, symbol):
        return {"symbol": symbol, "side": "flat", "qty": 0.0, "entry_price": 0.0}


@pytest.mark.asyncio
async def test_paper_broker_updates_cash_and_position(monkeypatch):
    redis = FakeRedis()
    broker = PaperBroker(redis)
    monkeypatch.setattr("api.services.execution.brokers.paper.random.uniform", lambda a, b: 0.0002)

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
    monkeypatch.setattr(execution_module, "AsyncSessionFactory", FakeSessionFactory(session))

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
            # Must clear the weighted execution gate (final_score >= 0.55)
            "signal_confidence": 0.7,
            "reasoning_score": 0.7,
        }
    )

    # Engine publishes: executions (order_filled) then trade_performance
    # Find the order_filled event specifically
    execution_event = next(
        event for stream, event in bus.published if event.get("type") == "order_filled"
    )
    assert execution_event["type"] == "order_filled"
    assert execution_event["trace_id"] == "trace-abc"
    assert execution_event["fill_price"] == 101.25
    assert "filled_at" in execution_event

    # Also verify trade_performance event was published
    tp_event = next(
        event for stream, event in bus.published if event.get("type") == "trade_performance"
    )
    assert tp_event["symbol"] == "BTC/USD"
    assert "pnl" in tp_event


@pytest.mark.asyncio
async def test_reasoning_agent_fallback_publishes_logs_and_orders(monkeypatch):
    import api.services.agents.reasoning_agent as reasoning_module
    from api.config import settings

    session = FakeSession(_reasoning_handler)
    monkeypatch.setattr(reasoning_module, "AsyncSessionFactory", FakeSessionFactory(session))
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
    # ReasoningAgent now publishes advisory decisions to "decisions", not "orders"
    assert "decisions" in streams


@pytest.mark.asyncio
async def test_execution_engine_updates_existing_short_position_with_signed_math(
    monkeypatch,
):
    class CaptureSession(FakeSession):
        pass

    updates = []

    def handler(sql, params):
        if "SELECT id, side, qty FROM positions" in sql:
            return FakeResult(mapping_rows=[{"id": "pos-1", "side": "short", "qty": 5.0}])
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


# Removed test_trade_evaluator_skips_realized_pnl_for_same_direction_fills
# The learning.services module was deleted during cleanup
# TradeEvaluator class no longer exists


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


@pytest.mark.asyncio
async def test_full_chain_runs_from_signal_to_execution_grade_and_reflection(monkeypatch):
    import api.services.agents.pipeline_agents as pipeline_module
    import api.services.agents.reasoning_agent as reasoning_module
    import api.services.execution.execution_engine as execution_module
    import api.services.llm_router as llm_router_module

    redis = FakeRedis()
    bus = RecordingBus(redis)
    dlq = DLQManager(redis, bus)

    monkeypatch.setattr(execution_module, "is_db_available", lambda: False)
    monkeypatch.setattr(reasoning_module, "is_db_available", lambda: False)
    monkeypatch.setattr(reasoning_module, "embed_text", AsyncMock(return_value=[0.1] * 16))
    monkeypatch.setattr(reasoning_module, "search_vector_memory", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        reasoning_module,
        "call_llm_with_system",
        AsyncMock(
            return_value=(
                '{"action":"buy","confidence":0.82,"primary_edge":"momentum","risk_factors":[],"size_pct":0.02,"stop_atr_x":1.5,"rr_ratio":2.0}',
                0,
                0.0,
            )
        ),
    )
    monkeypatch.setattr(pipeline_module.settings, "GRADE_EVERY_N_FILLS", 1)
    monkeypatch.setattr(pipeline_module.settings, "REFLECT_EVERY_N_FILLS", 1)
    monkeypatch.setattr(
        llm_router_module,
        "call_llm_with_system",
        AsyncMock(
            return_value=(
                '{"summary":"ok","hypotheses":[{"type":"parameter","confidence":0.8,"description":"x"}]}',
                0,
                0.0,
            )
        ),
    )
    monkeypatch.setattr(GradeAgent, "_information_coefficient", AsyncMock(return_value=0.55))
    monkeypatch.setattr(GradeAgent, "_cost_efficiency", AsyncMock(return_value=0.8))
    monkeypatch.setattr(GradeAgent, "_latency_score", AsyncMock(return_value=0.9))

    reasoning = ReasoningAgent(bus, dlq, redis)
    engine = ExecutionEngine(bus, dlq, redis, FakeBroker())
    grade = GradeAgent(bus, dlq)
    reflection = ReflectionAgent(bus, dlq)

    signal = {
        "msg_id": "sig-1",
        "strategy_id": "strat-1",
        "symbol": "BTC/USD",
        "price": 100.0,
        "pct": 0.6,
        "direction": "bullish",
        "action": "buy",
        "qty": 1.0,
        "composite_score": 0.8,
        "confidence": 0.8,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": "trace-e2e-1",
        "schema_version": "v3",
    }

    await reasoning.process(signal)
    decision = next(event for stream, event in bus.published if stream == "decisions")
    await engine.process(decision)

    execution_event = next(event for stream, event in bus.published if stream == "executions")
    trade_perf = next(event for stream, event in bus.published if stream == "trade_performance")

    await grade.process("executions", "id-ex", execution_event)
    await grade.process("trade_performance", "id-tp", trade_perf)
    grade_event = next(event for stream, event in bus.published if stream == "agent_grades")

    for idx in range(3):
        await reflection.process("trade_performance", f"id-tp-{idx}", trade_perf)
    await reflection.process("agent_grades", "id-grade", grade_event)

    assert any(stream == "executions" for stream, _ in bus.published)
    assert any(stream == "trade_performance" for stream, _ in bus.published)
    assert any(stream == "agent_grades" for stream, _ in bus.published)
    assert any(stream == "reflection_outputs" for stream, _ in bus.published)


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
