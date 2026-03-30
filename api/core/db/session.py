"""Database readiness checks used during production startup.

This module intentionally validates schema state at startup instead of creating
or mutating schema objects at runtime.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from api.observability import log_structured

logger = logging.getLogger(__name__)

REQUIRED_TABLES: tuple[str, ...] = (
    "strategies",
    "orders",
    "positions",
    "agent_pool",
    "agent_runs",
    "agent_logs",
    "events",
    "vector_memory",
    "trade_performance",
)

CRITICAL_INDEXES: tuple[tuple[str, str], ...] = (
    ("orders", "idx_orders_strategy_status"),
    ("positions", "idx_positions_strategy_symbol"),
    ("trade_performance", "idx_trade_unique"),
    ("agent_logs", "idx_agent_logs_trace"),
    ("events", "idx_events_entity_created"),
)


class DatabaseReadinessError(RuntimeError):
    """Raised when database schema validation fails."""


def _collect_missing_tables(engine: Engine, required_tables: Iterable[str]) -> list[str]:
    inspector = inspect(engine)
    return [table for table in required_tables if not inspector.has_table(table)]


def _collect_missing_indexes(
    engine: Engine,
    required_indexes: Iterable[tuple[str, str]],
) -> list[str]:
    inspector = inspect(engine)
    missing: list[str] = []
    for table_name, index_name in required_indexes:
        if not inspector.has_index(table_name, index_name):
            missing.append(f"{table_name}.{index_name}")
    return missing


def ensure_database_ready(engine: Engine) -> bool:
    """Validate that required tables and indexes exist.

    Args:
        engine: A synchronous SQLAlchemy engine bound to the target database.

    Returns:
        True when all required schema objects are present.

    Raises:
        DatabaseReadinessError: If schema objects are missing or inspection fails.
    """
    try:
        missing_tables = _collect_missing_tables(engine, REQUIRED_TABLES)
        if missing_tables:
            message = (
                "Database not properly migrated. Missing tables: "
                f"{missing_tables}. Run 'alembic upgrade head'."
            )
            raise DatabaseReadinessError(message)

        missing_indexes = _collect_missing_indexes(engine, CRITICAL_INDEXES)
        if missing_indexes:
            message = f"Critical indexes missing: {missing_indexes}. Run 'alembic upgrade head'."
            raise DatabaseReadinessError(message)

        log_structured("info", "database schema verification passed")
        return True
    except SQLAlchemyError as exc:
        message = f"Database connection or inspection failed: {exc}"
        raise DatabaseReadinessError(message) from exc
    except DatabaseReadinessError:
        log_structured("error", "database readiness error", exc_info=True)
        raise


def analyze_vector_table(engine: Engine) -> None:
    """Run ANALYZE against ``vector_memory`` to maintain planner performance."""
    try:
        with engine.begin() as connection:
            connection.execute(text("ANALYZE vector_memory"))
        log_structured("info", "vector table analyzed for index performance")
    except SQLAlchemyError:
        log_structured("warning", "vector table analyze failed", exc_info=True)


def safe_startup(engine: Engine) -> None:
    """Run all production startup database checks."""
    ensure_database_ready(engine)
    analyze_vector_table(engine)
    log_structured("info", "production startup verification complete")
