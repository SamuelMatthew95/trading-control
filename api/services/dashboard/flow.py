from typing import Any

from sqlalchemy import text

from api.constants import FieldName
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.schema_version import DASHBOARD_API_VERSION, DB_SCHEMA_VERSION
from api.services.metrics_aggregator import MetricsAggregator
from api.utils import now_iso


def _flow_status_memory_payload() -> dict[str, Any]:
    store = get_runtime_store()
    mem_runs = len(store.agent_runs)
    return {
        FieldName.API_VERSION: DASHBOARD_API_VERSION,
        FieldName.DB_SCHEMA_VERSION: DB_SCHEMA_VERSION,
        FieldName.DEGRADED_MODE: True,
        FieldName.DEGRADED_REASON: "db_unavailable",
        FieldName.COUNTS: {
            FieldName.AGENT_RUNS: mem_runs,
            FieldName.AGENT_LOGS: len(store.agent_logs),
            FieldName.AGENT_GRADES: len(store.grade_history),
            # Report the real in-memory counts — this is the operator's
            # "is data flowing?" panel and must not claim zero orders while
            # trades are visibly happening in memory mode.
            FieldName.ORDERS: len(store.orders),
            FieldName.TRADE_LIFECYCLE: len(store.trade_feed),
        },
        FieldName.REALTIME_EVENT_COUNT: mem_runs,
        FieldName.PERSISTED_EVENT_COUNT: 0,
        FieldName.TRACE_COVERAGE: {"trace_id": None},
        "timestamp": now_iso(),
        "source": "in_memory",
    }


async def get_order_metrics_payload() -> dict[str, Any]:
    """Get order flow metrics."""
    if not is_db_available():
        return await MetricsAggregator(None, use_memory_store=True).get_order_metrics()

    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_order_metrics()

    except Exception:
        log_structured("warning", "order_metrics_db_unavailable", exc_info=True)
        return {
            FieldName.ORDERS: [],
            FieldName.TOTAL_ORDERS: 0,
            "timestamp": now_iso(),
            "source": "in_memory",
        }


async def get_flow_status_payload() -> dict[str, Any]:
    """Operational view to verify data is flowing end-to-end for UI/debugging."""
    try:
        if not is_db_available():
            return _flow_status_memory_payload()
        async with AsyncSessionFactory() as session:
            counts_sql = text("""
                SELECT
                    (SELECT COUNT(*) FROM agent_runs) AS agent_runs,
                    (SELECT COUNT(*) FROM agent_logs) AS agent_logs,
                    (SELECT COUNT(*) FROM agent_grades) AS agent_grades,
                    (SELECT COUNT(*) FROM orders) AS orders,
                    (SELECT COUNT(*) FROM trade_lifecycle) AS trade_lifecycle
            """)
            counts_row = (await session.execute(counts_sql)).mappings().first() or {}

            recent_trace_sql = text("""
                SELECT ar.trace_id
                FROM agent_runs ar
                WHERE ar.trace_id IS NOT NULL
                ORDER BY ar.created_at DESC
                LIMIT 1
            """)
            recent_trace = (await session.execute(recent_trace_sql)).scalar()

            trace_coverage = {
                "trace_id": recent_trace,
                FieldName.IN_AGENT_RUNS: 0,
                FieldName.IN_AGENT_LOGS: 0,
                FieldName.IN_TRADE_LIFECYCLE: 0,
            }
            if recent_trace:
                trace_coverage[FieldName.IN_AGENT_RUNS] = int(
                    (
                        await session.execute(
                            text("SELECT COUNT(*) FROM agent_runs WHERE trace_id = :t"),
                            {FieldName.T: recent_trace},
                        )
                    ).scalar()
                    or 0
                )
                trace_coverage[FieldName.IN_AGENT_LOGS] = int(
                    (
                        await session.execute(
                            text("SELECT COUNT(*) FROM agent_logs WHERE trace_id = :t"),
                            {FieldName.T: recent_trace},
                        )
                    ).scalar()
                    or 0
                )
                trace_coverage[FieldName.IN_TRADE_LIFECYCLE] = int(
                    (
                        await session.execute(
                            text(
                                """
                                SELECT COUNT(*) FROM trade_lifecycle
                                WHERE execution_trace_id = :t
                                   OR decision_trace_id = :t
                                   OR signal_trace_id = :t
                                   OR grade_trace_id = :t
                                   OR reflection_trace_id = :t
                                """
                            ),
                            {FieldName.T: recent_trace},
                        )
                    ).scalar()
                    or 0
                )

        counts = {k: int(v or 0) for k, v in dict(counts_row).items()}
        return {
            FieldName.API_VERSION: DASHBOARD_API_VERSION,
            FieldName.DB_SCHEMA_VERSION: DB_SCHEMA_VERSION,
            FieldName.DEGRADED_MODE: False,
            FieldName.COUNTS: counts,
            FieldName.REALTIME_EVENT_COUNT: counts.get(FieldName.AGENT_RUNS, 0),
            FieldName.PERSISTED_EVENT_COUNT: counts.get(FieldName.AGENT_LOGS, 0),
            FieldName.TRACE_COVERAGE: trace_coverage,
            "timestamp": now_iso(),
        }
    except Exception:
        log_structured("warning", "flow_status_db_unavailable", exc_info=True)
        return _flow_status_memory_payload()
