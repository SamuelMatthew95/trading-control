"""
Metrics Aggregator - Centralized read layer for system metrics.

Provides clean, normalized metrics for the UI and eliminates NaN issues.
Computes lag per stream, system health, and PnL safely.
"""

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    CRITICAL_LAG_MS,
    REDIS_KEY_PRICES,
    STALE_THRESHOLD_SECONDS,
    WARNING_LAG_MS,
    FieldName,
    LogType,
    OrderSide,
    OrderStatus,
    PositionSide,
    Source,
)
from ..core.models import Order, Position, TradePerformance
from ..observability import log_structured
from ..runtime_state import get_runtime_store
from .metrics_calc import closed_trade_stats
from .notification_summary import compute_notification_summary


class MetricsAggregator:
    """Centralized metrics read layer with safe computations."""

    def __init__(self, session: AsyncSession | None, *, use_memory_store: bool = False):
        self.session = session
        self.use_memory_store = use_memory_store

    def _using_memory_store(self) -> bool:
        return self.use_memory_store or self.session is None

    def _memory_pnl_metrics(self) -> dict[str, Any]:
        store = get_runtime_store()
        orders = list(store.orders)
        stats = closed_trade_stats(orders)
        return {
            FieldName.TOTAL_PNL: stats.realized_pnl,
            FieldName.TODAY_PNL: stats.realized_pnl,
            FieldName.TOTAL_TRADES: len(orders),
            FieldName.WINNING_TRADES: stats.winning,
            FieldName.WIN_RATE_PERCENT: round(stats.win_rate * 100, 2),
            "status": "memory_mode",
            FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            "source": Source.IN_MEMORY,
        }

    def _memory_agent_metrics(self) -> dict[str, Any]:
        store = get_runtime_store()
        active_agents = [
            {
                "agent_id": agent_id,
                "last_seen": data.get(FieldName.LAST_SEEN) or data.get(FieldName.LAST_SEEN_AT),
                FieldName.MESSAGE_COUNT_5MIN: int(data.get(FieldName.EVENT_COUNT) or 0),
            }
            for agent_id, data in store.agents.items()
            if str(data.get(FieldName.STATUS, "")).lower() in {"active", "running", "live"}
        ]
        return {
            FieldName.ACTIVE_AGENTS: active_agents,
            FieldName.ACTIVE_AGENT_COUNT: len(active_agents),
            FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            "source": Source.IN_MEMORY,
        }

    def _memory_order_metrics(self) -> dict[str, Any]:
        order_stats: dict[str, int] = {}
        for order in get_runtime_store().orders:
            status = str(order.get(FieldName.STATUS) or "unknown")
            order_stats[status] = order_stats.get(status, 0) + 1
        total_orders = sum(order_stats.values())
        filled_orders = order_stats.get(OrderStatus.FILLED, 0) + order_stats.get(
            FieldName.EXECUTED, 0
        )
        fill_rate = (filled_orders / total_orders * 100) if total_orders else 0.0
        return {
            FieldName.ORDERS_LAST_HOUR: order_stats,
            FieldName.TOTAL_ORDERS_LAST_HOUR: total_orders,
            FieldName.FILL_RATE_PERCENT: fill_rate,
            FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            "source": Source.IN_MEMORY,
        }

    def _memory_paired_pnl(self) -> dict[str, Any]:
        store = get_runtime_store()
        closed_trades = list(reversed(store.trade_feed[-100:]))
        stats = closed_trade_stats(closed_trades)
        open_positions = list(store.positions.values())
        unrealized_pnl = sum(
            float(position.get(FieldName.UNREALIZED_PNL) or 0.0) for position in open_positions
        )
        return {
            FieldName.CLOSED_TRADES: closed_trades,
            FieldName.OPEN_POSITIONS: open_positions,
            "summary": {
                FieldName.REALIZED_PNL: round(stats.realized_pnl, 8),
                "unrealized_pnl": round(unrealized_pnl, 8),
                FieldName.TOTAL_PNL: round(stats.realized_pnl + unrealized_pnl, 8),
                FieldName.CLOSED_TRADES: stats.closed,
                FieldName.WINNING_TRADES: stats.winning,
                FieldName.WIN_RATE_PERCENT: round(stats.win_rate * 100, 2),
                FieldName.OPEN_POSITIONS: len(open_positions),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": Source.IN_MEMORY,
        }

    async def get_stream_lag_metrics(self) -> dict[str, Any]:
        """
        Get latest stream lag metrics per stream.

        Returns:
            Dict with stream names as keys and lag info as values
        """
        if self._using_memory_store():
            return {}

        try:
            # Query latest lag per stream using DISTINCT ON
            query = text("""
                SELECT DISTINCT ON (tags->>'stream')
                    tags->>'stream' as stream,
                    metric_value::float as lag_ms,
                    timestamp,
                    tags
                FROM system_metrics
                WHERE metric_name = 'stream_lag'
                ORDER BY tags->>'stream', timestamp DESC
            """)

            result = await self.session.execute(query)
            rows = result.fetchall()

            lag_metrics = {}
            for row in rows:
                stream = row.stream
                if stream:  # Guard against null stream
                    lag_metrics[stream] = {
                        FieldName.LAG_MS: float(row.lag_ms or 0),
                        FieldName.LAG_SECONDS: float(row.lag_ms or 0) / 1000,
                        "timestamp": (row.timestamp.isoformat() if row.timestamp else None),
                        FieldName.TAGS: row.tags or {},
                    }

            return lag_metrics

        except Exception:
            log_structured("error", "stream lag metrics failed", exc_info=True)
            return {}

    async def get_system_health(self) -> dict[str, Any]:
        """
        Compute overall system health metrics.

        Returns:
            Dict with health indicators
        """
        if self._using_memory_store():
            return {
                FieldName.OVERALL_STATUS: "degraded",
                FieldName.STREAMS_STATUS: {},
                FieldName.MODE: "in_memory",
                FieldName.DB_HEALTH: get_runtime_store().last_health,
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
                "source": Source.IN_MEMORY,
            }

        try:
            health = {
                FieldName.OVERALL_STATUS: "healthy",
                FieldName.STREAMS_STATUS: {},
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }
            # Get stream lag metrics
            lag_metrics = await self.get_stream_lag_metrics()

            # Check each stream health
            for stream, metrics in lag_metrics.items():
                lag_ms = metrics[FieldName.LAG_MS]
                timestamp_str = metrics[FieldName.TIMESTAMP]

                # Parse timestamp to check staleness
                is_stale = False
                if timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
                        is_stale = age_seconds > STALE_THRESHOLD_SECONDS
                    except (ValueError, AttributeError):
                        is_stale = True
                else:
                    is_stale = True

                # Determine status using thresholds
                if is_stale:
                    status = "stale"
                elif lag_ms > CRITICAL_LAG_MS:
                    status = "critical"
                elif lag_ms > WARNING_LAG_MS:
                    status = "warning"
                else:
                    status = "healthy"

                health[FieldName.STREAMS_STATUS][stream] = {
                    "status": status,
                    FieldName.LAG_MS: lag_ms,
                    FieldName.IS_STALE: is_stale,
                }

                # Update overall status
                if status == "critical":
                    health[FieldName.OVERALL_STATUS] = "critical"
                elif status == "warning" and health[FieldName.OVERALL_STATUS] == "healthy":
                    health[FieldName.OVERALL_STATUS] = "warning"
                elif status == "stale" and health[FieldName.OVERALL_STATUS] == "healthy":
                    health[FieldName.OVERALL_STATUS] = "stale"

            return health

        except Exception as e:
            log_structured("error", "system health computation failed", exc_info=True)
            return {
                FieldName.OVERALL_STATUS: "error",
                "error": str(e),
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }

    async def get_pnl_metrics(self) -> dict[str, Any]:
        """
        Compute PnL metrics safely.

        Returns:
            Dict with PnL information
        """
        if self._using_memory_store():
            return self._memory_pnl_metrics()

        try:
            # Get total PnL from trade_performance
            pnl_query = select(func.coalesce(func.sum(TradePerformance.pnl), 0))
            result = await self.session.execute(pnl_query)
            total_pnl = float(result.scalar() or 0)

            # Get today's PnL
            today = datetime.now(timezone.utc).date()
            today_pnl_query = select(func.coalesce(func.sum(TradePerformance.pnl), 0)).where(
                TradePerformance.created_at >= today
            )
            result = await self.session.execute(today_pnl_query)
            today_pnl = float(result.scalar() or 0)

            # Get trade count
            trade_count_query = select(func.count(TradePerformance.id))
            result = await self.session.execute(trade_count_query)
            total_trades = int(result.scalar() or 0)

            # Get winning trades
            winning_trades_query = select(func.count(TradePerformance.id)).where(
                TradePerformance.pnl > 0
            )
            result = await self.session.execute(winning_trades_query)
            winning_trades = int(result.scalar() or 0)

            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            return {
                FieldName.TOTAL_PNL: total_pnl,
                FieldName.TODAY_PNL: today_pnl,
                FieldName.TOTAL_TRADES: total_trades,
                FieldName.WINNING_TRADES: winning_trades,
                FieldName.WIN_RATE_PERCENT: win_rate,
                "status": "healthy" if total_trades > 0 else "no_trades",
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            # Handle missing trade_performance table gracefully
            log_structured(
                "warning",
                "Trade performance table unavailable - using fallback",
                exc_info=True,
            )
            return {
                FieldName.TOTAL_PNL: 0.0,
                FieldName.TODAY_PNL: 0.0,
                FieldName.TOTAL_TRADES: 0,
                FieldName.WINNING_TRADES: 0,
                FieldName.WIN_RATE_PERCENT: 0.0,
                "status": "table_missing",
                "error": str(e),
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }

    async def get_agent_metrics(self) -> dict[str, Any]:
        """
        Get agent activity metrics.

        Returns:
            Dict with agent information
        """
        if self._using_memory_store():
            return self._memory_agent_metrics()

        try:
            # Get recent agent activity (schema compatible across legacy/new agent_logs)
            five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
            columns_result = await self.session.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'agent_logs'
                    """
                )
            )
            available_columns = {row[0] for row in columns_result}

            time_col = "created_at" if "created_at" in available_columns else "timestamp"
            run_col = "agent_run_id" if "agent_run_id" in available_columns else "source"

            result = await self.session.execute(
                text(
                    f"""
                    SELECT
                        {run_col} AS agent_run_id,
                        MAX({time_col}) AS last_seen,
                        COUNT(id) AS message_count
                    FROM agent_logs
                    WHERE {time_col} >= :five_min_ago
                    GROUP BY {run_col}
                    """
                ),
                {FieldName.FIVE_MIN_AGO: five_min_ago},
            )
            rows = result.fetchall()

            active_agents = []
            for row in rows:
                active_agents.append(
                    {
                        "agent_id": row.agent_run_id,
                        "last_seen": (row.last_seen.isoformat() if row.last_seen else None),
                        FieldName.MESSAGE_COUNT_5MIN: int(row.message_count or 0),
                    }
                )

            return {
                FieldName.ACTIVE_AGENTS: active_agents,
                FieldName.ACTIVE_AGENT_COUNT: len(active_agents),
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured("error", "agent metrics failed", exc_info=True)
            return {
                FieldName.ACTIVE_AGENTS: [],
                FieldName.ACTIVE_AGENT_COUNT: 0,
                "error": str(e),
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }

    async def get_order_metrics(self) -> dict[str, Any]:
        """
        Get order flow metrics.

        Returns:
            Dict with order information
        """
        if self._using_memory_store():
            return self._memory_order_metrics()

        try:
            # Get order counts by status in last hour
            hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

            order_stats_query = (
                select(Order.status, func.count(Order.id).label("count"))
                .where(Order.created_at >= hour_ago)
                .group_by(Order.status)
            )

            result = await self.session.execute(order_stats_query)
            rows = result.fetchall()

            order_stats = {}
            total_orders = 0
            for row in rows:
                order_stats[row.status] = int(row.count or 0)
                total_orders += order_stats[row.status]

            # Get fill rate
            filled_orders = order_stats.get(FieldName.FILLED, 0)
            fill_rate = (filled_orders / total_orders * 100) if total_orders > 0 else 0

            return {
                FieldName.ORDERS_LAST_HOUR: order_stats,
                FieldName.TOTAL_ORDERS_LAST_HOUR: total_orders,
                FieldName.FILL_RATE_PERCENT: fill_rate,
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured("error", "order metrics failed", exc_info=True)
            return {
                FieldName.ORDERS_LAST_HOUR: {},
                FieldName.TOTAL_ORDERS_LAST_HOUR: 0,
                FieldName.FILL_RATE_PERCENT: 0,
                "error": str(e),
                FieldName.LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            }

    async def get_dashboard_snapshot(self) -> dict[str, Any]:
        """
        Get complete dashboard snapshot with all metrics.

        Returns:
            Complete dashboard data with no NaN values
        """
        try:
            # Get all metrics in parallel
            stream_lag = await self.get_stream_lag_metrics()
            system_health = await self.get_system_health()
            pnl_metrics = await self.get_pnl_metrics()
            agent_metrics = await self.get_agent_metrics()
            order_metrics = await self.get_order_metrics()

            # Combine into snapshot
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                FieldName.STREAM_LAG: stream_lag,
                FieldName.SYSTEM_HEALTH: system_health,
                "pnl": pnl_metrics,
                FieldName.AGENTS: agent_metrics,
                FieldName.ORDERS: order_metrics,
            }

            # Ensure no NaN values - replace with 0 or null
            return self._sanitize_snapshot(snapshot)

        except Exception:
            log_structured("error", "dashboard snapshot failed", exc_info=True)
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "snapshot_failed",
                FieldName.STREAM_LAG: {},
                FieldName.SYSTEM_HEALTH: {FieldName.OVERALL_STATUS: "error"},
                "pnl": {FieldName.TOTAL_PNL: 0, FieldName.TODAY_PNL: 0},
                FieldName.AGENTS: {FieldName.ACTIVE_AGENTS: [], FieldName.ACTIVE_AGENT_COUNT: 0},
                FieldName.ORDERS: {
                    FieldName.ORDERS_LAST_HOUR: {},
                    FieldName.TOTAL_ORDERS_LAST_HOUR: 0,
                },
            }

    async def get_raw_snapshot(self) -> dict[str, Any]:
        """Return raw DB rows matching the frontend DashboardData type.

        This is used for the WebSocket initial snapshot so every client
        starts with the same consistent view without any REST calls.
        """
        if self._using_memory_store():
            return get_runtime_store().dashboard_fallback_snapshot()

        def _safe_float(val: Any) -> float:
            try:
                return float(val) if val is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        def _safe_str(val: Any) -> str | None:
            return str(val) if val is not None else None

        try:
            # Recent orders (last 50, newest first) joined with trade_lifecycle
            # to populate real realized PnL values.
            orders_sql = text("""
                SELECT
                    o.id::text          AS order_id,
                    o.symbol,
                    o.side,
                    o.quantity,
                    o.price,
                    o.filled_price,
                    o.status,
                    o.created_at,
                    COALESCE(tl.pnl, 0.0)         AS pnl,
                    COALESCE(tl.pnl_percent, 0.0)  AS pnl_percent
                FROM orders o
                LEFT JOIN trade_lifecycle tl ON tl.order_id = o.id::text
                ORDER BY o.created_at DESC
                LIMIT 50
            """)
            orders_result = await self.session.execute(orders_sql)
            orders = [
                {
                    "order_id": row.order_id,
                    "symbol": row.symbol,
                    "side": row.side,
                    "quantity": _safe_float(row.quantity),
                    "price": _safe_float(row.price),
                    "filled_price": _safe_float(row.filled_price),
                    "status": row.status,
                    "pnl": _safe_float(row.pnl),
                    "pnl_percent": _safe_float(row.pnl_percent),
                    "timestamp": row.created_at.isoformat() if row.created_at else None,
                    "filled_at": (
                        row.created_at.isoformat()
                        if row.created_at
                        and str(row.status or "").lower()
                        in {"filled", "closed", "executed", "completed"}
                        else None
                    ),
                    "entry_price": _safe_float(row.price),
                    FieldName.CURRENT_PRICE: _safe_float(row.filled_price or row.price),
                }
                for row in orders_result.all()
            ]

            # Current positions — only non-flat (quantity != 0)
            positions_result = await self.session.execute(
                select(Position)
                .where(Position.quantity != 0)
                .order_by(Position.updated_at.desc())
                .limit(50)
            )
            positions = [
                {
                    "symbol": p.symbol,
                    "side": PositionSide.LONG
                    if _safe_float(p.quantity) > 0
                    else PositionSide.SHORT,
                    "quantity": _safe_float(p.quantity),
                    "entry_price": _safe_float(p.avg_cost),
                    FieldName.CURRENT_PRICE: _safe_float(p.last_price or p.avg_cost),
                    "pnl": _safe_float(p.unrealized_pnl),
                    "market_value": _safe_float(p.market_value),
                }
                for p in positions_result.scalars().all()
            ]

            # Recent agent logs (last 50)
            # NOTE: agent_logs has historically had multiple schemas in production
            # (legacy: log_type/payload; newer: log_level/message/source/timestamp).
            # Resolve available columns first and build a backward-compatible query.
            columns_result = await self.session.execute(
                text(
                    """
                    SELECT column_name, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'agent_logs'
                    """
                )
            )
            column_types = {row[0]: row[1] for row in columns_result}
            available_columns = set(column_types)
            order_column = "created_at" if "created_at" in available_columns else "timestamp"

            def _select(col: str, fallback_sql: str = "NULL") -> str:
                return col if col in available_columns else fallback_sql

            # Live DB stores payload as TEXT (JSON string), not native JSONB.
            # Treat text as parseable JSON too so message extraction works.
            payload_col_type = column_types.get(FieldName.PAYLOAD, "")
            payload_exists = "payload" in available_columns
            payload_is_native_json = payload_col_type in {"json", "jsonb"}
            # For text columns we still cast to jsonb for field extraction;
            # the cast is safe because we only insert valid JSON into payload.
            payload_is_json = payload_exists  # always try if the column is present
            payload_message = "payload::jsonb->>'message'" if payload_is_json else "NULL"
            payload_content = "payload::jsonb->>'content'" if payload_is_json else "NULL"
            payload_reason = "payload::jsonb->>'reason'" if payload_is_json else "NULL"
            payload_text = "payload::text" if payload_exists else "NULL"
            _ = payload_is_native_json  # retained for future use
            legacy_log_type = "log_type" if "log_type" in available_columns else "NULL"

            logs_sql = text(
                f"""
                SELECT
                    id,
                    {_select("trace_id")} AS trace_id,
                    {_select("source", "'agent'")} AS agent_name,
                    COALESCE(
                        {_select("message")},
                        {payload_message},
                        {payload_content},
                        {payload_reason},
                        {payload_text},
                        {legacy_log_type}
                    ) AS message,
                    {_select("log_level", legacy_log_type)} AS log_level,
                    {_select(order_column)} AS ts
                FROM agent_logs
                ORDER BY {_select(order_column)} DESC
                LIMIT 50
                """
            )
            logs_result = await self.session.execute(logs_sql)
            agent_logs = [
                {
                    FieldName.ID: _safe_str(row.id),
                    "agent_name": _safe_str(row.agent_name) or "agent",
                    "message": _safe_str(row.message),
                    "timestamp": row.ts.isoformat() if row.ts else None,
                    "log_level": _safe_str(row.log_level),
                    "trace_id": _safe_str(row.trace_id),
                }
                for row in logs_result
            ]

            # Recent learning events from agent_grades (last 20)
            learning_events: list[dict[str, Any]] = []
            try:
                grades_result = await self.session.execute(
                    text("""
                        SELECT trace_id, grade_type, score, metrics, created_at
                        FROM agent_grades
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                )
                for row in grades_result:
                    metrics_val = row[3]
                    if isinstance(metrics_val, str):
                        try:
                            metrics_val = json.loads(metrics_val)
                        except Exception:
                            metrics_val = {}
                    learning_events.append(
                        {
                            FieldName.ID: _safe_str(row[0]),
                            "type": "trade_evaluated",
                            "grade_type": _safe_str(row[1]) or "pipeline",
                            "score": _safe_float(row[2]),
                            "score_pct": round(_safe_float(row[2]) * 100, 2),
                            "metrics": metrics_val or {},
                            "timestamp": row[4].isoformat() if row[4] else None,
                        }
                    )
            except Exception:
                log_structured("warning", "raw_snapshot_grades_failed", exc_info=True)

            # Recent proposals from agent_logs
            proposals: list[dict[str, Any]] = []
            try:
                # Guard: only query log_type column if it exists in this schema
                if "log_type" not in available_columns or "payload" not in available_columns:
                    raise RuntimeError(
                        "agent_logs missing log_type/payload columns — skipping proposals"
                    )
                proposals_result = await self.session.execute(
                    text("""
                        SELECT trace_id, payload, created_at
                        FROM agent_logs
                        WHERE log_type = :log_type
                        ORDER BY created_at DESC
                        LIMIT 20
                    """),
                    {"log_type": LogType.PROPOSAL},
                )
                for row in proposals_result:
                    p = row[1]
                    if isinstance(p, str):
                        try:
                            p = json.loads(p)
                        except Exception:
                            p = {}
                    if not isinstance(p, dict):
                        p = {}
                    proposals.append(
                        {
                            FieldName.ID: _safe_str(row[0]) or _safe_str(p.get(FieldName.MSG_ID)),
                            "proposal_type": _safe_str(p.get(FieldName.PROPOSAL_TYPE))
                            or "parameter_change",
                            "content": _safe_str(
                                p.get(FieldName.CONTENT) or p.get(FieldName.DESCRIPTION) or ""
                            ),
                            "requires_approval": bool(p.get(FieldName.REQUIRES_APPROVAL, True)),
                            "confidence": _safe_float(p.get(FieldName.CONFIDENCE)) or None,
                            "reflection_trace_id": _safe_str(p.get(FieldName.REFLECTION_TRACE_ID)),
                            "status": _safe_str(p.get(FieldName.STATUS)) or OrderStatus.PENDING,
                            # ProposalApplier's applied record shares the trace_id with
                            # the original proposal row, so these flow to the UI and flip
                            # the queue row from "pending" to "applied" — an auto-applied
                            # promotion can never look like it is still waiting for a vote.
                            "applied": bool(p.get(FieldName.APPLIED, False)),
                            "applied_at": _safe_str(p.get(FieldName.APPLIED_AT)) or None,
                            "timestamp": row[2].isoformat() if row[2] else None,
                        }
                    )
            except Exception:
                log_structured("warning", "raw_snapshot_proposals_failed", exc_info=True)

            # Recent trade lifecycle (last 20)
            trade_feed: list[dict[str, Any]] = []
            try:
                tl_result = await self.session.execute(
                    text("""
                        SELECT
                            id, symbol, side, qty, entry_price, exit_price,
                            pnl, pnl_percent, grade, grade_score, grade_label,
                            status, filled_at, graded_at, execution_trace_id,
                            signal_trace_id, order_id, created_at
                        FROM trade_lifecycle
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                )
                for row in tl_result:
                    trade_feed.append(
                        {
                            FieldName.ID: _safe_str(row[0]),
                            "symbol": _safe_str(row[1]) or "",
                            "side": _safe_str(row[2]) or OrderSide.BUY,
                            "qty": _safe_float(row[3]) or None,
                            "entry_price": _safe_float(row[4]) or None,
                            "exit_price": _safe_float(row[5]) or None,
                            "pnl": _safe_float(row[6]) or None,
                            "pnl_percent": _safe_float(row[7]) or None,
                            "grade": _safe_str(row[8]),
                            "grade_score": _safe_float(row[9]) or None,
                            "grade_label": _safe_str(row[10]),
                            "status": _safe_str(row[11]) or OrderStatus.FILLED,
                            "filled_at": row[12].isoformat() if row[12] else None,
                            "graded_at": row[13].isoformat() if row[13] else None,
                            "execution_trace_id": _safe_str(row[14]),
                            "signal_trace_id": _safe_str(row[15]),
                            "order_id": _safe_str(row[16]),
                            "created_at": row[17].isoformat() if row[17] else None,
                        }
                    )
            except Exception:
                log_structured("warning", "raw_snapshot_trade_feed_failed", exc_info=True)

            # Recent notifications (last 50) — persisted by SafeWriter.write_notification
            # as event rows. The UI hydrates from this so buy/sell fills survive a page
            # reload instead of only appearing on the live WebSocket stream.
            notifications: list[dict[str, Any]] = []
            try:
                notif_result = await self.session.execute(
                    text("""
                        SELECT data, created_at
                        FROM events
                        WHERE event_type = 'notification.created'
                        ORDER BY created_at DESC
                        LIMIT 50
                    """)
                )
                for row in notif_result:
                    payload = row[0]
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:
                            payload = {}
                    if not isinstance(payload, dict):
                        continue
                    entry = dict(payload)
                    entry.setdefault(
                        FieldName.TIMESTAMP,
                        row[1].isoformat() if row[1] else None,
                    )
                    notifications.append(entry)
            except Exception:
                log_structured("warning", "raw_snapshot_notifications_failed", exc_info=True)

            notification_summary = compute_notification_summary(notifications)

            return {
                FieldName.ORDERS: orders,
                FieldName.POSITIONS: positions,
                FieldName.AGENT_LOGS: agent_logs,
                FieldName.LEARNING_EVENTS: learning_events,
                FieldName.PROPOSALS: proposals,
                FieldName.TRADE_FEED: trade_feed,
                FieldName.NOTIFICATIONS: notifications,
                FieldName.NOTIFICATION_SUMMARY: notification_summary,
                FieldName.SIGNALS: [],
                FieldName.RISK_ALERTS: [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception:
            log_structured("error", "raw_snapshot_failed", exc_info=True)
            return {
                FieldName.ORDERS: [],
                FieldName.POSITIONS: [],
                FieldName.AGENT_LOGS: [],
                FieldName.LEARNING_EVENTS: [],
                FieldName.PROPOSALS: [],
                FieldName.TRADE_FEED: [],
                FieldName.NOTIFICATIONS: [],
                FieldName.NOTIFICATION_SUMMARY: {
                    FieldName.SUMMARY_VERSION: 1,
                    FieldName.COUNTS: {
                        FieldName.TOTAL: 0,
                        FieldName.OPEN: 0,
                        FieldName.RESOLVED: 0,
                    },
                    FieldName.SEVERITY_COUNTS: [
                        {"severity": "success", FieldName.COUNT: 0},
                        {"severity": "info", FieldName.COUNT: 0},
                        {"severity": "warning", FieldName.COUNT: 0},
                        {"severity": "critical", FieldName.COUNT: 0},
                    ],
                    FieldName.TOTAL: 0,
                    FieldName.OPEN: 0,
                    FieldName.RESOLVED: 0,
                    FieldName.BY_SEVERITY: {
                        FieldName.SUCCESS: 0,
                        FieldName.INFO: 0,
                        FieldName.WARNING: 0,
                        FieldName.CRITICAL: 0,
                    },
                },
                FieldName.SIGNALS: [],
                FieldName.RISK_ALERTS: [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def get_paired_pnl(self, redis_client=None) -> dict[str, Any]:
        """Return closed trade pairs and open position P&L for a complete portfolio view.

        Closed trades come from ``trade_lifecycle`` rows where ``pnl IS NOT NULL``
        (each row = one completed round-trip: entry_price, exit_price, realized pnl).

        Open positions are read from ``positions`` and enriched with current price
        from Redis (when ``redis_client`` is provided) to show unrealized P&L.
        """
        if self._using_memory_store():
            return self._memory_paired_pnl()

        try:
            closed_result = await self.session.execute(
                text("""
                    SELECT symbol, side, qty, entry_price, exit_price, pnl, pnl_percent,
                           grade, status, filled_at, order_id, execution_trace_id
                    FROM trade_lifecycle
                    WHERE pnl IS NOT NULL AND pnl != 0
                    ORDER BY filled_at DESC NULLS LAST
                    LIMIT 100
                """)
            )
            closed_rows = closed_result.mappings().all()

            open_result = await self.session.execute(
                text("""
                    SELECT symbol, side, qty, avg_cost, unrealized_pnl, strategy_id
                    FROM positions
                    WHERE side != 'flat' AND qty > 0
                    ORDER BY symbol
                """)
            )
            open_rows = open_result.mappings().all()
        except Exception:
            log_structured("warning", "paired_pnl_query_failed", exc_info=True)
            return {FieldName.CLOSED_TRADES: [], FieldName.OPEN_POSITIONS: [], "summary": {}}

        # --- Closed trades -------------------------------------------------
        closed_trades = []
        realized_pnl = 0.0
        winning = 0
        for row in closed_rows:
            pnl = float(row[FieldName.PNL] or 0)
            realized_pnl += pnl
            if pnl > 0:
                winning += 1
            closed_trades.append(
                {
                    FieldName.SYMBOL: row[FieldName.SYMBOL],
                    FieldName.SIDE: row[FieldName.SIDE],
                    FieldName.QTY: float(row[FieldName.QTY] or 0),
                    "entry_price": float(row[FieldName.ENTRY_PRICE] or 0),
                    "exit_price": float(row[FieldName.EXIT_PRICE] or 0),
                    "pnl": round(pnl, 8),
                    "pnl_percent": round(float(row[FieldName.PNL_PERCENT] or 0), 4),
                    "grade": row.get(FieldName.GRADE),
                    FieldName.STATUS: row.get(FieldName.STATUS),
                    "filled_at": row[FieldName.FILLED_AT].isoformat()
                    if row[FieldName.FILLED_AT]
                    else None,
                    "order_id": str(row[FieldName.ORDER_ID])
                    if row.get(FieldName.ORDER_ID)
                    else None,
                    FieldName.TRACE_ID: row.get(FieldName.EXECUTION_TRACE_ID),
                }
            )

        total_closed = len(closed_trades)
        win_rate = (winning / total_closed * 100) if total_closed else 0.0

        # --- Open positions ------------------------------------------------
        open_positions = []
        unrealized_pnl = 0.0
        for row in open_rows:
            symbol = str(row[FieldName.SYMBOL])
            avg_cost = float(row[FieldName.AVG_COST] or 0)
            qty = float(row[FieldName.QTY] or 0)
            side = str(row[FieldName.SIDE]).lower()

            # Try enriching with live price from Redis
            current_price = avg_cost  # fallback
            if redis_client is not None:
                try:
                    raw = await redis_client.get(REDIS_KEY_PRICES.format(symbol=symbol))
                    if raw:
                        price_data = json.loads(raw)
                        current_price = float(
                            price_data.get(FieldName.PRICE)
                            or price_data.get(FieldName.LAST_PRICE)
                            or avg_cost
                        )
                except Exception:
                    pass

            if avg_cost > 0 and qty > 0:
                if side == PositionSide.LONG:
                    pos_pnl = (current_price - avg_cost) * qty
                    pnl_pct = (current_price - avg_cost) / avg_cost
                else:
                    pos_pnl = (avg_cost - current_price) * qty
                    pnl_pct = (avg_cost - current_price) / avg_cost
            else:
                pos_pnl = 0.0
                pnl_pct = 0.0

            unrealized_pnl += pos_pnl
            open_positions.append(
                {
                    FieldName.SYMBOL: symbol,
                    FieldName.SIDE: side,
                    FieldName.QTY: qty,
                    FieldName.AVG_COST: avg_cost,
                    FieldName.CURRENT_PRICE: round(current_price, 8),
                    "unrealized_pnl": round(pos_pnl, 8),
                    FieldName.UNREALIZED_PNL_PCT: round(pnl_pct * 100, 4),
                    "market_value": round(current_price * qty, 8),
                }
            )

        return {
            FieldName.CLOSED_TRADES: closed_trades,
            FieldName.OPEN_POSITIONS: open_positions,
            "summary": {
                FieldName.REALIZED_PNL: round(realized_pnl, 8),
                "unrealized_pnl": round(unrealized_pnl, 8),
                FieldName.TOTAL_PNL: round(realized_pnl + unrealized_pnl, 8),
                FieldName.CLOSED_TRADES: total_closed,
                FieldName.WINNING_TRADES: winning,
                FieldName.WIN_RATE_PERCENT: round(win_rate, 2),
                FieldName.OPEN_POSITIONS: len(open_positions),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _sanitize_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively sanitize snapshot to remove NaN values.

        Args:
            snapshot: Raw snapshot data

        Returns:
            Sanitized snapshot with no NaN values
        """

        def sanitize_value(value):
            if isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    return 0
                return value
            if isinstance(value, dict):
                return {k: sanitize_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [sanitize_value(item) for item in value]
            return value

        return sanitize_value(snapshot)
