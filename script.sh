#!/bin/bash
set -e

echo "=== Step 1: Checking you're in the right repo ==="
if [ ! -f "api/main.py" ]; then
  echo "ERROR: Run this script from the root of the trading-control repo"
  echo "       cd /path/to/trading-control && bash apply_patch.sh"
  exit 1
fi

echo "=== Step 2: Checking current branch ==="
BRANCH=$(git branch --show-current)
echo "Current branch: $BRANCH"

if [ "$BRANCH" != "codex/implement-codex-plan-for-ai-trading-bot" ]; then
  echo "Switching to the correct branch..."
  git checkout codex/implement-codex-plan-for-ai-trading-bot
fi

echo "=== Step 3: Pulling latest ==="
git pull origin codex/implement-codex-plan-for-ai-trading-bot --rebase || true

echo "=== Step 4: Creating all new files from patch ==="

# ── api/alembic.ini ──────────────────────────────────────────────────────────
cat > api/alembic.ini << 'EOF'
[alembic]
script_location = %(here)s/alembic
prepend_sys_path = %(here)s/..
sqlalchemy.url = ${DATABASE_URL}

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers = console
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
EOF

# ── api/alembic/ directories ─────────────────────────────────────────────────
mkdir -p api/alembic/versions

# ── api/alembic/env.py ───────────────────────────────────────────────────────
cat > api/alembic/env.py << 'EOF'
from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.config import get_database_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_database_url())

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    assert isinstance(connectable, AsyncEngine)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
EOF

# ── api/alembic/versions/0001_initial.py ─────────────────────────────────────
cat > api/alembic/versions/0001_initial.py << 'PYEOF'
"""Initial Phase 2 schema."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UTC_NOW = sa.text("TIMEZONE('utc', NOW())")
UUID_DEFAULT = sa.text("gen_random_uuid()")


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def get_col_spec(self, **kw):
        return f"vector({self.dimensions})"


def _uuid_column(name: str = "id") -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=UUID_DEFAULT,
    )


def _timestamp_column(name: str = "created_at") -> sa.Column:
    return sa.Column(
        name,
        postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=UTC_NOW,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "strategies",
        _uuid_column(),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _timestamp_column(),
    )

    op.create_table(
        "orders",
        _uuid_column(),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("broker_order_id", sa.String(length=255), nullable=True),
        _timestamp_column(),
        sa.Column("filled_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "positions",
        _uuid_column(),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("unrealised_pnl", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("opened_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=UTC_NOW),
    )

    op.create_table(
        "agent_runs",
        _uuid_column(),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("signal_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("primary_edge", sa.String(length=255), nullable=False),
        sa.Column("risk_factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("size_pct", sa.Float(), nullable=False),
        sa.Column("stop_atr_x", sa.Float(), nullable=False),
        sa.Column("rr_ratio", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _timestamp_column(),
    )

    op.create_table(
        "agent_logs",
        _uuid_column(),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("log_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _timestamp_column(),
    )

    op.create_table(
        "vector_memory",
        _uuid_column(),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _timestamp_column(),
    )
    op.execute(
        "CREATE INDEX vector_memory_embedding_idx "
        "ON vector_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "trade_performance",
        _uuid_column(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("pnl", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("holding_secs", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("market_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("factor_attribution", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _timestamp_column(),
    )

    op.create_table(
        "strategy_metrics",
        _uuid_column(),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("avg_pnl", sa.Float(), nullable=False),
        sa.Column("sharpe", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=UTC_NOW),
    )

    op.create_table(
        "factor_ic_history",
        _uuid_column(),
        sa.Column("factor_name", sa.String(length=128), nullable=False),
        sa.Column("ic_score", sa.Float(), nullable=False),
        sa.Column("computed_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=UTC_NOW),
    )

    op.create_table(
        "system_metrics",
        _uuid_column(),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timestamp", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=UTC_NOW),
    )

    op.create_table(
        "audit_log",
        _uuid_column(),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _timestamp_column(),
    )

    op.create_table(
        "order_reconciliation",
        _uuid_column(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("discrepancy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _timestamp_column(),
    )

    op.create_table(
        "llm_cost_tracking",
        _uuid_column(),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        _timestamp_column(),
    )

    op.execute("CREATE INDEX audit_log_created_at_desc_idx ON audit_log (created_at DESC)")
    op.execute("CREATE INDEX system_metrics_metric_name_timestamp_desc_idx ON system_metrics (metric_name, timestamp DESC)")

    strategies_table = sa.table(
        "strategies",
        sa.column("name", sa.String),
        sa.column("rules", postgresql.JSONB),
        sa.column("risk_limits", postgresql.JSONB),
        sa.column("is_active", sa.Boolean),
    )

    op.bulk_insert(strategies_table, [
        {
            "name": "BTC_MOMENTUM_V3",
            "rules": {"universe": ["BTC/USD"], "entry": {"trend_window": "4h", "trigger": "breakout_with_volume_confirmation", "minimum_composite_score": 0.72}, "exit": {"stop_loss": "2.2_atr", "take_profit": "trailing_3.5_atr", "time_stop_hours": 18}, "filters": {"avoid_high_impact_news_minutes": 30, "require_positive_funding_regime": False}},
            "risk_limits": {"max_position_pct": 0.08, "max_daily_loss_pct": 0.025, "max_open_positions": 1, "slippage_bps_cap": 18},
            "is_active": True,
        },
        {
            "name": "ETH_REVERSAL_V2",
            "rules": {"universe": ["ETH/USD"], "entry": {"signal_family": "mean_reversion", "oversold_rsi_threshold": 28, "require_orderflow_divergence": True}, "exit": {"stop_loss": "1.6_atr", "first_target": "session_vwap", "final_target": "2.8_atr"}, "filters": {"min_liquidity_usd": 5000000, "disable_during_fomc_window": True}},
            "risk_limits": {"max_position_pct": 0.06, "max_daily_loss_pct": 0.02, "max_open_positions": 1, "slippage_bps_cap": 15},
            "is_active": True,
        },
    ])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS system_metrics_metric_name_timestamp_desc_idx")
    op.execute("DROP INDEX IF EXISTS audit_log_created_at_desc_idx")
    op.execute("DROP INDEX IF EXISTS vector_memory_embedding_idx")
    op.drop_table("llm_cost_tracking")
    op.drop_table("order_reconciliation")
    op.drop_table("audit_log")
    op.drop_table("system_metrics")
    op.drop_table("factor_ic_history")
    op.drop_table("strategy_metrics")
    op.drop_table("trade_performance")
    op.drop_table("vector_memory")
    op.drop_table("agent_logs")
    op.drop_table("agent_runs")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("strategies")
PYEOF

# ── api/db.py ────────────────────────────────────────────────────────────────
cat > api/db.py << 'EOF'
"""Async SQLAlchemy session management primitives for FastAPI."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import get_database_url

engine = create_async_engine(get_database_url(), pool_pre_ping=True)
AsyncSessionFactory = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        yield session
EOF

# ── api/redis_client.py ──────────────────────────────────────────────────────
cat > api/redis_client.py << 'EOF'
"""Redis async client helpers."""

from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis

from api.config import settings

_redis_client: Optional[Redis] = None


async def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        redis_url = settings.REDIS_URL or "redis://localhost:6379/0"
        _redis_client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        await _redis_client.ping()
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
EOF

# ── api/events/__init__.py ───────────────────────────────────────────────────
mkdir -p api/events
cat > api/events/__init__.py << 'EOF'
"""Event subsystem package."""
EOF

# ── api/events/bus.py ────────────────────────────────────────────────────────
cat > api/events/bus.py << 'EOF'
"""Redis stream event bus primitives."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

STREAMS = (
    "market_ticks",
    "signals",
    "orders",
    "executions",
    "risk_alerts",
    "learning_events",
    "system_metrics",
    "agent_logs",
)
DEFAULT_GROUP = "workers"


class EventBus:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def publish(self, stream: str, event: dict[str, Any]) -> str:
        payload = {"payload": json.dumps(event, default=str)}
        message_id = await self.redis.xadd(stream, payload)
        return str(message_id)

    async def consume(self, stream: str, group: str, consumer: str, count: int = 10, block_ms: int = 500) -> list[tuple[str, dict[str, Any]]]:
        messages = await self.redis.xreadgroup(
            groupname=group, consumername=consumer,
            streams={stream: ">"}, count=count, block=block_ms,
        )
        return self._decode_message_batch(messages)

    async def acknowledge(self, stream: str, group: str, *ids: str) -> int:
        if not ids:
            return 0
        return int(await self.redis.xack(stream, group, *ids))

    async def create_groups(self) -> None:
        for stream in STREAMS:
            try:
                await self.redis.xgroup_create(stream, DEFAULT_GROUP, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def get_stream_info(self) -> dict[str, dict[str, int]]:
        info: dict[str, dict[str, int]] = {}
        for stream in STREAMS:
            length = int(await self.redis.xlen(stream))
            try:
                groups = await self.redis.xinfo_groups(stream)
            except ResponseError:
                groups = []
            lag = 0
            for g in groups:
                lag = max(lag, int(g.get("lag") or g.get("pending") or g.get(b"lag") or g.get(b"pending") or 0))
            info[stream] = {"lag": lag, "length": length, "groups": len(groups)}
        return info

    async def reclaim_stale(self, stream: str, group: str, min_idle_ms: int = 60000) -> list[tuple[str, dict[str, Any]]]:
        reclaimed = await self.redis.xautoclaim(stream, group, DEFAULT_GROUP, min_idle_ms, start_id="0-0")
        return self._decode_autoclaim(reclaimed)

    def _decode_autoclaim(self, reclaimed: Any) -> list[tuple[str, dict[str, Any]]]:
        if isinstance(reclaimed, tuple):
            _, messages, *_ = reclaimed
        else:
            messages = reclaimed[1] if reclaimed else []
        return self._decode_entries(messages)

    def _decode_message_batch(self, messages: Any) -> list[tuple[str, dict[str, Any]]]:
        decoded: list[tuple[str, dict[str, Any]]] = []
        for _, entries in messages:
            decoded.extend(self._decode_entries(entries))
        return decoded

    def _decode_entries(self, entries: Any) -> list[tuple[str, dict[str, Any]]]:
        decoded: list[tuple[str, dict[str, Any]]] = []
        for msg_id, fields in entries:
            payload_raw = fields.get("payload") or fields.get(b"payload") or "{}"
            if isinstance(payload_raw, bytes):
                payload_raw = payload_raw.decode("utf-8")
            decoded.append((str(msg_id), json.loads(payload_raw)))
        return decoded


async def create_groups(redis_client: Redis) -> None:
    await EventBus(redis_client).create_groups()
EOF

# ── api/events/dlq.py ────────────────────────────────────────────────────────
cat > api/events/dlq.py << 'EOF'
"""Dead-letter queue management for Redis streams."""

from __future__ import annotations

import json
from typing import Any

from api.events.bus import STREAMS, EventBus


class DLQManager:
    def __init__(self, redis_client, bus: EventBus):
        self.redis = redis_client
        self.bus = bus

    async def push(self, stream: str, event_id: str, payload: dict[str, Any], error: str, retries: int) -> None:
        record = {"stream": stream, "event_id": event_id, "payload": payload, "error": error, "retries": retries}
        await self.redis.hset(f"dlq:{stream}", event_id, json.dumps(record, default=str))

    async def should_dlq(self, event_id: str) -> bool:
        retries_key = f"dlq:retries:{event_id}"
        retries = int(await self.redis.incr(retries_key))
        await self.redis.expire(retries_key, 86400)
        return retries >= 3

    async def get_all(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for stream in STREAMS:
            values = await self.redis.hgetall(f"dlq:{stream}")
            for value in values.values():
                raw = value.decode("utf-8") if isinstance(value, bytes) else value
                items.append(json.loads(raw))
        return items

    async def replay(self, event_id: str) -> bool:
        for stream in STREAMS:
            raw = await self.redis.hget(f"dlq:{stream}", event_id)
            if raw is None:
                continue
            raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            record = json.loads(raw)
            await self.bus.publish(record["stream"], record["payload"])
            await self.clear(event_id)
            return True
        return False

    async def clear(self, event_id: str) -> None:
        for stream in STREAMS:
            await self.redis.hdel(f"dlq:{stream}", event_id)
        await self.redis.delete(f"dlq:retries:{event_id}")
EOF

# ── api/events/consumer.py ───────────────────────────────────────────────────
cat > api/events/consumer.py << 'EOF'
"""Base consumer with at-least-once stream semantics."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured


class BaseStreamConsumer(ABC):
    def __init__(self, bus: EventBus, dlq: DLQManager, stream: str, group: str, consumer: str):
        self.bus = bus
        self.dlq = dlq
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"consumer:{self.stream}")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    @abstractmethod
    async def process(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _run(self) -> None:
        reclaimed = await self.bus.reclaim_stale(self.stream, self.group)
        for msg_id, data in reclaimed:
            await self._handle_message(msg_id, data)
        while self._running:
            messages = await self.bus.consume(self.stream, self.group, self.consumer, count=10, block_ms=500)
            for msg_id, data in messages:
                await self._handle_message(msg_id, data)

    async def _handle_message(self, msg_id: str, data: dict[str, Any]) -> None:
        try:
            await self.process(data)
            await self.bus.acknowledge(self.stream, self.group, msg_id)
        except Exception as exc:  # noqa: BLE001
            send_to_dlq = await self.dlq.should_dlq(msg_id)
            if send_to_dlq:
                retries_key = f"dlq:retries:{msg_id}"
                retries = int(await self.dlq.redis.get(retries_key) or 0)
                await self.dlq.push(self.stream, msg_id, data, error=str(exc), retries=retries)
                await self.bus.acknowledge(self.stream, self.group, msg_id)
            log_structured("warning", "Stream consumer failed to process message",
                           stream=self.stream, message_id=msg_id, error=str(exc), dlq=send_to_dlq)
EOF

# ── api/services/agents/ ─────────────────────────────────────────────────────
mkdir -p api/services/agents
cat > api/services/agents/__init__.py << 'EOF'
"""Agent services package."""
EOF

# ── api/services/execution/ ──────────────────────────────────────────────────
mkdir -p api/services/execution/brokers
cat > api/services/execution/__init__.py << 'EOF'
"""Execution services package."""
EOF
cat > api/services/execution/brokers/__init__.py << 'EOF'
"""Execution broker backends."""
EOF

# ── api/services/execution/brokers/paper.py ─────────────────────────────────
cat > api/services/execution/brokers/paper.py << 'EOF'
"""Paper broker backed by Redis state."""

from __future__ import annotations

import json
import random
import uuid
from typing import Any

from redis.asyncio import Redis


class PaperBroker:
    CASH_KEY = "paper:cash"
    POSITION_KEY_PREFIX = "paper:positions:"
    ORDER_KEY_PREFIX = "paper:order:"
    DEFAULT_CASH = 100000.0

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def place_order(self, symbol: str, side: str, qty: float, price: float) -> dict[str, Any]:
        await self.redis.setnx(self.CASH_KEY, self.DEFAULT_CASH)
        normalized_side = side.lower()
        slippage = random.uniform(0.0001, 0.0005)
        direction = 1 if normalized_side in {"buy", "long"} else -1
        fill_price = round(price + (direction * slippage), 8)
        notional = qty * fill_price
        cash = await self.get_cash()
        if direction > 0:
            cash -= notional
        else:
            cash += notional
        await self.redis.set(self.CASH_KEY, cash)
        position_key = f"{self.POSITION_KEY_PREFIX}{symbol}"
        current_position = await self.get_position(symbol)
        current_qty = float(current_position.get("qty", 0.0))
        new_qty = current_qty + (qty * direction)
        position_payload = {"symbol": symbol, "side": "long" if new_qty >= 0 else "short", "qty": new_qty, "entry_price": fill_price, "current_price": fill_price}
        await self.redis.set(position_key, json.dumps(position_payload))
        broker_order_id = str(uuid.uuid4())
        order_payload = {"broker_order_id": broker_order_id, "symbol": symbol, "side": normalized_side, "filled_qty": qty, "fill_price": fill_price, "status": "filled"}
        await self.redis.set(f"{self.ORDER_KEY_PREFIX}{broker_order_id}", json.dumps(order_payload))
        return order_payload

    async def get_position(self, symbol: str) -> dict[str, Any]:
        raw = await self.redis.get(f"{self.POSITION_KEY_PREFIX}{symbol}")
        if not raw:
            return {"symbol": symbol, "side": "flat", "qty": 0.0, "entry_price": 0.0, "current_price": 0.0}
        return json.loads(raw)

    async def get_cash(self) -> float:
        await self.redis.setnx(self.CASH_KEY, self.DEFAULT_CASH)
        return float(await self.redis.get(self.CASH_KEY) or self.DEFAULT_CASH)

    async def get_order_status(self, broker_order_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(f"{self.ORDER_KEY_PREFIX}{broker_order_id}")
        return json.loads(raw) if raw else None
EOF

# ── api/services/execution/execution_engine.py ──────────────────────────────
cat > api/services/execution/execution_engine.py << 'EOF'
"""Order execution engine backed by the paper broker."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.execution.brokers.paper import PaperBroker

LARGE_ORDER_THRESHOLD = 10.0


class ExecutionEngine(BaseStreamConsumer):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis, broker: PaperBroker):
        super().__init__(bus, dlq, stream="orders", group=DEFAULT_GROUP, consumer="execution-engine")
        self.redis = redis_client
        self.broker = broker

    async def process(self, data: dict[str, Any]) -> None:
        if await self.redis.get("kill_switch:active") == "1":
            raise RuntimeError("KillSwitchActive")

        strategy_id = str(data["strategy_id"])
        symbol = str(data["symbol"])
        side = str(data["side"]).lower()
        qty = float(data["qty"])
        price = float(data["price"])
        order_timestamp = self._parse_timestamp(data.get("timestamp"))
        idempotency_key = self._build_idempotency_key(strategy_id, symbol, side, order_timestamp)
        lock_key = f"order_lock:{symbol}"
        lock_value = str(uuid.uuid4())

        async with AsyncSessionFactory() as session:
            existing = await session.execute(
                text("SELECT id, status, broker_order_id, idempotency_key FROM orders WHERE idempotency_key = :idempotency_key"),
                {"idempotency_key": idempotency_key},
            )
            existing_row = existing.mappings().first()
            if existing_row is not None:
                log_structured("info", "Skipping duplicate order event", idempotency_key=idempotency_key, order_id=str(existing_row["id"]))
                return

            lock_acquired = await self.redis.set(lock_key, lock_value, ex=5, nx=True)
            if not lock_acquired:
                raise RuntimeError(f"Order lock already held for {symbol}")

            order_id: str | None = None
            vwap_plan = self._build_vwap_plan(qty)
            try:
                inserted = await session.execute(
                    text("INSERT INTO orders (strategy_id, symbol, side, qty, price, status, idempotency_key, broker_order_id) VALUES (:strategy_id, :symbol, :side, :qty, :price, 'pending', :idempotency_key, NULL) RETURNING id"),
                    {"strategy_id": strategy_id, "symbol": symbol, "side": side, "qty": qty, "price": price, "idempotency_key": idempotency_key},
                )
                order_id = str(inserted.scalar_one())
                await session.flush()

                broker_result = await self.broker.place_order(symbol, side, qty, price)
                filled_at = datetime.now(timezone.utc)

                await session.execute(
                    text("UPDATE orders SET status = :status, broker_order_id = :broker_order_id, price = :fill_price, filled_at = :filled_at WHERE id = :order_id"),
                    {"status": broker_result["status"], "broker_order_id": broker_result["broker_order_id"], "fill_price": broker_result["fill_price"], "filled_at": filled_at, "order_id": order_id},
                )
                await self._upsert_position(session, strategy_id=strategy_id, symbol=symbol, side=side, qty=qty, fill_price=float(broker_result["fill_price"]))
                await self._insert_audit_log(session, event_type="order_placed", payload={"order_id": order_id, "strategy_id": strategy_id, "symbol": symbol, "side": side, "qty": qty, "broker_order_id": broker_result["broker_order_id"], "vwap_plan": vwap_plan})
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await self.redis.delete(lock_key)

        await self.bus.publish("executions", {"type": "order_filled", "order_id": order_id, "strategy_id": strategy_id, "symbol": symbol, "side": side, "qty": qty, "price": price, "fill_price": float(broker_result["fill_price"]), "filled_at": filled_at.isoformat(), "idempotency_key": idempotency_key, "trace_id": data.get("trace_id"), "vwap_plan": vwap_plan})

    def _build_idempotency_key(self, strategy_id: str, symbol: str, side: str, timestamp: datetime) -> str:
        ts_minute = timestamp.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        return f"{strategy_id}_{symbol}_{side}_{ts_minute}"

    def _build_vwap_plan(self, qty: float) -> list[float] | None:
        if qty <= LARGE_ORDER_THRESHOLD:
            return None
        slice_qty = round(qty / 3, 8)
        return [slice_qty, slice_qty, round(qty - (slice_qty * 2), 8)]

    def _parse_timestamp(self, value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    async def _upsert_position(self, session, strategy_id: str, symbol: str, side: str, qty: float, fill_price: float) -> None:
        existing = await session.execute(
            text("SELECT id, side, qty FROM positions WHERE strategy_id = :strategy_id AND symbol = :symbol"),
            {"strategy_id": strategy_id, "symbol": symbol},
        )
        row = existing.mappings().first()
        signed_qty = qty if side in {"buy", "long"} else (-1 * qty)
        if row is None:
            await session.execute(
                text("INSERT INTO positions (symbol, side, qty, entry_price, current_price, unrealised_pnl, strategy_id) VALUES (:symbol, :side, :qty, :entry_price, :current_price, :unrealised_pnl, :strategy_id)"),
                {"symbol": symbol, "side": "long" if signed_qty >= 0 else "short", "qty": abs(signed_qty), "entry_price": fill_price, "current_price": fill_price, "unrealised_pnl": 0.0, "strategy_id": strategy_id},
            )
            return
        existing_side = str(row["side"]).lower()
        existing_qty = float(row["qty"])
        existing_signed_qty = existing_qty if existing_side in {"long", "buy"} else (-1 * existing_qty)
        new_qty = existing_signed_qty + signed_qty
        next_side = "flat" if abs(new_qty) < 1e-9 else ("long" if new_qty > 0 else "short")
        await session.execute(
            text("UPDATE positions SET side = :side, qty = :qty, current_price = :current_price WHERE id = :position_id"),
            {"side": next_side, "qty": abs(new_qty), "current_price": fill_price, "position_id": row["id"]},
        )

    async def _insert_audit_log(self, session, event_type: str, payload: dict[str, Any]) -> None:
        await session.execute(
            text("INSERT INTO audit_log (event_type, payload) VALUES (:event_type, CAST(:payload AS JSONB))"),
            {"event_type": event_type, "payload": json.dumps(payload, default=str)},
        )
EOF

# ── api/services/execution/reconciler.py ────────────────────────────────────
cat > api/services/execution/reconciler.py << 'EOF'
"""Periodic paper broker reconciliation."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from api.db import AsyncSessionFactory
from api.observability import log_structured
from api.services.execution.brokers.paper import PaperBroker


class OrderReconciler:
    def __init__(self, broker: PaperBroker, interval_seconds: int = 300):
        self.broker = broker
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="order-reconciler")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("SELECT id, broker_order_id, status FROM orders WHERE status IN ('pending', 'partial') AND created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            rows = result.mappings().all()
            for row in rows:
                broker_status = await self.broker.get_order_status(str(row["broker_order_id"]))
                discrepancy = self._build_discrepancy(row, broker_status)
                if discrepancy is None:
                    continue
                await session.execute(
                    text("INSERT INTO order_reconciliation (order_id, discrepancy, resolved) VALUES (:order_id, CAST(:discrepancy AS JSONB), true)"),
                    {"order_id": row["id"], "discrepancy": json.dumps(discrepancy, default=str)},
                )
                if broker_status is not None:
                    await session.execute(text("UPDATE orders SET status = :status WHERE id = :order_id"), {"status": broker_status["status"], "order_id": row["id"]})
                await session.execute(text("INSERT INTO audit_log (event_type, payload) VALUES ('order_reconciled', CAST(:payload AS JSONB))"), {"payload": json.dumps(discrepancy, default=str)})
            await session.commit()

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                log_structured("warning", "Order reconciliation failed", error=str(exc))
            await asyncio.sleep(self.interval_seconds)

    def _build_discrepancy(self, order_row: dict[str, Any], broker_status: dict[str, Any] | None) -> dict[str, Any] | None:
        if broker_status is None:
            return {"order_id": str(order_row["id"]), "broker_order_id": str(order_row["broker_order_id"]), "db_status": order_row["status"], "broker_status": "missing"}
        if broker_status.get("status") == order_row["status"]:
            return None
        return {"order_id": str(order_row["id"]), "broker_order_id": str(order_row["broker_order_id"]), "db_status": order_row["status"], "broker_status": broker_status.get("status")}
EOF

# ── api/services/market_ingestor.py ─────────────────────────────────────────
cat > api/services/market_ingestor.py << 'EOF'
"""Market data ingestion for paper-mode simulations."""

from __future__ import annotations

import asyncio
import random
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.events.bus import EventBus
from api.observability import log_structured


class MarketIngestor:
    SYMBOLS = {"BTC/USD": 67000.0, "ETH/USD": 3500.0, "SOL/USD": 145.0, "SPY": 510.0, "AAPL": 178.0, "NVDA": 875.0}

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._prices = dict(self.SYMBOLS)
        self._running = False
        self._live_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        if settings.BROKER_MODE == "paper":
            for symbol in self.SYMBOLS:
                if symbol not in self._tasks or self._tasks[symbol].done():
                    self._tasks[symbol] = asyncio.create_task(self._run_symbol(symbol), name=f"market:{symbol}")
            return
        self._live_task = asyncio.create_task(self._connect_live(), name="market:live")

    async def stop(self) -> None:
        self._running = False
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        if self._live_task is not None:
            self._live_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._live_task
            self._live_task = None

    async def _run_symbol(self, symbol: str) -> None:
        drift = 0.0
        while self._running:
            drift = (drift * 0.95) + random.gauss(0.0, 0.0001)
            self._prices[symbol] += random.gauss(drift, 0.0005)
            price = round(self._prices[symbol], 6)
            tick = {"symbol": symbol, "price": price, "bid": round(price - 0.01, 6), "ask": round(price + 0.01, 6), "volume": round(random.uniform(0.1, 10.0), 6), "timestamp": datetime.now(timezone.utc).isoformat(), "source": "paper"}
            if self._is_valid_tick(tick):
                await self.bus.publish("market_ticks", tick)
            else:
                log_structured("debug", "Rejected invalid paper tick", tick=tick)
            await asyncio.sleep(0.25)

    def _is_valid_tick(self, tick: dict[str, Any]) -> bool:
        try:
            timestamp = datetime.fromisoformat(str(tick["timestamp"]))
            age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
        except Exception:  # noqa: BLE001
            return False
        return (tick.get("symbol") in self.SYMBOLS and float(tick.get("price", 0)) > 0 and float(tick.get("bid", 0)) > 0 and float(tick.get("ask", 0)) >= float(tick.get("bid", 0)) and age_seconds < 60)

    async def _connect_live(self) -> None:
        backoff = 1
        while self._running:
            try:
                log_structured("info", "Live market connector stub waiting for implementation", backoff_seconds=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except asyncio.CancelledError:
                raise
EOF

# ── api/services/learning/ ───────────────────────────────────────────────────
mkdir -p api/services/learning

# Rename learning.py to learning/__init__.py if it exists as a file
if [ -f "api/services/learning.py" ]; then
  cp api/services/learning.py api/services/learning/__init__.py.bak
fi

# Append new exports to existing __init__.py or create it
if [ ! -f "api/services/learning/__init__.py" ]; then
  cp api/services/learning.py api/services/learning/__init__.py 2>/dev/null || echo '"""Learning services package."""' > api/services/learning/__init__.py
fi

# Add the new imports at the end if not already there
grep -q "TradeEvaluator" api/services/learning/__init__.py || cat >> api/services/learning/__init__.py << 'EOF'


from api.services.learning.evaluator import TradeEvaluator
from api.services.learning.ic_updater import ICUpdater
from api.services.learning.reflection import ReflectionService

__all__ = [
    "AgentLearningService",
    "TradeEvaluator",
    "ReflectionService",
    "ICUpdater",
]
EOF

# ── api/services/learning/evaluator.py ──────────────────────────────────────
cat > api/services/learning/evaluator.py << 'EOF'
"""Execution consumer that computes realized trade learning metrics."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import text

from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured

FACTOR_KEYS = ("ofi_score", "momentum_score", "volume_ratio", "composite_score", "volatility_score", "trend_score")


class TradeEvaluator(BaseStreamConsumer):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client):
        super().__init__(bus, dlq, stream="executions", group=DEFAULT_GROUP, consumer="trade-evaluator")
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        order_id = str(data["order_id"])
        strategy_id = str(data["strategy_id"])
        symbol = str(data["symbol"])
        side = str(data.get("side", "buy")).lower()
        qty = float(data.get("qty", 0.0) or 0.0)
        fill_price = float(data.get("fill_price", data.get("price", 0.0)) or 0.0)
        trace_id = data.get("trace_id")
        filled_at = self._parse_timestamp(data.get("filled_at"))

        async with AsyncSessionFactory() as session:
            prior_trade = await self._fetch_prior_trade(session, strategy_id, symbol, order_id)
            signal_payload = await self._fetch_signal_payload(session, trace_id, strategy_id, symbol)
            factor_attribution = self._build_factor_attribution(signal_payload)
            pnl, holding_secs, entry_price = self._compute_trade_metrics(prior_trade=prior_trade, side=side, qty=qty, fill_price=fill_price, filled_at=filled_at)
            market_context = {"strategy_id": strategy_id, "symbol": symbol, "side": side, "qty": qty, "trace_id": trace_id, "fill_price": fill_price, "timestamp": filled_at.isoformat(), "vwap_plan": data.get("vwap_plan")}

            await session.execute(
                text("INSERT INTO trade_performance (order_id, symbol, pnl, holding_secs, entry_price, exit_price, market_context, factor_attribution) VALUES (:order_id, :symbol, :pnl, :holding_secs, :entry_price, :exit_price, CAST(:market_context AS JSONB), CAST(:factor_attribution AS JSONB))"),
                {"order_id": order_id, "symbol": symbol, "pnl": pnl, "holding_secs": holding_secs, "entry_price": entry_price, "exit_price": fill_price, "market_context": json.dumps(market_context, default=str), "factor_attribution": json.dumps(factor_attribution, default=str)},
            )
            await self._update_strategy_metrics(session, strategy_id)
            await self._update_vector_memory_outcome(session, trace_id=trace_id, pnl=pnl, holding_secs=holding_secs, factor_attribution=factor_attribution)
            await session.commit()

        reflection_count = int(await self.redis.incr("reflection:trade_count"))
        await self.bus.publish("learning_events", {"type": "learning_event", "event": "trade_evaluated", "order_id": order_id, "strategy_id": strategy_id, "symbol": symbol, "pnl": pnl, "holding_secs": holding_secs, "factor_attribution": factor_attribution, "reflection_trade_count": reflection_count, "trace_id": trace_id})

    async def _fetch_prior_trade(self, session, strategy_id: str, symbol: str, order_id: str) -> dict[str, Any] | None:
        result = await session.execute(
            text("SELECT o.side, o.qty, o.price, o.filled_at, tp.exit_price, tp.created_at FROM orders o LEFT JOIN trade_performance tp ON tp.order_id = o.id WHERE o.strategy_id = :strategy_id AND o.symbol = :symbol AND o.id != :order_id AND o.status = 'filled' ORDER BY COALESCE(o.filled_at, o.created_at) DESC LIMIT 1"),
            {"strategy_id": strategy_id, "symbol": symbol, "order_id": order_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _fetch_signal_payload(self, session, trace_id: str | None, strategy_id: str, symbol: str) -> dict[str, Any]:
        if trace_id:
            result = await session.execute(text("SELECT signal_data FROM agent_runs WHERE trace_id = :trace_id ORDER BY created_at DESC LIMIT 1"), {"trace_id": trace_id})
            row = result.first()
            if row is not None:
                return self._json_value(row[0])
        fallback = await session.execute(text("SELECT signal_data FROM agent_runs WHERE strategy_id = :strategy_id AND symbol = :symbol ORDER BY created_at DESC LIMIT 1"), {"strategy_id": strategy_id, "symbol": symbol})
        row = fallback.first()
        return self._json_value(row[0]) if row is not None else {}

    def _build_factor_attribution(self, signal_payload: dict[str, Any]) -> dict[str, float]:
        context = signal_payload.get("context") if isinstance(signal_payload, dict) else {}
        context = context if isinstance(context, dict) else {}
        attribution: dict[str, float] = {}
        for key in FACTOR_KEYS:
            raw = context.get(key, signal_payload.get(key, 0.0))
            try:
                attribution[key] = round(float(raw or 0.0), 6)
            except (TypeError, ValueError):
                attribution[key] = 0.0
        return attribution

    def _compute_trade_metrics(self, *, prior_trade: dict[str, Any] | None, side: str, qty: float, fill_price: float, filled_at: datetime) -> tuple[float, int, float]:
        if not prior_trade:
            return 0.0, 0, fill_price
        entry_price = float(prior_trade.get("exit_price") or prior_trade.get("price") or fill_price)
        prior_side = str(prior_trade.get("side", "buy")).lower()
        prior_qty = float(prior_trade.get("qty", qty) or qty)
        trade_qty = max(qty, min(qty or prior_qty, prior_qty))
        if side in {"sell", "short"} and prior_side in {"buy", "long"}:
            pnl = (fill_price - entry_price) * trade_qty
        elif side in {"buy", "long"} and prior_side in {"sell", "short"}:
            pnl = (entry_price - fill_price) * trade_qty
        else:
            return 0.0, 0, entry_price
        prior_time = self._parse_timestamp(prior_trade.get("filled_at") or prior_trade.get("created_at"))
        holding_secs = max(int((filled_at - prior_time).total_seconds()), 0)
        return round(pnl, 8), holding_secs, entry_price

    async def _update_strategy_metrics(self, session, strategy_id: str) -> None:
        result = await session.execute(text("SELECT tp.pnl FROM trade_performance tp JOIN orders o ON o.id = tp.order_id WHERE o.strategy_id = :strategy_id ORDER BY tp.created_at ASC"), {"strategy_id": strategy_id})
        pnls = [float(row[0]) for row in result.all()]
        if not pnls:
            return
        win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
        avg_pnl = mean(pnls)
        volatility = pstdev(pnls) if len(pnls) > 1 else 0.0
        sharpe = 0.0 if volatility == 0 else (avg_pnl / volatility) * math.sqrt(len(pnls))
        running = peak = max_drawdown = 0.0
        for p in pnls:
            running += p
            peak = max(peak, running)
            max_drawdown = min(max_drawdown, running - peak)
        existing = await session.execute(text("SELECT id FROM strategy_metrics WHERE strategy_id = :strategy_id"), {"strategy_id": strategy_id})
        row = existing.mappings().first()
        params = {"strategy_id": strategy_id, "win_rate": round(win_rate, 6), "avg_pnl": round(avg_pnl, 8), "sharpe": round(sharpe, 8), "max_drawdown": round(abs(max_drawdown), 8)}
        if row is None:
            await session.execute(text("INSERT INTO strategy_metrics (strategy_id, win_rate, avg_pnl, sharpe, max_drawdown, updated_at) VALUES (:strategy_id, :win_rate, :avg_pnl, :sharpe, :max_drawdown, NOW())"), params)
        else:
            await session.execute(text("UPDATE strategy_metrics SET win_rate = :win_rate, avg_pnl = :avg_pnl, sharpe = :sharpe, max_drawdown = :max_drawdown, updated_at = NOW() WHERE strategy_id = :strategy_id"), params)

    async def _update_vector_memory_outcome(self, session, *, trace_id: str | None, pnl: float, holding_secs: int, factor_attribution: dict[str, float]) -> None:
        if not trace_id:
            return
        result = await session.execute(text("SELECT id FROM vector_memory WHERE metadata_->>'trace_id' = :trace_id ORDER BY created_at DESC LIMIT 1"), {"trace_id": trace_id})
        row = result.mappings().first()
        if row is None:
            return
        outcome = {"pnl": pnl, "holding_secs": holding_secs, "win": pnl > 0, "factor_attribution": factor_attribution}
        await session.execute(text("UPDATE vector_memory SET outcome = CAST(:outcome AS JSONB) WHERE id = :id"), {"id": row["id"], "outcome": json.dumps(outcome, default=str)})

    def _parse_timestamp(self, value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _json_value(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                log_structured("warning", "Invalid JSON payload in trade evaluator")
        return {}
EOF

# ── api/services/learning/ic_updater.py ─────────────────────────────────────
cat > api/services/learning/ic_updater.py << 'EOF'
"""Nightly information-coefficient updater for factor weights."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from math import isnan
from typing import Any

from sqlalchemy import text

from api.db import AsyncSessionFactory
from api.observability import log_structured


class ICUpdater:
    def __init__(self, redis_client):
        self.redis = redis_client
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="ic-updater")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self, reference_dt: datetime | None = None) -> dict[str, float]:
        now = reference_dt or datetime.now(timezone.utc)
        since = now - timedelta(days=30)
        async with AsyncSessionFactory() as session:
            result = await session.execute(text("SELECT factor_attribution, pnl FROM trade_performance WHERE created_at >= :since ORDER BY created_at ASC"), {"since": since})
            rows = result.all()
            grouped: defaultdict[str, list[tuple[float, float]]] = defaultdict(list)
            for factor_attribution, pnl in rows:
                parsed = self._json_value(factor_attribution)
                realized_return = float(pnl or 0.0)
                for factor_name, score in parsed.items():
                    try:
                        grouped[str(factor_name)].append((float(score), realized_return))
                    except (TypeError, ValueError):
                        continue
            ic_scores: dict[str, float] = {k: round(self._spearman(v), 6) for k, v in grouped.items()}
            positive = {f: max(s, 0.0) for f, s in ic_scores.items() if not isnan(s)}
            total = sum(positive.values())
            weights = {f: round(v / total, 6) if total > 0 else 0.0 for f, v in sorted(positive.items())}
            for factor_name, ic_score in ic_scores.items():
                await session.execute(text("INSERT INTO factor_ic_history (factor_name, ic_score, computed_at) VALUES (:factor_name, :ic_score, :computed_at)"), {"factor_name": factor_name, "ic_score": ic_score, "computed_at": now})
            await session.commit()
        await self.redis.set("alpha:ic_weights", json.dumps(weights, default=str))
        return weights

    async def _run_loop(self) -> None:
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                next_midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)
                await asyncio.sleep(max((next_midnight - now).total_seconds(), 1))
                await self.run_once(next_midnight)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log_structured("warning", "IC updater failed", error=str(exc))

    def _spearman(self, pairs: list[tuple[float, float]]) -> float:
        if len(pairs) < 2:
            return 0.0
        xs = [s for s, _ in pairs]
        ys = [r for _, r in pairs]
        rx, ry = self._ranks(xs), self._ranks(ys)
        mean_rx, mean_ry = sum(rx) / len(rx), sum(ry) / len(ry)
        numerator = sum((x - mean_rx) * (y - mean_ry) for x, y in zip(rx, ry))
        denom_x = sum((x - mean_rx) ** 2 for x in rx) ** 0.5
        denom_y = sum((y - mean_ry) ** 2 for y in ry) ** 0.5
        if denom_x == 0 or denom_y == 0:
            return 0.0
        return numerator / (denom_x * denom_y)

    def _ranks(self, values: list[float]) -> list[float]:
        order = sorted(enumerate(values), key=lambda item: item[1])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and order[j + 1][1] == order[i][1]:
                j += 1
            avg_rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[order[k][0]] = avg_rank
            i = j + 1
        return ranks

    def _json_value(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return dict(value) if hasattr(value, "items") else {}
EOF

# ── api/services/learning/reflection.py ─────────────────────────────────────
cat > api/services/learning/reflection.py << 'EOF'
"""Batch trade reflection loop for learning summaries."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timezone
from statistics import mean
from typing import Any

import aiohttp
from sqlalchemy import text

from api.config import settings
from api.db import AsyncSessionFactory
from api.events.bus import EventBus
from api.observability import log_structured

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class ReflectionService:
    def __init__(self, bus: EventBus, redis_client, poll_interval_seconds: int = 5):
        self.bus = bus
        self.redis = redis_client
        self.poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="reflection-service")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> bool:
        trade_count = int(await self.redis.get("reflection:trade_count") or 0)
        if trade_count < settings.REFLECTION_TRADE_THRESHOLD:
            return False
        trades = await self._fetch_recent_trades(settings.REFLECTION_TRADE_THRESHOLD)
        if not trades:
            return False
        payload = await self._build_reflection_payload(trades)
        trace_id = f"reflection_{datetime.now(timezone.utc).isoformat()}"
        async with AsyncSessionFactory() as session:
            await session.execute(
                text("INSERT INTO agent_logs (trace_id, log_type, payload) VALUES (:trace_id, 'reflection', CAST(:payload AS JSONB))"),
                {"trace_id": trace_id, "payload": json.dumps({**payload, "type": "reflection", "trade_count": len(trades)}, default=str)},
            )
            await session.commit()
        await self.redis.set("reflection:trade_count", 0)
        await self.bus.publish("agent_logs", {"type": "agent_log", "log_type": "reflection", "trace_id": trace_id, **payload})
        await self.bus.publish("learning_events", {"type": "learning_event", "event": "reflection_completed", "trace_id": trace_id, "summary": payload.get("summary")})
        return True

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                log_structured("warning", "Reflection service failed", error=str(exc))
            await asyncio.sleep(self.poll_interval_seconds)

    async def _fetch_recent_trades(self, limit: int) -> list[dict[str, Any]]:
        async with AsyncSessionFactory() as session:
            result = await session.execute(text("SELECT tp.symbol, tp.pnl, tp.holding_secs, tp.factor_attribution, tp.market_context, tp.created_at FROM trade_performance tp ORDER BY tp.created_at DESC LIMIT :limit"), {"limit": limit})
            return [{"symbol": row[0], "pnl": float(row[1]), "holding_secs": int(row[2]), "factor_attribution": self._json_value(row[3]), "market_context": self._json_value(row[4]), "created_at": row[5]} for row in result.all()]

    async def _build_reflection_payload(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        fallback = self._fallback_reflection(trades)
        if not settings.ANTHROPIC_API_KEY:
            return fallback
        payload = {"model": "claude-sonnet-4-20250514", "max_tokens": 400, "temperature": 0.2, "messages": [{"role": "user", "content": json.dumps({"trades": trades, "instruction": "Return JSON only with keys winning_factors, losing_factors, regime_edge, sizing_recommendation, new_hypotheses, summary."}, default=str)}]}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=settings.LLM_TIMEOUT_SECONDS)) as session:
                async with session.post(ANTHROPIC_URL, headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json=payload) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"anthropic_status_{response.status}")
                    body = await response.json()
            text_payload = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
            parsed = json.loads(text_payload)
            return {k: parsed.get(k, fallback[k]) for k in fallback}
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Reflection LLM call failed", error=str(exc))
            return fallback

    def _fallback_reflection(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        wins: defaultdict[str, list[float]] = defaultdict(list)
        losses: defaultdict[str, list[float]] = defaultdict(list)
        for trade in trades:
            bucket = wins if float(trade.get("pnl", 0.0)) > 0 else losses
            for key, value in self._json_value(trade.get("factor_attribution")).items():
                try:
                    bucket[key].append(float(value))
                except (TypeError, ValueError):
                    continue

        def top_factors(source: defaultdict[str, list[float]]) -> list[dict[str, float]]:
            ranked = sorted(((k, mean(v)) for k, v in source.items() if v), key=lambda x: x[1], reverse=True)
            return [{"factor": k, "score": round(s, 6)} for k, s in ranked[:3]]

        avg_hold = round(mean([max(int(t.get("holding_secs", 0)), 0) for t in trades]), 2)
        return {"winning_factors": top_factors(wins), "losing_factors": top_factors(losses), "regime_edge": "paper-mode regime inference from recent trade batch", "sizing_recommendation": "increase only when top winning factors stay positive and lag stays low", "new_hypotheses": ["Favor signals whose positive factor cluster repeats across winning trades.", "Reduce size when recent losing factor cluster dominates consecutive trades."], "summary": f"Reflection batch analyzed {len(trades)} trades with average holding time {avg_hold} seconds."}

    def _json_value(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return dict(value) if hasattr(value, "items") else {}
EOF

# ── api/services/agents/reasoning_agent.py ───────────────────────────────────
cat > api/services/agents/reasoning_agent.py << 'PYEOF'
"""Structured reasoning agent for signal summaries."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

import aiohttp
from sqlalchemy import text

from api.config import settings
from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"
EMBED_DIMENSIONS = 1536


class ReasoningAgent(BaseStreamConsumer):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client):
        super().__init__(bus, dlq, stream="signals", group=DEFAULT_GROUP, consumer="reasoning-agent")
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        today = date.today().isoformat()
        trace_id = str(uuid.uuid4())
        budget_key = f"llm:tokens:{today}"
        budget_used = int(await self.redis.get(budget_key) or 0)
        signal_summary = self._summarize_signal(data)
        embedding = await self._embed_text(signal_summary)
        similar_trades = await self._search_vector_memory(embedding)
        fallback_reason = None
        if budget_used >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            fallback_reason = "budget_exceeded"
            summary = await self._apply_fallback(data, trace_id, reason=fallback_reason)
            tokens_used, cost_usd = 0, 0.0
        else:
            try:
                summary, tokens_used, cost_usd = await self._call_reasoning_model(data, similar_trades, trace_id)
            except Exception as exc:  # noqa: BLE001
                fallback_reason = str(exc)
                summary = await self._apply_fallback(data, trace_id, reason=fallback_reason)
                tokens_used, cost_usd = 0, 0.0
        await self._store_agent_run(data, summary, trace_id, fallback_reason is not None)
        await self._store_vector_memory(signal_summary, embedding, summary)
        await self._store_agent_log(trace_id, summary, fallback_reason)
        await self.redis.incrby(budget_key, tokens_used)
        await self.redis.incrbyfloat(f"llm:cost:{today}", cost_usd)
        await self._store_cost_tracking(today, tokens_used, cost_usd)
        if int(await self.redis.get(budget_key) or 0) >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            await self.bus.publish("risk_alerts", {"type": "llm_budget", "message": "Daily Anthropic token budget exceeded", "tokens_used": int(await self.redis.get(budget_key) or 0), "limit": settings.ANTHROPIC_DAILY_TOKEN_BUDGET})
        await self.bus.publish("agent_logs", {"type": "agent_log", **summary})
        if summary["action"].lower() not in {"reject", "hold", "flat"}:
            await self.bus.publish("orders", {"strategy_id": data.get("strategy_id"), "symbol": data.get("symbol"), "side": summary["action"].lower(), "qty": max(float(data.get("qty", 1.0)), float(summary.get("size_pct", 1.0))), "price": float(data.get("price", data.get("last_price", 0.0))), "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()), "trace_id": trace_id})

    def _summarize_signal(self, data: dict[str, Any]) -> str:
        return json.dumps({"symbol": data.get("symbol"), "price": data.get("price"), "composite_score": data.get("composite_score"), "signal_type": data.get("signal_type"), "context": data.get("context", {})}, sort_keys=True, default=str)

    async def _embed_text(self, text_value: str) -> list[float]:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=settings.LLM_TIMEOUT_SECONDS)) as session:
                async with session.post(OPENAI_EMBEDDING_URL, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json={"model": "text-embedding-3-small", "input": text_value}) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"Embedding API failed with status {response.status}")
                    payload = await response.json()
                    return payload["data"][0]["embedding"]
        digest = hashlib.sha256(text_value.encode("utf-8")).digest()
        values = []
        while len(values) < EMBED_DIMENSIONS:
            for byte in digest:
                values.append(round(byte / 255, 6))
                if len(values) == EMBED_DIMENSIONS:
                    break
        return values

    async def _search_vector_memory(self, embedding: list[float]) -> list[dict[str, Any]]:
        vector_literal = self._vector_literal(embedding)
        query = text("SELECT id, content, metadata_, outcome, 1 - (embedding <=> CAST(:embedding AS vector)) AS sim FROM vector_memory ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT 5")
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(query, {"embedding": vector_literal})
                return [{"id": str(row["id"]), "content": row["content"], "metadata": row["metadata_"], "outcome": row["outcome"], "sim": float(row["sim"])} for row in result.mappings().all()]
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Vector memory search unavailable", error=str(exc))
            return []

    async def _call_reasoning_model(self, data: dict[str, Any], similar_trades: list[dict[str, Any]], trace_id: str) -> tuple[dict[str, Any], int, float]:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("anthropic_api_key_missing")
        payload = {"model": "claude-sonnet-4-20250514", "max_tokens": 300, "temperature": 0.2, "system": "Return ONLY valid JSON with keys: action, confidence, primary_edge, risk_factors, size_pct, stop_atr_x, rr_ratio, latency_ms, cost_usd, trace_id, fallback.", "messages": [{"role": "user", "content": json.dumps({"signal": data, "similar_trades": similar_trades}, default=str)}]}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=settings.LLM_TIMEOUT_SECONDS)) as session:
            async with session.post(ANTHROPIC_URL, headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json=payload) as response:
                if response.status >= 400:
                    raise RuntimeError(f"anthropic_status_{response.status}")
                body = await response.json()
        text_payload = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
        parsed = json.loads(text_payload)
        parsed["trace_id"] = trace_id
        parsed["fallback"] = False
        tokens_used = int(body.get("usage", {}).get("input_tokens", 0)) + int(body.get("usage", {}).get("output_tokens", 0))
        cost_usd = round(tokens_used * 0.000003, 6)
        parsed.setdefault("latency_ms", 0)
        parsed.setdefault("cost_usd", cost_usd)
        parsed.setdefault("risk_factors", [])
        return parsed, tokens_used, cost_usd

    async def _apply_fallback(self, data: dict[str, Any], trace_id: str, reason: str) -> dict[str, Any]:
        base_action = str(data.get("action") or data.get("signal") or "hold").lower()
        composite_score = float(data.get("composite_score", 0.0) or 0.0)
        if settings.LLM_FALLBACK_MODE == "reject_signal":
            action = "reject"
        elif settings.LLM_FALLBACK_MODE == "use_last_reflection":
            reflection = await self._get_last_reflection()
            action = base_action if base_action not in {"none", ""} else "hold"
        else:
            action = base_action if base_action not in {"none", ""} else "hold"
        return {"action": action, "confidence": round(max(composite_score, 0.1), 4), "primary_edge": f"fallback:{settings.LLM_FALLBACK_MODE}", "risk_factors": [reason], "size_pct": round(max(float(data.get("size_pct", 0.01) or 0.01), 0.01), 4), "stop_atr_x": float(data.get("stop_atr_x", 1.5) or 1.5), "rr_ratio": float(data.get("rr_ratio", 2.0) or 2.0), "latency_ms": 0, "cost_usd": 0.0, "trace_id": trace_id, "fallback": True}

    async def _get_last_reflection(self) -> dict[str, Any]:
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(text("SELECT payload FROM agent_logs WHERE log_type = 'reflection' ORDER BY created_at DESC LIMIT 1"))
                row = result.first()
                if row is None:
                    return {}
                payload = row[0]
                if isinstance(payload, str):
                    return json.loads(payload)
                return payload or {}
        except Exception:
            return {}

    async def _store_agent_run(self, data: dict[str, Any], summary: dict[str, Any], trace_id: str, fallback: bool) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(text("INSERT INTO agent_runs (strategy_id, symbol, signal_data, action, confidence, primary_edge, risk_factors, size_pct, stop_atr_x, rr_ratio, latency_ms, cost_usd, trace_id, fallback) VALUES (:strategy_id, :symbol, CAST(:signal_data AS JSONB), :action, :confidence, :primary_edge, CAST(:risk_factors AS JSONB), :size_pct, :stop_atr_x, :rr_ratio, :latency_ms, :cost_usd, :trace_id, :fallback)"), {"strategy_id": data.get("strategy_id"), "symbol": data.get("symbol"), "signal_data": json.dumps(data, default=str), "action": summary["action"], "confidence": summary["confidence"], "primary_edge": summary["primary_edge"], "risk_factors": json.dumps(summary["risk_factors"], default=str), "size_pct": summary["size_pct"], "stop_atr_x": summary["stop_atr_x"], "rr_ratio": summary["rr_ratio"], "latency_ms": summary["latency_ms"], "cost_usd": summary["cost_usd"], "trace_id": trace_id, "fallback": fallback})
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Unable to store agent run", error=str(exc))

    async def _store_vector_memory(self, content: str, embedding: list[float], summary: dict[str, Any]) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(text("INSERT INTO vector_memory (content, embedding, metadata_, outcome) VALUES (:content, CAST(:embedding AS vector), CAST(:metadata AS JSONB), CAST(:outcome AS JSONB))"), {"content": content, "embedding": self._vector_literal(embedding), "metadata": json.dumps({"trace_id": summary["trace_id"]}), "outcome": json.dumps({"action": summary["action"], "confidence": summary["confidence"]})})
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Unable to store vector memory", error=str(exc))

    async def _store_agent_log(self, trace_id: str, summary: dict[str, Any], fallback_reason: str | None) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(text("INSERT INTO agent_logs (trace_id, log_type, payload) VALUES (:trace_id, :log_type, CAST(:payload AS JSONB))"), {"trace_id": trace_id, "log_type": "reasoning_summary", "payload": json.dumps({**summary, "fallback_reason": fallback_reason}, default=str)})
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Unable to store agent log", error=str(exc))

    async def _store_cost_tracking(self, today: str, tokens_used: int, cost_usd: float) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(text("INSERT INTO llm_cost_tracking (date, tokens_used, cost_usd) VALUES (:date, :tokens_used, :cost_usd)"), {"date": today, "tokens_used": tokens_used, "cost_usd": cost_usd})
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log_structured("warning", "Unable to store LLM cost tracking", error=str(exc))

    def _vector_literal(self, embedding: list[float]) -> str:
        return "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
PYEOF

# ── api/routes/ws.py ─────────────────────────────────────────────────────────
cat > api/routes/ws.py << 'EOF'
"""Dashboard WebSocket fanout."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])

STREAM_TYPE_MAP = {
    "market_ticks": "market_tick",
    "signals": "signal",
    "orders": "order_update",
    "executions": "order_update",
    "risk_alerts": "risk_alert",
    "learning_events": "learning_event",
    "system_metrics": "system_metric",
    "agent_logs": "agent_log",
}


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    redis_client = getattr(websocket.app.state, "redis_client", None)
    if redis_client is None:
        await websocket.close(code=1013)
        return
    last_ids = {stream: "$" for stream in STREAM_TYPE_MAP}
    try:
        while True:
            messages = await redis_client.xread(last_ids, block=1000, count=50)
            for stream_name, entries in messages:
                stream_key = stream_name.decode("utf-8") if isinstance(stream_name, bytes) else stream_name
                for entry_id, fields in entries:
                    payload_raw = fields.get("payload") or fields.get(b"payload") or "{}"
                    if isinstance(payload_raw, bytes):
                        payload_raw = payload_raw.decode("utf-8")
                    payload: dict[str, Any] = json.loads(payload_raw)
                    payload.setdefault("type", STREAM_TYPE_MAP.get(stream_key, stream_key))
                    await websocket.send_json(payload)
                    last_ids[stream_key] = entry_id.decode("utf-8") if isinstance(entry_id, bytes) else entry_id
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        return
EOF

# ── frontend files ────────────────────────────────────────────────────────────
mkdir -p frontend/src/app/dashboard/agents
mkdir -p frontend/src/app/dashboard/learning
mkdir -p frontend/src/app/dashboard/system
mkdir -p frontend/src/app/dashboard/trading
mkdir -p frontend/src/hooks
mkdir -p frontend/src/stores
mkdir -p frontend/src/shims
mkdir -p frontend/src/legacy-pages

# Move old pages/ to legacy-pages/ if they exist
for f in _app.tsx dashboard.tsx film-room.tsx index.tsx logs.tsx performance.tsx; do
  if [ -f "frontend/src/pages/$f" ]; then
    mv "frontend/src/pages/$f" "frontend/src/legacy-pages/" 2>/dev/null || true
  fi
done
# Rename specific files
[ -f "frontend/src/legacy-pages/dashboard.tsx" ] && mv frontend/src/legacy-pages/dashboard.tsx frontend/src/legacy-pages/dashboard-legacy.tsx 2>/dev/null || true
[ -f "frontend/src/legacy-pages/index.tsx" ] && mv frontend/src/legacy-pages/index.tsx frontend/src/legacy-pages/index-legacy.tsx 2>/dev/null || true

cat > frontend/src/app/layout.tsx << 'EOF'
import '../styles/globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Trading Control Dashboard',
  description: 'Phase 2 dashboard for AI trading control',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0F172A] text-slate-100">{children}</body>
    </html>
  )
}
EOF

cat > frontend/src/app/page.tsx << 'EOF'
import { redirect } from 'next/navigation'
export default function HomePage() { redirect('/dashboard') }
EOF

cat > frontend/src/app/dashboard/page.tsx << 'EOF'
import { DashboardView } from './DashboardView'
export default function DashboardPage() { return <DashboardView section="overview" /> }
EOF

cat > frontend/src/app/dashboard/agents/page.tsx << 'EOF'
import { DashboardView } from '../DashboardView'
export default function AgentsPage() { return <DashboardView section="agents" /> }
EOF

cat > frontend/src/app/dashboard/learning/page.tsx << 'EOF'
import { DashboardView } from '../DashboardView'
export default function LearningPage() { return <DashboardView section="learning" /> }
EOF

cat > frontend/src/app/dashboard/system/page.tsx << 'EOF'
import { DashboardView } from '../DashboardView'
export default function SystemPage() { return <DashboardView section="system" /> }
EOF

cat > frontend/src/app/dashboard/trading/page.tsx << 'EOF'
import { DashboardView } from '../DashboardView'
export default function TradingPage() { return <DashboardView section="trading" /> }
EOF

cat > frontend/src/stores/useCodexStore.ts << 'EOF'
'use client'
import { create } from 'zustand'

type PriceRecord = Record<string, { price: number; change: number }>

type CodexState = {
  prices: PriceRecord
  orders: any[]
  positions: any[]
  signals: any[]
  agentLogs: any[]
  riskAlerts: any[]
  learningEvents: any[]
  systemMetrics: any[]
  regime: string
  killSwitchActive: boolean
  wsConnected: boolean
  updatePrice: (symbol: string, price: number, change: number) => void
  addSignal: (signal: any) => void
  addOrder: (order: any) => void
  updateOrder: (order: any) => void
  addAgentLog: (log: any) => void
  addRiskAlert: (alert: any) => void
  addLearningEvent: (event: any) => void
  addSystemMetric: (metric: any) => void
  setRegime: (regime: string) => void
  setKillSwitch: (active: boolean) => void
  setWsConnected: (connected: boolean) => void
}

export const useCodexStore = create<CodexState>((set) => ({
  prices: {}, orders: [], positions: [], signals: [],
  agentLogs: [], riskAlerts: [], learningEvents: [], systemMetrics: [],
  regime: 'neutral', killSwitchActive: false, wsConnected: false,
  updatePrice: (symbol, price, change) => set((state) => ({ prices: { ...state.prices, [symbol]: { price, change } } })),
  addSignal: (signal) => set((state) => ({ signals: [signal, ...state.signals].slice(0, 50) })),
  addOrder: (order) => set((state) => ({ orders: [order, ...state.orders].slice(0, 100) })),
  updateOrder: (order) => set((state) => ({ orders: state.orders.some((e) => e.order_id === order.order_id) ? state.orders.map((e) => e.order_id === order.order_id ? { ...e, ...order } : e) : [order, ...state.orders].slice(0, 100) })),
  addAgentLog: (log) => set((state) => ({ agentLogs: [log, ...state.agentLogs].slice(0, 100) })),
  addRiskAlert: (alert) => set((state) => ({ riskAlerts: [alert, ...state.riskAlerts].slice(0, 50) })),
  addLearningEvent: (event) => set((state) => ({ learningEvents: [event, ...state.learningEvents].slice(0, 50) })),
  addSystemMetric: (metric) => set((state) => ({ systemMetrics: [metric, ...state.systemMetrics].slice(0, 100) })),
  setRegime: (regime) => set({ regime }),
  setKillSwitch: (killSwitchActive) => set({ killSwitchActive }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
}))
EOF

cat > frontend/src/hooks/useWebSocket.ts << 'EOF'
'use client'
import { useEffect } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

const getWsUrl = () => {
  const base = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'
  return `${base.replace(/\/$/, '')}/ws/dashboard`
}

export function useWebSocket() {
  const { addAgentLog, addLearningEvent, addOrder, addRiskAlert, addSignal, addSystemMetric, setKillSwitch, setRegime, setWsConnected, updateOrder, updatePrice } = useCodexStore()

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry = 0
    let closed = false
    const connect = () => {
      socket = new WebSocket(getWsUrl())
      socket.onopen = () => { retry = 0; setWsConnected(true) }
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data)
        switch (payload.type) {
          case 'market_tick': updatePrice(payload.symbol, Number(payload.price || 0), Number(payload.change || 0)); break
          case 'signal': addSignal(payload); break
          case 'order_update': addOrder(payload); updateOrder(payload); break
          case 'agent_log': addAgentLog(payload); break
          case 'risk_alert': addRiskAlert(payload); break
          case 'regime_change': setRegime(payload.regime || 'neutral'); break
          case 'learning_event': addLearningEvent(payload); break
          case 'system_metric': addSystemMetric(payload); break
          case 'kill_switch': setKillSwitch(Boolean(payload.active)); break
        }
      }
      socket.onclose = () => {
        setWsConnected(false)
        if (closed) return
        const timeout = Math.min(1000 * (2 ** retry), 30000)
        retry += 1
        window.setTimeout(connect, timeout)
      }
    }
    connect()
    return () => { closed = true; socket?.close() }
  }, [addAgentLog, addLearningEvent, addOrder, addRiskAlert, addSignal, addSystemMetric, setKillSwitch, setRegime, setWsConnected, updateOrder, updatePrice])
}
EOF

cat > frontend/src/shims/zustand.ts << 'EOF'
'use client'
import { useSyncExternalStore } from 'react'

type Setter<T> = (partial: Partial<T> | ((state: T) => Partial<T>)) => void

export function create<T extends Record<string, any>>(initializer: (set: Setter<T>, get: () => T) => T) {
  let state: T
  const listeners = new Set<() => void>()
  const get = () => state
  const set: Setter<T> = (partial) => {
    const patch = typeof partial === 'function' ? partial(state) : partial
    state = { ...state, ...patch }
    listeners.forEach((l) => l())
  }
  state = initializer(set, get)
  const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener) }
  function useStore<U = T>(selector?: (state: T) => U): U {
    return useSyncExternalStore(subscribe, () => (selector ? selector(state) : (state as unknown as U)), () => (selector ? selector(state) : (state as unknown as U)))
  }
  ;(useStore as any).getState = get
  ;(useStore as any).setState = set
  return useStore as typeof useStore & { getState: () => T; setState: Setter<T> }
}
EOF

cat > frontend/src/lib/fonts.ts << 'EOF'
export const inter = { variable: '--font-inter' }
EOF

# ── frontend/src/app/dashboard/DashboardView.tsx ─────────────────────────────
cat > frontend/src/app/dashboard/DashboardView.tsx << 'TSXEOF'
'use client'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useCodexStore } from '@/stores/useCodexStore'

const NAV_ITEMS = [
  { href: '/dashboard', label: 'Overview' },
  { href: '/dashboard/trading', label: 'Trading' },
  { href: '/dashboard/agents', label: 'Agents' },
  { href: '/dashboard/learning', label: 'Learning' },
  { href: '/dashboard/system', label: 'System' },
]

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  useWebSocket()
  const { agentLogs, killSwitchActive, learningEvents, orders, prices, regime, riskAlerts, signals, systemMetrics, wsConnected, setKillSwitch } = useCodexStore()
  const [dlqItems, setDlqItems] = useState<any[]>([])

  useEffect(() => {
    if (section !== 'system') return
    fetch(`${API_BASE}/v1/events/dlq`).then((r) => r.json()).then((p) => setDlqItems(p.items || [])).catch(() => setDlqItems([]))
  }, [section])

  const dailyPnl = useMemo(() => orders.reduce((t, o) => t + Number(o.pnl || 0), 0), [orders])

  const toggleKillSwitch = async () => {
    const next = !killSwitchActive
    if (!window.confirm(`${next ? 'Enable' : 'Disable'} kill switch?`)) return
    const r = await fetch(`${API_BASE}/v1/dashboard/kill_switch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ active: next }) })
    if (r.ok) setKillSwitch(next)
  }

  const replayDlq = async (eventId: string) => {
    const r = await fetch(`${API_BASE}/v1/events/dlq/${eventId}/replay`, { method: 'POST' })
    if (r.ok) setDlqItems((items) => items.filter((i) => i.event_id !== eventId))
  }

  return (
    <div className="min-h-screen bg-[#0F172A] px-6 py-6 text-slate-100">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-5 md:flex-row md:items-center md:justify-between">
          <div><p className="text-sm text-slate-400">AI Trading Bot Control</p><h1 className="text-2xl font-semibold">Mission Dashboard</h1></div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-slate-700 px-3 py-1 text-sm">Regime: {regime}</span>
            <span className={`rounded-full px-3 py-1 text-sm ${wsConnected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>WS {wsConnected ? 'Connected' : 'Disconnected'}</span>
            <span className="rounded-full border border-slate-700 px-3 py-1 text-sm">Daily P&L: ${dailyPnl.toFixed(2)}</span>
            <button onClick={toggleKillSwitch} className={`rounded-full px-4 py-2 text-sm font-medium transition ${killSwitchActive ? 'animate-pulse bg-red-600 text-white' : 'bg-slate-800 text-slate-100 hover:bg-slate-700'}`}>{killSwitchActive ? 'Kill Switch Active' : 'Enable Kill Switch'}</button>
          </div>
        </header>
        <nav className="flex flex-wrap gap-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-3">
          {NAV_ITEMS.map((item) => (<Link key={item.href} href={item.href} className="rounded-xl px-4 py-2 text-sm text-slate-300 transition hover:bg-slate-800 hover:text-white">{item.label}</Link>))}
        </nav>
        {section === 'overview' && (
          <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <h2 className="mb-4 text-lg font-semibold">Price Grid</h2>
              <div className="grid gap-3 md:grid-cols-3">
                {Object.entries(prices).length === 0 && <p className="text-sm text-slate-400">Waiting for market ticks...</p>}
                {Object.entries(prices).map(([symbol, record]) => (<div key={symbol} className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><div className="text-sm text-slate-400">{symbol}</div><div className="mt-2 text-xl font-semibold">${record.price.toFixed(2)}</div><div className={`text-sm ${record.change >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{record.change.toFixed(2)}%</div></div>))}
              </div>
            </section>
            <section className="space-y-6">
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-3 text-lg font-semibold">Risk Alerts</h2><div className="space-y-3">{riskAlerts.length === 0 ? <p className="text-sm text-slate-400">No active alerts.</p> : riskAlerts.slice(0, 5).map((a, i) => <div key={i} className="rounded-xl bg-amber-500/10 p-3 text-sm text-amber-200">{a.message || a.type || 'risk_alert'}</div>)}</div></div>
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-3 text-lg font-semibold">Last Reasoning Summary</h2>{agentLogs[0] ? <pre className="overflow-auto text-xs text-slate-300">{JSON.stringify(agentLogs[0], null, 2)}</pre> : <p className="text-sm text-slate-400">No agent logs yet.</p>}</div>
            </section>
          </div>
        )}
        {section === 'trading' && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Candlestick Chart</h2><div className="h-72 rounded-xl border border-dashed border-slate-700 bg-slate-950/40 p-4 text-sm text-slate-400">Chart placeholder for lightweight-charts integration.</div></section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Open Positions</h2><div className="space-y-3 text-sm text-slate-300">{orders.slice(0, 10).map((o, i) => (<div key={i} className="flex items-center justify-between rounded-xl bg-slate-950/40 p-3"><span>{o.symbol || 'Unknown'}</span><span>{o.side || o.type || 'n/a'}</span><span>{o.qty || 0}</span></div>))}{orders.length === 0 && <p className="text-slate-400">No positions or orders yet.</p>}</div></section>
          </div>
        )}
        {section === 'agents' && (
          <div className="grid gap-6 lg:grid-cols-[280px,1fr]">
            <aside className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Agent Status</h2><div className="space-y-3 text-sm text-slate-300">{['ReasoningAgent', 'ExecutionEngine', 'LearningAgent'].map((n) => (<div key={n} className="rounded-xl bg-slate-950/40 p-3">{n}: online</div>))}</div></aside>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Reasoning Log</h2><div className="space-y-3">{agentLogs.length === 0 && <p className="text-sm text-slate-400">Waiting for agent logs...</p>}{agentLogs.slice(0, 12).map((log, i) => (<div key={i} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm"><div className="font-medium">{log.action || 'unknown action'}</div><div className="mt-2 text-slate-400">confidence: {log.confidence ?? 'n/a'} · cost: ${log.cost_usd ?? 0}</div><div className="mt-2 text-slate-300">{log.primary_edge || 'No primary edge supplied.'}</div></div>))}</div></section>
          </div>
        )}
        {section === 'learning' && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Trade Timeline</h2><div className="space-y-3 text-sm text-slate-300">{signals.slice(0, 10).map((s, i) => <div key={i} className="rounded-xl bg-slate-950/40 p-3">{s.symbol || 'signal'} · {s.signal_type || s.type || 'unknown'}</div>)}{signals.length === 0 && <p className="text-slate-400">No learning timeline data yet.</p>}</div></section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Reflection Log</h2><div className="space-y-3 text-sm text-slate-300">{learningEvents.slice(0, 10).map((e, i) => <div key={i} className="rounded-xl bg-slate-950/40 p-3">{e.summary || e.type || 'learning_event'}</div>)}{learningEvents.length === 0 && <p className="text-slate-400">No reflections yet.</p>}</div></section>
          </div>
        )}
        {section === 'system' && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Stream Metrics</h2><div className="space-y-3 text-sm text-slate-300">{systemMetrics.length === 0 && <p className="text-slate-400">No stream metrics yet.</p>}{systemMetrics.slice(0, 10).map((m, i) => (<div key={i} className="flex items-center justify-between rounded-xl bg-slate-950/40 p-3"><span>{m.metric_name || m.type || 'metric'}</span><span>{m.value ?? m.lag ?? 'n/a'}</span></div>))}</div></section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">DLQ Inspector</h2><div className="space-y-3 text-sm text-slate-300">{dlqItems.length === 0 && <p className="text-slate-400">DLQ empty.</p>}{dlqItems.map((item) => (<div key={item.event_id} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><div className="font-medium">{item.stream}</div><div className="mt-1 text-slate-400">{item.error}</div><button onClick={() => replayDlq(item.event_id)} className="mt-3 rounded-lg bg-sky-600 px-3 py-2 text-xs font-medium text-white">Replay</button></div>))}</div></section>
          </div>
        )}
      </div>
    </div>
  )
}
TSXEOF

# ── next.config.js update ────────────────────────────────────────────────────
if grep -q "NEXT_PUBLIC_WS_URL" frontend/next.config.js; then
  echo "next.config.js already has WS_URL"
else
  sed -i 's/NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,/NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,\n    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL,/' frontend/next.config.js
fi

# ── zustand in package.json ──────────────────────────────────────────────────
if grep -q '"zustand"' frontend/package.json; then
  echo "zustand already in package.json"
else
  sed -i 's/"typescript": "\^5.9.3"/"typescript": "^5.9.3",\n    "zustand": "^5.0.8"/' frontend/package.json
fi

# ── tsconfig.json zustand path alias ────────────────────────────────────────
if grep -q '"zustand"' frontend/tsconfig.json; then
  echo "zustand alias already in tsconfig"
else
  sed -i 's|"@/\*": \[|"@/*": [\n        "./src/*"\n      ],\n      "zustand": [\n        "./src/shims/zustand"\n      ],\n      "REMOVE_THIS": [|' frontend/tsconfig.json
  sed -i 's|"REMOVE_THIS": \[||' frontend/tsconfig.json
fi

# ── test file fix ────────────────────────────────────────────────────────────
sed -i 's|Path("api/services/learning.py")|Path("api/services/learning/__init__.py")|' tests/test_api_modularization.py 2>/dev/null || true

echo ""
echo "=== Step 5: Committing ==="
git add -A
git status --short
git commit -m "Apply full service layer — events, execution, learning, agents, frontend dashboard"

echo ""
echo "=== Step 6: Pushing ==="
git push origin codex/implement-codex-plan-for-ai-trading-bot

echo ""
echo "=== DONE ==="
echo "Branch pushed. Now open Windsurf and paste the big prompt to finish the remaining work."
