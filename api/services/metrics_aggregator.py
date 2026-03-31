"""
Metrics Aggregator - Centralized read layer for system metrics.

Provides clean, normalized metrics for the UI and eliminates NaN issues.
Computes lag per stream, system health, and PnL safely.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.models import AgentLog, Order, TradePerformance
from ..observability import log_structured

logger = logging.getLogger(__name__)

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

        except Exception as e:
            log_structured("error", "stream lag metrics failed", error=str(e))
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
            log_structured("error", "system health computation failed", error=str(e))
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
                error=str(e),
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
            # Get recent agent activity
            five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)

            agent_activity_query = (
                select(
                    AgentLog.agent_run_id,
                    func.max(AgentLog.timestamp).label("last_seen"),
                    func.count(AgentLog.id).label("message_count"),
                )
                .where(AgentLog.timestamp >= five_min_ago)
                .group_by(AgentLog.agent_run_id)
            )

            result = await self.session.execute(agent_activity_query)
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
            log_structured("error", "agent metrics failed", error=str(e))
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
            log_structured("error", "order metrics failed", error=str(e))
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
