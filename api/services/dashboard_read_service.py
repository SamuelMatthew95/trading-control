from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import (
    ALL_AGENT_NAMES,
    REDIS_KEY_PRICES,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    FieldName,
)
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store
from api.services.metrics_aggregator import MetricsAggregator


class DashboardReadService:
    def update_in_memory_proposal_status(self, proposal_id: str, status: str) -> bool:
        store = get_runtime_store()
        updated = False

        def _as_dict(payload: Any) -> dict[str, Any]:
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, str):
                try:
                    loaded = json.loads(payload)
                    return loaded if isinstance(loaded, dict) else {}
                except json.JSONDecodeError:
                    return {}
            return {}

        def _matches(record: dict[str, Any]) -> bool:
            payload = _as_dict(record.get("payload"))
            candidates = {
                record.get("id"),
                record.get("trace_id"),
                record.get("msg_id"),
                payload.get("trace_id"),
                payload.get("reflection_trace_id"),
                payload.get("msg_id"),
            }
            return proposal_id in {str(c) for c in candidates if c is not None}

        for collection in (store.event_history, store.agent_logs):
            for record in collection:
                if str(record.get("log_type", "")).lower() == "proposal" and _matches(record):
                    payload = _as_dict(record.get("payload"))
                    payload["status"] = status
                    record["payload"] = payload
                    updated = True
        return updated

    async def db_snapshot_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_dashboard_snapshot()

    async def db_state_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_raw_snapshot()

    async def db_orders_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_order_metrics()

    async def db_pnl_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_pnl_metrics()

    async def db_agents_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_agent_metrics()

    async def db_trade_feed_payload(
        self, session: Any, limit: int, session_id: str | None
    ) -> dict[str, Any]:
        return await MetricsAggregator(session).get_trade_feed(limit=limit, session_id=session_id)

    async def db_system_metrics_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_system_metrics()

    async def db_positions_payload(self, session: Any) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_raw_snapshot()
        positions = snapshot.get("positions", [])
        return {
            "positions": positions,
            "count": len(positions),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_portfolio_payload(self, session: Any) -> dict[str, Any]:
        pnl = await MetricsAggregator(session).get_paired_pnl(redis_client=None)
        return {
            "portfolio": pnl.get("summary", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_lifecycle_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_trade_feed(limit=50, session_id=None)

    async def db_agent_runs_payload(self, session: Any) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_agent_metrics()
        runs = snapshot.get("runs", [])
        return {
            "runs": runs,
            "count": len(runs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_notifications_payload(self, session: Any) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_raw_snapshot()
        notifications = snapshot.get("notifications", [])
        return {
            "notifications": notifications,
            "count": len(notifications),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_learning_grades_payload(self, session: Any, limit: int) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_raw_snapshot()
        grades = list(reversed((snapshot.get("learning_events") or [])[-limit:]))
        return {
            "grades": grades,
            "total": len(grades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_learning_ic_weights_payload(self, session: Any) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_raw_snapshot()
        return {
            "current_weights": snapshot.get("ic_weights", {}),
            "history": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_learning_proposals_payload(self, session: Any, limit: int) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_raw_snapshot()
        proposals = list(reversed((snapshot.get("proposals") or [])[-limit:]))
        return {
            "proposals": proposals,
            "total": len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_learning_reflections_payload(self, session: Any, limit: int) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_raw_snapshot()
        reflections = [
            row
            for row in reversed(snapshot.get("agent_logs", [])[-200:])
            if str(row.get("log_type", "")).lower() == "reflection"
        ][:limit]
        return {
            "reflections": reflections,
            "total": len(reflections),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def db_learning_loop_payload(self, session: Any) -> dict[str, Any]:
        snapshot = await MetricsAggregator(session).get_raw_snapshot()
        proposals = snapshot.get("proposals", [])
        latest_grade = (snapshot.get("learning_events") or [None])[-1]
        return {
            "latest_grade": latest_grade,
            "recent_proposals": proposals[-20:],
            "loss_attribution": [],
            "control_plane": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def runtime_snapshot_payload(self) -> dict[str, Any]:
        return get_runtime_store().dashboard_fallback_snapshot()

    def runtime_state_payload(self) -> dict[str, Any]:
        payload = get_runtime_store().dashboard_fallback_snapshot()
        payload["mode"] = "in_memory"
        return payload

    def runtime_orders_payload(self) -> dict[str, Any]:
        store = get_runtime_store()
        return {
            "orders": list(reversed(store.orders[-50:])),
            "total_orders": len(store.orders),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_pnl_payload(self) -> dict[str, Any]:
        store = get_runtime_store()
        orders = list(store.orders)
        total_pnl = sum(float(order.get(FieldName.PNL) or 0.0) for order in orders)
        return {
            "pnl": orders[-100:],
            "total_pnl": round(total_pnl, 2),
            "winning_trades": sum(1 for o in orders if float(o.get(FieldName.PNL) or 0.0) > 0),
            "losing_trades": sum(1 for o in orders if float(o.get(FieldName.PNL) or 0.0) < 0),
            "win_rate": round(
                (sum(1 for o in orders if float(o.get(FieldName.PNL) or 0.0) > 0) / len(orders))
                if orders
                else 0.0,
                4,
            ),
            "active_positions": len(store.open_positions()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_agents_payload(self) -> dict[str, Any]:
        store = get_runtime_store()
        return {
            "agents": [{"name": name, **(store.get_agent(name) or {})} for name in ALL_AGENT_NAMES],
            "runs": store.agent_runs[-50:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_trade_feed_payload(self, limit: int) -> dict[str, Any]:
        trades = list(reversed(get_runtime_store().trade_feed[-max(1, min(limit, 200)) :]))
        return {
            "trades": trades,
            "count": len(trades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def runtime_prices_payload(self) -> dict[str, Any]:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
        redis_client = await get_redis()
        keys = [REDIS_KEY_PRICES.format(symbol=symbol) for symbol in symbols]
        cached_values = await redis_client.mget(keys)
        prices = {}
        for symbol, cached_value in zip(symbols, cached_values, strict=False):
            prices[symbol] = cached_value
        return {
            "prices": prices,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "redis_cache",
        }

    def runtime_system_metrics_payload(self) -> dict[str, Any]:
        store = get_runtime_store()
        return {
            "market_events": len(store.event_history),
            "signals": len([e for e in store.event_history if e.get("stream") == STREAM_SIGNALS]),
            "decisions": len(store.orders),
            "graded_decisions": len(store.grade_history),
            "agent_logs": len(store.agent_logs),
            "trade_alerts": len(store.notifications),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def runtime_system_metrics_stream_payload(self) -> dict[str, Any]:
        redis_client = await get_redis()
        streams = {
            "market_events": STREAM_MARKET_EVENTS,
            "signals": STREAM_SIGNALS,
            "decisions": STREAM_DECISIONS,
            "graded_decisions": STREAM_GRADED_DECISIONS,
        }
        result = {key: await redis_client.xlen(stream_name) for key, stream_name in streams.items()}
        result["agent_logs"] = len(get_runtime_store().agent_logs)
        result["trade_alerts"] = len(get_runtime_store().notifications)
        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        result["source"] = "runtime"
        return result

    def runtime_positions_payload(self) -> dict[str, Any]:
        positions = get_runtime_store().open_positions()
        return {
            "positions": positions,
            "count": len(positions),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_portfolio_payload(self) -> dict[str, Any]:
        payload = get_runtime_store().paired_pnl_payload()
        return {
            "portfolio": payload.get("summary", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_lifecycle_payload(self) -> dict[str, Any]:
        return self.runtime_trade_feed_payload(limit=50)

    def runtime_agent_runs_payload(self) -> dict[str, Any]:
        runs = list(reversed(get_runtime_store().agent_runs[-50:]))
        return {
            "runs": runs,
            "count": len(runs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_notifications_payload(self) -> dict[str, Any]:
        notifications = list(reversed(get_runtime_store().notifications[-50:]))
        return {
            "notifications": notifications,
            "count": len(notifications),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_learning_grades_payload(self, limit: int) -> dict[str, Any]:
        grades = get_runtime_store().get_grades(limit=limit)
        return {
            "grades": grades,
            "total": len(grades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_learning_ic_weights_payload(self) -> dict[str, Any]:
        return {
            "current_weights": {},
            "history": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_learning_proposals_payload(self, limit: int) -> dict[str, Any]:
        rows = [
            e
            for e in get_runtime_store().get_events(limit=200)
            if str(e.get("log_type", "")).lower() == "proposal"
        ][:limit]
        return {
            "proposals": rows,
            "total": len(rows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_learning_reflections_payload(self, limit: int) -> dict[str, Any]:
        rows = [
            e
            for e in get_runtime_store().agent_logs[-200:]
            if str(e.get("log_type", "")).lower() == "reflection"
        ]
        reflections = list(reversed(rows))[:limit]
        return {
            "reflections": reflections,
            "total": len(reflections),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def runtime_learning_loop_payload(self) -> dict[str, Any]:
        return {
            "latest_grade": (
                get_runtime_store().grade_history[-1] if get_runtime_store().grade_history else None
            ),
            "recent_proposals": [
                e
                for e in get_runtime_store().event_history
                if str(e.get("log_type", "")).lower() == "proposal"
            ][-20:],
            "loss_attribution": [],
            "control_plane": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_orders_payload(self) -> dict[str, Any]:
        return {
            "orders": [],
            "total_orders": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_trade_feed_payload(self) -> dict[str, Any]:
        return {
            "trades": [],
            "count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_snapshot_payload(self) -> dict[str, Any]:
        return self.runtime_snapshot_payload()

    def empty_state_payload(self) -> dict[str, Any]:
        return self.runtime_state_payload()

    def empty_pnl_payload(self) -> dict[str, Any]:
        return self.runtime_pnl_payload()

    def empty_agents_payload(self) -> dict[str, Any]:
        return self.runtime_agents_payload()

    def empty_system_metrics_payload(self) -> dict[str, Any]:
        return self.runtime_system_metrics_payload()

    def empty_prices_payload(self) -> dict[str, Any]:
        return {
            "prices": dict.fromkeys(["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_positions_payload(self) -> dict[str, Any]:
        return {
            "positions": [],
            "count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_portfolio_payload(self) -> dict[str, Any]:
        return {
            "portfolio": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_lifecycle_payload(self) -> dict[str, Any]:
        return self.empty_trade_feed_payload()

    def empty_agent_runs_payload(self) -> dict[str, Any]:
        return {
            "runs": [],
            "count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_notifications_payload(self) -> dict[str, Any]:
        return {
            "notifications": [],
            "count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_learning_grades_payload(self) -> dict[str, Any]:
        return {
            "grades": [],
            "total": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_learning_ic_weights_payload(self) -> dict[str, Any]:
        return {
            "current_weights": {},
            "history": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_learning_proposals_payload(self) -> dict[str, Any]:
        return {
            "proposals": [],
            "total": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_learning_reflections_payload(self) -> dict[str, Any]:
        return {
            "reflections": [],
            "total": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_learning_loop_payload(self) -> dict[str, Any]:
        return {
            "latest_grade": None,
            "recent_proposals": [],
            "loss_attribution": [],
            "control_plane": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_paired_pnl_payload(self, session: Any, redis_client: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_paired_pnl(redis_client=redis_client)

    def runtime_paired_pnl_payload(self) -> dict[str, Any]:
        payload = get_runtime_store().paired_pnl_payload()
        return {
            "closed_trades": payload["closed_trades"],
            "open_positions": payload["open_positions"],
            "summary": payload["summary"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_paired_pnl_payload(self) -> dict[str, Any]:
        return {
            "closed_trades": [],
            "open_positions": [],
            "summary": {
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "total_pnl": 0.0,
                "closed_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "open_positions": 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_agents_status_payload(self) -> dict[str, Any]:
        redis_client = await get_redis()
        now = int(datetime.now(timezone.utc).timestamp())
        agents = []
        for name in ALL_AGENT_NAMES:
            raw = await redis_client.get(f"agent:status:{name}")
            if not raw:
                agents.append(
                    {
                        "name": name,
                        "status": "WAITING",
                        "event_count": 0,
                        "last_event": "",
                        "last_seen": 0,
                        "last_seen_at": None,
                        "seconds_ago": 0,
                    }
                )
                continue
            data = json.loads(raw)
            last_seen = int(data.get("last_seen", 0) or 0)
            agents.append(
                {
                    "name": name,
                    "status": data.get("status", "ACTIVE"),
                    "event_count": data.get("event_count", 0),
                    "last_event": data.get("last_event", ""),
                    "last_seen": last_seen,
                    "last_seen_at": datetime.fromtimestamp(last_seen, tz=timezone.utc).isoformat()
                    if last_seen
                    else None,
                    "seconds_ago": now - last_seen if last_seen else 0,
                }
            )
        return {
            "agents": agents,
            "pipeline_health": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def runtime_agents_status_payload(self) -> dict[str, Any]:
        store = get_runtime_store()
        now = int(datetime.now(timezone.utc).timestamp())
        agents = [
            {
                "name": name,
                "status": (store.get_agent(name) or {}).get("status", "WAITING"),
                "event_count": (store.get_agent(name) or {}).get("event_count", 0),
                "last_event": (store.get_agent(name) or {}).get("last_event", ""),
                "last_seen": (store.get_agent(name) or {}).get("last_seen", 0),
                "seconds_ago": now
                - int((store.get_agent(name) or {}).get("last_seen", now) or now),
            }
            for name in ALL_AGENT_NAMES
        ]
        return {
            "agents": agents,
            "degraded_mode": True,
            "degraded_reason": "redis_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_agents_status_payload(self) -> dict[str, Any]:
        return {
            "agents": [],
            "pipeline_health": {},
            "degraded_mode": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_recent_events_payload(self, session: Any) -> dict[str, Any]:
        result = await session.execute(
            text(
                """
                SELECT id, event_type, entity_type, source, created_at
                FROM events
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        )
        events = [
            {
                "id": str(row[0]),
                "event_type": row[1],
                "entity_type": row[2],
                "source": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
            }
            for row in result.all()
        ]
        return {"events": events, "timestamp": datetime.now(timezone.utc).isoformat()}

    def runtime_recent_events_payload(self) -> dict[str, Any]:
        return {
            "events": get_runtime_store().get_events(limit=10),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_recent_events_payload(self) -> dict[str, Any]:
        return {
            "events": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_event_history_payload(self, session: Any, limit: int) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 200))
        result = await session.execute(
            text(
                """
                SELECT id, event_type, entity_type, source, created_at
                FROM events
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        )
        events = [
            {
                "id": str(row[0]),
                "event_type": row[1],
                "entity_type": row[2],
                "source": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
            }
            for row in result.all()
        ]
        return {
            "stream_counts": [],
            "persisted_events": events,
            "persisted_logs": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def runtime_event_history_payload(self, limit: int) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 200))
        return {
            "stream_counts": [],
            "persisted_events": get_runtime_store().get_events(limit=safe_limit),
            "persisted_logs": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_event_history_payload(self) -> dict[str, Any]:
        return {
            "stream_counts": [],
            "persisted_events": [],
            "persisted_logs": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_trace_payload(self, session: Any, trace_id: str) -> dict[str, Any]:
        return {"trace_id": trace_id, "agent_runs": [], "agent_logs": [], "agent_grades": []}

    def runtime_trace_payload(self, trace_id: str) -> dict[str, Any]:
        store = get_runtime_store()
        return {
            "trace_id": trace_id,
            "agent_runs": [r for r in store.agent_runs if str(r.get("trace_id", "")) == trace_id],
            "agent_logs": [r for r in store.agent_logs if str(r.get("trace_id", "")) == trace_id],
            "agent_grades": [
                r for r in store.grade_history if str(r.get("trace_id", "")) == trace_id
            ],
            "source": "in_memory",
        }

    def empty_trace_payload(self, trace_id: str) -> dict[str, Any]:
        return {
            "trace_id": trace_id,
            "agent_runs": [],
            "agent_logs": [],
            "agent_grades": [],
            "source": "in_memory",
        }

    async def db_performance_trends_payload(self, session: Any) -> dict[str, Any]:
        return {
            "summary": {"total_trades": 0},
            "daily_pnl": [],
            "grade_trend": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def runtime_performance_trends_payload(self) -> dict[str, Any]:
        return {
            "summary": {"total_trades": len(get_runtime_store().orders)},
            "daily_pnl": [],
            "grade_trend": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_performance_trends_payload(self) -> dict[str, Any]:
        return {
            "summary": {"total_trades": 0},
            "daily_pnl": [],
            "grade_trend": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_agent_instances_payload(self, session: Any) -> dict[str, Any]:
        return {
            "instances": [],
            "active_count": 0,
            "retired_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def runtime_agent_instances_payload(self) -> dict[str, Any]:
        return {
            "instances": [],
            "active_count": 0,
            "retired_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_agent_instances_payload(self) -> dict[str, Any]:
        return {
            "instances": [],
            "active_count": 0,
            "retired_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_stream_lag_payload(self, session: Any) -> dict[str, Any]:
        lag_metrics = await MetricsAggregator(session).get_stream_lag_metrics()
        return {"stream_lag": lag_metrics, "timestamp": datetime.now(timezone.utc).isoformat()}

    def runtime_stream_lag_payload(self) -> dict[str, Any]:
        return {
            "stream_lag": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_stream_lag_payload(self) -> dict[str, Any]:
        return {
            "stream_lag": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_system_health_payload(self, session: Any) -> dict[str, Any]:
        return await MetricsAggregator(session).get_system_health()

    async def runtime_system_health_payload(self) -> dict[str, Any]:
        return await MetricsAggregator(None, use_memory_store=True).get_system_health()

    def empty_system_health_payload(self) -> dict[str, Any]:
        store = get_runtime_store()
        return {
            "status": "degraded",
            "mode": "in_memory",
            "db_health": store.last_health,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_flow_status_payload(self, session: Any) -> dict[str, Any]:
        counts_sql = text(
            """
            SELECT
                (SELECT COUNT(*) FROM agent_runs) AS agent_runs,
                (SELECT COUNT(*) FROM agent_logs) AS agent_logs,
                (SELECT COUNT(*) FROM agent_grades) AS agent_grades,
                (SELECT COUNT(*) FROM orders) AS orders,
                (SELECT COUNT(*) FROM trade_lifecycle) AS trade_lifecycle
            """
        )
        counts_row = (await session.execute(counts_sql)).mappings().first() or {}
        counts = {k: int(v or 0) for k, v in dict(counts_row).items()}
        return {
            "api_version": "2.0",
            "db_schema_version": "v2",
            "degraded_mode": False,
            "counts": counts,
            "realtime_event_count": counts.get("agent_runs", 0),
            "persisted_event_count": counts.get("agent_logs", 0),
            "trace_coverage": {"trace_id": None},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def runtime_flow_status_payload(self) -> dict[str, Any]:
        store = get_runtime_store()
        mem_runs = len(store.agent_runs)
        return {
            "api_version": "2.0",
            "db_schema_version": "v2",
            "degraded_mode": True,
            "degraded_reason": "db_unavailable",
            "counts": {
                "agent_runs": mem_runs,
                "agent_logs": len(store.event_history),
                "agent_grades": len(store.grade_history),
                "orders": 0,
                "trade_lifecycle": 0,
            },
            "realtime_event_count": mem_runs,
            "persisted_event_count": 0,
            "trace_coverage": {"trace_id": None},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_flow_status_payload(self) -> dict[str, Any]:
        return self.runtime_flow_status_payload()

    async def db_challengers_payload(self, _request: Any) -> dict[str, Any]:
        return {"challengers": [], "timestamp": datetime.now(timezone.utc).isoformat()}

    def runtime_challengers_payload(self) -> dict[str, Any]:
        return {
            "challengers": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_challengers_payload(self) -> dict[str, Any]:
        return {
            "challengers": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    async def db_proposals_panel_payload(self, session: Any) -> dict[str, Any]:
        result = await session.execute(
            text(
                """
                SELECT trace_id, payload, created_at
                FROM agent_logs
                WHERE log_type = :log_type
                ORDER BY created_at DESC
                LIMIT 20
                """
            ),
            {"log_type": "proposal"},
        )
        proposals = []
        for row in result.all():
            payload = row[1] if isinstance(row[1], dict) else {}
            proposals.append(
                {
                    "id": str(row[0]),
                    "symbol": payload.get("symbol"),
                    "action": payload.get("action"),
                    "grade_score": payload.get("grade_score"),
                    "bias": payload.get("bias"),
                    "buys": payload.get("buys"),
                    "sells": payload.get("sells"),
                    "strategy_name": payload.get("strategy_name"),
                    "trace_id": row[0],
                    "created_at": row[2].isoformat() if row[2] else None,
                    "source": "agent_logs",
                    "status": payload.get("status", "pending"),
                }
            )
        return {"proposals": proposals, "timestamp": datetime.now(timezone.utc).isoformat()}

    def runtime_proposals_panel_payload(self) -> dict[str, Any]:
        return {
            "proposals": get_runtime_store().get_events(limit=20),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    def empty_proposals_panel_payload(self) -> dict[str, Any]:
        return {
            "proposals": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }
