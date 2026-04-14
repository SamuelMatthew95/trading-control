"""
Metrics Aggregator - Centralized read layer for system metrics.

Provides clean, normalized metrics for the UI and eliminates NaN issues.
Computes lag per stream, system health, and PnL safely.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import LogType
from ..core.models import Order, Position, TradePerformance
from ..observability import log_structured

# Health validation thresholds
STALE_THRESHOLD_SECONDS = 30  # Mark stream as stale if no update in 30s
CRITICAL_LAG_MS = 5000  # Mark stream as critical if lag > 5 seconds
WARNING_LAG_MS = 1000  # Mark stream as warning if lag > 1 second


class MetricsAggregator:
    """Centralized metrics read layer with safe computations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_stream_lag_metrics(self) -> dict[str, Any]:
        """
        Get latest stream lag metrics per stream.

        Returns:
            Dict with stream names as keys and lag info as values
        """
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
                        "lag_ms": float(row.lag_ms or 0),
                        "lag_seconds": float(row.lag_ms or 0) / 1000,
                        "timestamp": (row.timestamp.isoformat() if row.timestamp else None),
                        "tags": row.tags or {},
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
        try:
            health = {
                "overall_status": "healthy",
                "streams_status": {},
                "last_update": datetime.now(timezone.utc).isoformat(),
            }

            # Get stream lag metrics
            lag_metrics = await self.get_stream_lag_metrics()

            # Check each stream health
            for stream, metrics in lag_metrics.items():
                lag_ms = metrics["lag_ms"]
                timestamp_str = metrics["timestamp"]

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

                health["streams_status"][stream] = {
                    "status": status,
                    "lag_ms": lag_ms,
                    "is_stale": is_stale,
                }

                # Update overall status
                if status == "critical":
                    health["overall_status"] = "critical"
                elif status == "warning" and health["overall_status"] == "healthy":
                    health["overall_status"] = "warning"
                elif status == "stale" and health["overall_status"] == "healthy":
                    health["overall_status"] = "stale"

            return health

        except Exception as e:
            log_structured("error", "system health computation failed", exc_info=True)
            return {
                "overall_status": "error",
                "error": str(e),
                "last_update": datetime.now(timezone.utc).isoformat(),
            }

    async def get_pnl_metrics(self) -> dict[str, Any]:
        """
        Compute PnL metrics safely.

        Returns:
            Dict with PnL information
        """
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
                "total_pnl": total_pnl,
                "today_pnl": today_pnl,
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate_percent": win_rate,
                "status": "healthy" if total_trades > 0 else "no_trades",
                "last_update": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            # Handle missing trade_performance table gracefully
            log_structured(
                "warning",
                "Trade performance table unavailable - using fallback",
                exc_info=True,
            )
            return {
                "total_pnl": 0.0,
                "today_pnl": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "win_rate_percent": 0.0,
                "status": "table_missing",
                "error": str(e),
                "last_update": datetime.now(timezone.utc).isoformat(),
            }

    async def get_agent_metrics(self) -> dict[str, Any]:
        """
        Get agent activity metrics.

        Returns:
            Dict with agent information
        """
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
                {"five_min_ago": five_min_ago},
            )
            rows = result.fetchall()

            active_agents = []
            for row in rows:
                active_agents.append(
                    {
                        "agent_id": row.agent_run_id,
                        "last_seen": (row.last_seen.isoformat() if row.last_seen else None),
                        "message_count_5min": int(row.message_count or 0),
                    }
                )

            return {
                "active_agents": active_agents,
                "active_agent_count": len(active_agents),
                "last_update": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured("error", "agent metrics failed", exc_info=True)
            return {
                "active_agents": [],
                "active_agent_count": 0,
                "error": str(e),
                "last_update": datetime.now(timezone.utc).isoformat(),
            }

    async def get_order_metrics(self) -> dict[str, Any]:
        """
        Get order flow metrics.

        Returns:
            Dict with order information
        """
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
            filled_orders = order_stats.get("filled", 0)
            fill_rate = (filled_orders / total_orders * 100) if total_orders > 0 else 0

            return {
                "orders_last_hour": order_stats,
                "total_orders_last_hour": total_orders,
                "fill_rate_percent": fill_rate,
                "last_update": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured("error", "order metrics failed", exc_info=True)
            return {
                "orders_last_hour": {},
                "total_orders_last_hour": 0,
                "fill_rate_percent": 0,
                "error": str(e),
                "last_update": datetime.now(timezone.utc).isoformat(),
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
                "stream_lag": stream_lag,
                "system_health": system_health,
                "pnl": pnl_metrics,
                "agents": agent_metrics,
                "orders": order_metrics,
            }

            # Ensure no NaN values - replace with 0 or null
            return self._sanitize_snapshot(snapshot)

        except Exception:
            log_structured("error", "dashboard snapshot failed", exc_info=True)
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "snapshot_failed",
                "stream_lag": {},
                "system_health": {"overall_status": "error"},
                "pnl": {"total_pnl": 0, "today_pnl": 0},
                "agents": {"active_agents": [], "active_agent_count": 0},
                "orders": {"orders_last_hour": {}, "total_orders_last_hour": 0},
            }

    async def get_raw_snapshot(self) -> dict[str, Any]:
        """Return raw DB rows matching the frontend DashboardData type.

        This is used for the WebSocket initial snapshot so every client
        starts with the same consistent view without any REST calls.
        """

        def _safe_float(val: Any) -> float:
            try:
                return float(val) if val is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        def _safe_str(val: Any) -> str | None:
            return str(val) if val is not None else None

        try:
            # Recent orders (last 50, newest first)
            orders_result = await self.session.execute(
                select(Order).order_by(Order.created_at.desc()).limit(50)
            )
            orders = [
                {
                    "order_id": _safe_str(o.id),
                    "symbol": o.symbol,
                    "side": o.side,
                    "quantity": _safe_float(o.quantity),
                    "price": _safe_float(o.price),
                    "filled_price": _safe_float(o.filled_price),
                    "status": o.status,
                    "pnl": 0.0,  # filled in by trade_performance
                    "timestamp": o.created_at.isoformat() if o.created_at else None,
                    "entry_price": _safe_float(o.price),
                    "current_price": _safe_float(o.filled_price or o.price),
                }
                for o in orders_result.scalars().all()
            ]

            # Current positions
            positions_result = await self.session.execute(
                select(Position).order_by(Position.updated_at.desc()).limit(50)
            )
            positions = [
                {
                    "symbol": p.symbol,
                    "side": "long" if _safe_float(p.quantity) >= 0 else "short",
                    "quantity": _safe_float(p.quantity),
                    "entry_price": _safe_float(p.avg_cost),
                    "current_price": _safe_float(p.last_price or p.avg_cost),
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
            payload_col_type = column_types.get("payload", "")
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
                    "id": _safe_str(row.id),
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
                        import json as _json

                        try:
                            metrics_val = _json.loads(metrics_val)
                        except Exception:
                            metrics_val = {}
                    learning_events.append(
                        {
                            "id": _safe_str(row[0]),
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
                        import json as _json

                        try:
                            p = _json.loads(p)
                        except Exception:
                            p = {}
                    if not isinstance(p, dict):
                        p = {}
                    proposals.append(
                        {
                            "id": _safe_str(row[0]) or _safe_str(p.get("msg_id")),
                            "proposal_type": _safe_str(p.get("proposal_type"))
                            or "parameter_change",
                            "content": _safe_str(p.get("content") or p.get("description") or ""),
                            "requires_approval": bool(p.get("requires_approval", True)),
                            "confidence": _safe_float(p.get("confidence")) or None,
                            "reflection_trace_id": _safe_str(p.get("reflection_trace_id")),
                            "status": _safe_str(p.get("status")) or "pending",
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
                            "id": _safe_str(row[0]),
                            "symbol": _safe_str(row[1]) or "",
                            "side": _safe_str(row[2]) or "buy",
                            "qty": _safe_float(row[3]) or None,
                            "entry_price": _safe_float(row[4]) or None,
                            "exit_price": _safe_float(row[5]) or None,
                            "pnl": _safe_float(row[6]) or None,
                            "pnl_percent": _safe_float(row[7]) or None,
                            "grade": _safe_str(row[8]),
                            "grade_score": _safe_float(row[9]) or None,
                            "grade_label": _safe_str(row[10]),
                            "status": _safe_str(row[11]) or "filled",
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

            return {
                "orders": orders,
                "positions": positions,
                "agent_logs": agent_logs,
                "learning_events": learning_events,
                "proposals": proposals,
                "trade_feed": trade_feed,
                "signals": [],
                "risk_alerts": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception:
            log_structured("error", "raw_snapshot_failed", exc_info=True)
            return {
                "orders": [],
                "positions": [],
                "agent_logs": [],
                "learning_events": [],
                "proposals": [],
                "trade_feed": [],
                "signals": [],
                "risk_alerts": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def get_paired_pnl(self, redis_client=None) -> dict[str, Any]:
        """Return closed trade pairs and open position P&L for a complete portfolio view.

        Closed trades come from ``trade_lifecycle`` rows where ``pnl IS NOT NULL``
        (each row = one completed round-trip: entry_price, exit_price, realized pnl).

        Open positions are read from ``positions`` and enriched with current price
        from Redis (when ``redis_client`` is provided) to show unrealized P&L.
        """
        import json as _json

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
            return {"closed_trades": [], "open_positions": [], "summary": {}}

        # --- Closed trades -------------------------------------------------
        closed_trades = []
        realized_pnl = 0.0
        winning = 0
        for row in closed_rows:
            pnl = float(row["pnl"] or 0)
            realized_pnl += pnl
            if pnl > 0:
                winning += 1
            closed_trades.append(
                {
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "qty": float(row["qty"] or 0),
                    "entry_price": float(row["entry_price"] or 0),
                    "exit_price": float(row["exit_price"] or 0),
                    "pnl": round(pnl, 8),
                    "pnl_percent": round(float(row["pnl_percent"] or 0), 4),
                    "grade": row.get("grade"),
                    "status": row.get("status"),
                    "filled_at": row["filled_at"].isoformat() if row["filled_at"] else None,
                    "order_id": str(row["order_id"]) if row.get("order_id") else None,
                    "trace_id": row.get("execution_trace_id"),
                }
            )

        total_closed = len(closed_trades)
        win_rate = (winning / total_closed * 100) if total_closed else 0.0

        # --- Open positions ------------------------------------------------
        open_positions = []
        unrealized_pnl = 0.0
        for row in open_rows:
            symbol = str(row["symbol"])
            avg_cost = float(row["avg_cost"] or 0)
            qty = float(row["qty"] or 0)
            side = str(row["side"]).lower()

            # Try enriching with live price from Redis
            current_price = avg_cost  # fallback
            if redis_client is not None:
                try:
                    from api.constants import REDIS_KEY_PRICES

                    raw = await redis_client.get(REDIS_KEY_PRICES.format(symbol=symbol))
                    if raw:
                        price_data = _json.loads(raw)
                        current_price = float(
                            price_data.get("price") or price_data.get("last_price") or avg_cost
                        )
                except Exception:
                    pass

            if avg_cost > 0 and qty > 0:
                if side == "long":
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
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "avg_cost": avg_cost,
                    "current_price": round(current_price, 8),
                    "unrealized_pnl": round(pos_pnl, 8),
                    "unrealized_pnl_pct": round(pnl_pct * 100, 4),
                    "market_value": round(current_price * qty, 8),
                }
            )

        return {
            "closed_trades": closed_trades,
            "open_positions": open_positions,
            "summary": {
                "realized_pnl": round(realized_pnl, 8),
                "unrealized_pnl": round(unrealized_pnl, 8),
                "total_pnl": round(realized_pnl + unrealized_pnl, 8),
                "closed_trades": total_closed,
                "winning_trades": winning,
                "win_rate_percent": round(win_rate, 2),
                "open_positions": len(open_positions),
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
        import math

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
