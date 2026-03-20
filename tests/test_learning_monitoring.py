from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

from api.config import settings
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.main import collect_consumer_lag_metrics, collect_llm_cost_metric
from api.services.learning.evaluator import TradeEvaluator
from api.services.learning.ic_updater import ICUpdater
from api.services.learning.reflection import ReflectionService


class FakeResult:
    def __init__(self, rows=None, first_row=None, mapping_rows=None):
        self._rows = rows or []
        self._first_row = first_row
        self._mapping_rows = mapping_rows or []

    def mappings(self):
        return self

    def all(self):
        return self._mapping_rows or self._rows

    def first(self):
        if self._mapping_rows:
            return self._mapping_rows[0]
        return self._first_row


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.executed = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        return self.handler(sql, params)

    async def commit(self):
        self.commits += 1


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


class FakeRedis:
    def __init__(self):
        self.values = defaultdict(str)

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = str(value)
        return True

    async def incr(self, key):
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        return int(self.values[key])

    async def xadd(self, stream, payload):
        return "1-0"


class RecordingBus(EventBus):
    def __init__(self, redis_client):
        super().__init__(redis_client)
        self.published = []
        self.stream_info = {}

    async def publish(self, stream, event):
        self.published.append((stream, event))
        return "1-0"

    async def get_stream_info(self):
        return self.stream_info


@pytest.mark.asyncio
async def test_trade_evaluator_persists_metrics_and_publishes_learning_event(
    monkeypatch,
):
    import api.services.learning.evaluator as evaluator_module

    previous_time = datetime.now(timezone.utc) - timedelta(hours=1)
    session = FakeSession(
        lambda sql, params: _trade_evaluator_handler(sql, params, previous_time)
    )
    monkeypatch.setattr(
        evaluator_module, "AsyncSessionFactory", FakeSessionFactory(session)
    )

    redis = FakeRedis()
    bus = RecordingBus(redis)
    dlq = DLQManager(redis, bus)
    evaluator = TradeEvaluator(bus, dlq, redis)

    await evaluator.process(
        {
            "order_id": "order-1",
            "strategy_id": "strategy-1",
            "symbol": "BTC/USD",
            "side": "sell",
            "qty": 2,
            "fill_price": 110,
            "filled_at": datetime.now(timezone.utc).isoformat(),
            "trace_id": "trace-123",
        }
    )

    sqls = [sql for sql, _ in session.executed]
    assert any("INSERT INTO trade_performance" in sql for sql in sqls)
    assert any("INSERT INTO strategy_metrics" in sql for sql in sqls)
    assert any("UPDATE vector_memory SET outcome" in sql for sql in sqls)
    assert redis.values["reflection:trade_count"] == "1"
    assert bus.published[-1][0] == "learning_events"
    assert bus.published[-1][1]["event"] == "trade_evaluated"
    assert bus.published[-1][1]["pnl"] == 18.0


@pytest.mark.asyncio
async def test_reflection_service_triggers_and_resets_counter(monkeypatch):
    import api.services.learning.reflection as reflection_module

    trades = [
        (
            "BTC/USD",
            float(index - 8),
            90 + index,
            json.dumps({"momentum_score": index / 10, "ofi_score": 1 - index / 20}),
            json.dumps({"trace_id": f"t-{index}"}),
            datetime.now(timezone.utc) - timedelta(minutes=index),
        )
        for index in range(settings.REFLECTION_TRADE_THRESHOLD)
    ]
    session = FakeSession(
        lambda sql, params: FakeResult(rows=trades)
        if "FROM trade_performance" in sql
        else FakeResult()
    )
    monkeypatch.setattr(
        reflection_module, "AsyncSessionFactory", FakeSessionFactory(session)
    )
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)

    redis = FakeRedis()
    await redis.set("reflection:trade_count", settings.REFLECTION_TRADE_THRESHOLD)
    bus = RecordingBus(redis)
    service = ReflectionService(bus, redis, poll_interval_seconds=999)

    triggered = await service.run_once()

    assert triggered is True
    assert redis.values["reflection:trade_count"] == "0"
    assert any("INSERT INTO agent_logs" in sql for sql, _ in session.executed)
    assert [stream for stream, _ in bus.published] == ["agent_logs", "learning_events"]
    assert bus.published[0][1]["log_type"] == "reflection"


@pytest.mark.asyncio
async def test_ic_updater_zeroes_negative_ic_and_normalizes(monkeypatch):
    import api.services.learning.ic_updater as ic_module

    rows = [
        (json.dumps({"factor_a": 1, "factor_b": 3}), 1.0),
        (json.dumps({"factor_a": 2, "factor_b": 2}), 2.0),
        (json.dumps({"factor_a": 3, "factor_b": 1}), 3.0),
    ]
    session = FakeSession(
        lambda sql, params: FakeResult(rows=rows)
        if "SELECT factor_attribution, pnl FROM trade_performance" in sql
        else FakeResult()
    )
    monkeypatch.setattr(ic_module, "AsyncSessionFactory", FakeSessionFactory(session))

    redis = FakeRedis()
    updater = ICUpdater(redis)

    weights = await updater.run_once(datetime.now(timezone.utc))

    stored = json.loads(redis.values["alpha:ic_weights"])
    assert weights == stored
    assert stored["factor_a"] == 1.0
    assert stored["factor_b"] == 0.0
    assert (
        sum(1 for sql, _ in session.executed if "INSERT INTO factor_ic_history" in sql)
        == 2
    )


@pytest.mark.asyncio
async def test_monitor_helpers_publish_metrics_and_alerts(monkeypatch):
    recorded = []

    async def fake_record(bus, metric_name, value, labels=None):
        recorded.append((metric_name, value, labels or {}))

    monkeypatch.setattr("api.main._record_system_metric", fake_record)
    monkeypatch.setattr(settings, "MAX_CONSUMER_LAG_ALERT", 5)
    monkeypatch.setattr(settings, "ANTHROPIC_COST_ALERT_USD", 5.0)

    redis = FakeRedis()
    await redis.set(f"llm:cost:{datetime.now(timezone.utc).date().isoformat()}", 7.25)
    bus = RecordingBus(redis)
    bus.stream_info = {
        "signals": {"lag": 9, "length": 12, "groups": 1},
        "orders": {"lag": 2, "length": 4, "groups": 1},
    }

    await collect_consumer_lag_metrics(bus)
    await collect_llm_cost_metric(bus, redis)

    metric_names = [name for name, _, _ in recorded]
    assert "stream_lag:signals" in metric_names
    assert "stream_lag:orders" in metric_names
    assert "llm_cost_usd" in metric_names
    alerts = [event for stream, event in bus.published if stream == "risk_alerts"]
    assert any(alert["type"] == "consumer_lag" for alert in alerts)
    assert any(alert["type"] == "llm_cost" for alert in alerts)


def _trade_evaluator_handler(sql: str, params, previous_time: datetime):
    if "SELECT o.side, o.qty, o.price" in sql:
        return FakeResult(
            mapping_rows=[
                {
                    "side": "buy",
                    "qty": 2.0,
                    "price": 101.0,
                    "exit_price": 101.0,
                    "filled_at": previous_time,
                    "created_at": previous_time,
                }
            ]
        )
    if "SELECT signal_data FROM agent_runs WHERE trace_id" in sql:
        return FakeResult(
            first_row=[
                {
                    "context": {
                        "ofi_score": 0.6,
                        "momentum_score": 0.8,
                        "volume_ratio": 1.2,
                    },
                    "composite_score": 0.9,
                }
            ]
        )
    if "SELECT tp.pnl FROM trade_performance" in sql:
        return FakeResult(rows=[(12.0,), (18.0,)])
    if "SELECT id FROM strategy_metrics" in sql:
        return FakeResult(mapping_rows=[])
    if "SELECT id FROM vector_memory" in sql:
        return FakeResult(mapping_rows=[{"id": "vm-1"}])
    return FakeResult()
