"""Async database session management for FastAPI runtime."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

try:
    from alembic import command
    from alembic.config import Config as AlembicConfig
except ImportError:  # pragma: no cover
    command = None
    AlembicConfig = None

try:
    from api.config import get_database_url, settings
except ImportError:  # pragma: no cover
    settings = None

    def get_database_url() -> str:
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./trading-control.db")
        if db_url.startswith("postgres://") or db_url.startswith("postgresql://"):
            return db_url.replace("://", "+asyncpg://", 1)
        return db_url


SQLITE_FALLBACK_URL = "sqlite+aiosqlite:///./trading-control.db"
ALEMBIC_STARTUP_LOCK_ID = 78451233
INITIAL_REVISION = "0001_initial"
INITIAL_BASELINE_TABLES = (
    "strategies",
    "orders",
    "positions",
    "agent_runs",
    "agent_logs",
    "vector_memory",
    "trade_performance",
    "strategy_metrics",
    "factor_ic_history",
    "system_metrics",
    "audit_log",
    "order_reconciliation",
    "llm_cost_tracking",
)
INITIAL_BASELINE_REQUIRED_COLUMNS = {
    "strategies": ("id", "name", "rules", "risk_limits", "created_at"),
    "orders": ("id", "strategy_id", "symbol", "qty", "status", "idempotency_key"),
    "positions": ("id", "strategy_id", "symbol", "qty", "entry_price"),
    "agent_runs": ("id", "strategy_id", "trace_id", "created_at"),
    "agent_logs": ("id", "trace_id", "payload", "created_at"),
    "vector_memory": ("id", "content", "embedding", "metadata_", "created_at"),
    "trade_performance": ("id", "order_id", "symbol", "pnl", "created_at"),
    "strategy_metrics": ("id", "strategy_id", "win_rate", "updated_at"),
    "factor_ic_history": ("id", "factor_name", "ic_score", "computed_at"),
    "system_metrics": ("id", "metric_name", "value", "timestamp"),
    "audit_log": ("id", "event_type", "payload", "created_at"),
    "order_reconciliation": ("id", "order_id", "discrepancy", "created_at"),
    "llm_cost_tracking": ("id", "date", "tokens_used", "cost_usd", "created_at"),
}


def _resolve_database_url() -> str:
    try:
        return get_database_url()
    except Exception:
        db_url = os.getenv("DATABASE_URL")
        if os.getenv("NODE_ENV", "development") == "production" and not db_url:
            raise RuntimeError("DATABASE_URL is required in production") from None
        return db_url or SQLITE_FALLBACK_URL


def _uses_postgres(url: str) -> bool:
    return url.startswith("postgresql") or url.startswith("postgres")


def _build_alembic_config(url: str):
    if AlembicConfig is None:
        raise RuntimeError("Alembic is required for PostgreSQL schema bootstrap")
    api_dir = Path(__file__).resolve().parent
    config = AlembicConfig(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _run_alembic_upgrade(url: str) -> None:
    if command is None:
        raise RuntimeError("Alembic is required for PostgreSQL schema bootstrap")
    command.upgrade(_build_alembic_config(url), "head")


def _run_alembic_stamp(url: str, revision: str) -> None:
    if command is None:
        raise RuntimeError("Alembic is required for PostgreSQL schema bootstrap")
    command.stamp(_build_alembic_config(url), revision)


database_url = _resolve_database_url()


def _engine_kwargs() -> dict:
    """Build SQLAlchemy engine kwargs, skipping pool args for SQLite."""
    kwargs: dict = {"echo": False, "pool_pre_ping": True}
    if _uses_postgres(database_url):
        try:
            from api.config import settings as _s

            kwargs["pool_size"] = _s.DB_POOL_SIZE
            kwargs["max_overflow"] = _s.DB_MAX_OVERFLOW
            kwargs["pool_timeout"] = _s.DB_POOL_TIMEOUT
            kwargs["pool_recycle"] = _s.DB_POOL_RECYCLE
            # Add retry and reliability settings
            kwargs["pool_pre_ping"] = True
            kwargs["connect_args"] = {
                "server_settings": {"application_name": "trading-control", "jit": "off"},
            }
        except Exception:
            # Fallback to safe defaults if settings unavailable
            kwargs.update(
                {"pool_size": 5, "max_overflow": 5, "pool_timeout": 30, "pool_recycle": 1800}
            )
            kwargs["connect_args"] = {
                "server_settings": {"application_name": "trading-control", "jit": "off"},
            }
    return kwargs


async_engine = create_async_engine(database_url, **_engine_kwargs())
engine = async_engine
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
AsyncSessionFactory = AsyncSessionLocal
Base = declarative_base()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_async_session() as session:
        yield session


async def init_database() -> None:
    """Runtime helper retained for compatibility tests; app startup does not call this."""
    if _uses_postgres(database_url):
        await _run_alembic_upgrade_with_lock(database_url)
        return

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _run_alembic_upgrade_with_lock(url: str) -> None:
    """Serialize startup migrations across instances to avoid duplicate DDL races."""
    async with async_engine.connect() as conn:
        lock_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await lock_conn.execute(
            text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": ALEMBIC_STARTUP_LOCK_ID}
        )
        try:
            await _bootstrap_existing_schema_revision(lock_conn, url)
            await asyncio.to_thread(_run_alembic_upgrade, url)
        finally:
            await lock_conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": ALEMBIC_STARTUP_LOCK_ID}
            )


async def _bootstrap_existing_schema_revision(conn, url: str) -> None:
    """Stamp base revision when schema exists but alembic_version table is missing."""
    version_table_exists = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
    if version_table_exists:
        return

    baseline_table_count = await conn.scalar(
        text(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY(:table_names)
            """
        ),
        {"table_names": list(INITIAL_BASELINE_TABLES)},
    )
    if not baseline_table_count or int(baseline_table_count) != len(INITIAL_BASELINE_TABLES):
        return

    for table_name, required_columns in INITIAL_BASELINE_REQUIRED_COLUMNS.items():
        present_required_columns = await conn.scalar(
            text(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = ANY(:column_names)
                """
            ),
            {"table_name": table_name, "column_names": list(required_columns)},
        )
        if int(present_required_columns or 0) != len(required_columns):
            return

    await asyncio.to_thread(_run_alembic_stamp, url, INITIAL_REVISION)


async def test_database_connection() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_settings_info() -> dict:
    return {
        "config_source": "pydantic_settings" if settings else "environment_variables",
        "database_url": database_url,
        "validation": bool(settings),
    }
