import json
import time
from typing import Any

from fastapi import HTTPException

from api.config import settings
from api.constants import (
    ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_PRICES,
    FieldName,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available, runtime_mode
from api.services.metrics_aggregator import MetricsAggregator
from api.services.redis_store import get_redis_store


async def hydrate_dashboard_state_from_redis() -> dict[str, Any]:
    """Hydrate runtime ledger from Redis decisions/notifications in DB-down mode."""
    store = get_runtime_store()
    diagnostics: dict[str, Any] = {
        FieldName.SOURCE: "in_memory",
        FieldName.HYDRATION_STATUS: "skipped",
        FieldName.PERSISTENCE_SOURCE: "memory_only",
        FieldName.LEDGER_SOURCE: "runtime_store",
        FieldName.REDIS_DECISIONS_SEEN: 0,
        FieldName.REDIS_NOTIFICATIONS_SEEN: 0,
        FieldName.REDIS_DECISIONS_APPLIED: 0,
        FieldName.REDIS_NOTIFICATIONS_APPLIED: 0,
        FieldName.APPLIED_DECISION_KEYS: len(store.applied_decision_keys),
        FieldName.LAST_ERROR: None,
    }
    if is_db_available():
        diagnostics[FieldName.PERSISTENCE_SOURCE] = "postgres"
        return diagnostics

    redis_store = get_redis_store()
    if redis_store is None:
        return diagnostics

    try:
        diagnostics[FieldName.HYDRATION_STATUS] = "attempted"
        decisions = await redis_store.list_decisions(limit=500)
        diagnostics[FieldName.REDIS_DECISIONS_SEEN] = len(decisions)
        decisions_before = len(store.applied_decision_keys)
        for decision in reversed(decisions):
            # Redis ``decisions:recent`` is advisory output from ReasoningAgent.
            # Replaying it as executed fills creates phantom positions/PnL.
            # Hydrate via advisory path only; portfolio mutation must come from
            # execution/fill sources.
            store.record_decision(decision)
        diagnostics[FieldName.REDIS_DECISIONS_APPLIED] = max(
            0, len(store.applied_decision_keys) - decisions_before
        )

        notifications = await redis_store.list_notifications(limit=500)
        diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN] = len(notifications)
        notifications_before = len(store.notifications)

        def _notification_key(item: dict[str, Any]) -> str:
            notif_id = str(
                item.get(FieldName.ID) or item.get(FieldName.NOTIFICATION_ID) or ""
            ).strip()
            if notif_id:
                return f"id:{notif_id}"
            trace_id = str(item.get(FieldName.TRACE_ID) or "").strip()
            notif_type = str(
                item.get(FieldName.TYPE) or item.get(FieldName.NOTIFICATION_TYPE) or ""
            ).strip()
            action = str(item.get(FieldName.ACTION) or "").strip().upper()
            symbol = str(item.get(FieldName.SYMBOL) or "").strip().upper()
            title = str(item.get(FieldName.TITLE) or "").strip()
            body = str(item.get(FieldName.BODY) or item.get(FieldName.MESSAGE) or "").strip()
            stable = "|".join([trace_id, notif_type, action, symbol, title, body])
            if stable.strip("|"):
                return f"stable:{stable}"
            return f"raw:{json.dumps(item, sort_keys=True, default=str)}"

        existing_notification_keys = {_notification_key(item) for item in store.notifications}
        for notification in reversed(notifications):
            notification_key = _notification_key(notification)
            if notification_key in existing_notification_keys:
                continue
            store.record_notification(notification)
            existing_notification_keys.add(notification_key)
        diagnostics[FieldName.REDIS_NOTIFICATIONS_APPLIED] = max(
            0, len(store.notifications) - notifications_before
        )

        diagnostics[FieldName.APPLIED_DECISION_KEYS] = len(store.applied_decision_keys)
        if (
            diagnostics[FieldName.REDIS_DECISIONS_SEEN] > 0
            or diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN] > 0
        ):
            diagnostics[FieldName.SOURCE] = "redis_hydrated"
            diagnostics[FieldName.PERSISTENCE_SOURCE] = "redis"
        diagnostics[FieldName.HYDRATION_STATUS] = "completed"
    except Exception as exc:
        diagnostics[FieldName.HYDRATION_STATUS] = "failed"
        diagnostics[FieldName.LAST_ERROR] = str(exc)
        log_structured("warning", "dashboard_redis_hydration_failed", exc_info=True)

    return diagnostics


def _attach_runtime_hydration_metadata(
    payload: dict[str, Any], diagnostics: dict[str, Any]
) -> dict[str, Any]:
    """Attach consistent hydration/source metadata to runtime payloads."""
    payload[FieldName.SOURCE] = diagnostics[FieldName.SOURCE]
    payload[FieldName.LEDGER_SOURCE] = diagnostics[FieldName.LEDGER_SOURCE]
    payload[FieldName.PERSISTENCE_SOURCE] = diagnostics[FieldName.PERSISTENCE_SOURCE]
    payload[FieldName.HYDRATION] = {
        "status": diagnostics[FieldName.HYDRATION_STATUS],
        FieldName.REDIS_DECISIONS_SEEN: diagnostics[FieldName.REDIS_DECISIONS_SEEN],
        FieldName.REDIS_DECISIONS_APPLIED: diagnostics[FieldName.REDIS_DECISIONS_APPLIED],
        FieldName.REDIS_NOTIFICATIONS_SEEN: diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN],
        FieldName.REDIS_NOTIFICATIONS_APPLIED: diagnostics[FieldName.REDIS_NOTIFICATIONS_APPLIED],
        FieldName.APPLIED_DECISION_KEYS: diagnostics[FieldName.APPLIED_DECISION_KEYS],
        FieldName.LAST_ERROR: diagnostics[FieldName.LAST_ERROR],
    }
    return payload


async def get_snapshot_payload() -> dict[str, Any]:
    """
    Get complete dashboard snapshot with all metrics.

    This is the primary endpoint for the UI dashboard.
    Returns sanitized data with no NaN values.
    Uses in-memory store directly when the database is unavailable.
    """
    if not is_db_available():
        diagnostics = await hydrate_dashboard_state_from_redis()
        payload = get_runtime_store().dashboard_fallback_snapshot()
        return _attach_runtime_hydration_metadata(payload, diagnostics)
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_dashboard_snapshot()
    except Exception:
        log_structured("warning", "dashboard_snapshot_db_failed", exc_info=True)
        return get_runtime_store().dashboard_fallback_snapshot()


async def get_state_payload() -> dict[str, Any]:
    """
    Get raw dashboard state in the format the frontend expects.

    Returns orders[], positions[], agent_logs[] — same shape as the WebSocket
    dashboard_update snapshot so the UI can hydrate via REST when the WebSocket
    is slow to connect or unavailable.
    """
    try:
        # Route determined once upfront; no silent try/except routing.
        if not is_db_available():
            diagnostics = await hydrate_dashboard_state_from_redis()
            store = get_runtime_store()
            data = store.dashboard_fallback_snapshot()
            data = _attach_runtime_hydration_metadata(data, diagnostics)
            data[FieldName.MODE] = runtime_mode()  # "in_memory_fallback" when DB is unavailable
        else:
            try:
                async with AsyncSessionFactory() as session:
                    aggregator = MetricsAggregator(session)
                    data = await aggregator.get_raw_snapshot()
            except Exception:
                log_structured("warning", "dashboard_state_db_failed", exc_info=True)
                fallback = get_runtime_store().dashboard_fallback_snapshot()
                fallback[FieldName.DEGRADED_MODE] = True
                fallback[FieldName.DEGRADED_REASON] = "db_unavailable"
                return fallback

        # Redis enrichment is best-effort: a Redis outage must not prevent
        # the frontend from receiving its DB-backed hydration data.
        try:
            redis_client = await get_redis()
        except Exception:
            log_structured("warning", "dashboard_state_redis_unavailable", exc_info=True)
            data.setdefault(FieldName.MODE, runtime_mode())
            db_up = is_db_available()
            data[FieldName.DEGRADED_MODE] = True
            data[FieldName.DEGRADED_REASON] = "db_unavailable" if not db_up else "redis_unavailable"
            return data

        # Enrich with current prices from Redis cache
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
        keys = [REDIS_KEY_PRICES.format(symbol=s) for s in symbols]
        try:
            cached_values = await redis_client.mget(keys)
            prices: dict[str, Any] = {}
            for symbol, raw in zip(symbols, cached_values, strict=False):
                if raw:
                    try:
                        prices[symbol] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        pass
            if prices:
                data[FieldName.PRICES] = prices
        except Exception:
            log_structured("warning", "dashboard_state_prices_failed", exc_info=True)

        # Enrich with IC weights from Redis
        try:
            raw_weights = await redis_client.get(REDIS_KEY_IC_WEIGHTS)
            if raw_weights:
                data[FieldName.IC_WEIGHTS] = json.loads(raw_weights)
        except Exception:
            log_structured("warning", "dashboard_state_ic_weights_failed", exc_info=True)

        # Enrich with agent heartbeats from Redis (keys must match what agents write)
        try:
            agent_keys = [REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES]
            agent_values = await redis_client.mget(agent_keys)
            now_ts = time.time()
            agent_statuses: list[dict[str, Any]] = []
            for name, raw in zip(ALL_AGENT_NAMES, agent_values, strict=False):
                if raw:
                    try:
                        status = json.loads(raw)
                        last_seen = float(status.get(FieldName.LAST_SEEN) or 0)
                        seconds_ago = max(0, int(now_ts - last_seen)) if last_seen > 0 else 0
                        agent_statuses.append(
                            {FieldName.NAME: name, FieldName.SECONDS_AGO: seconds_ago, **status}
                        )
                    except (json.JSONDecodeError, TypeError, ValueError):
                        agent_statuses.append({FieldName.NAME: name, FieldName.STATUS: "unknown"})
                else:
                    agent_statuses.append(
                        {
                            FieldName.NAME: name,
                            FieldName.STATUS: "offline",
                            FieldName.SECONDS_AGO: 0,
                        }
                    )
            data[FieldName.AGENT_STATUSES] = agent_statuses
        except Exception:
            log_structured("warning", "dashboard_state_agent_statuses_failed", exc_info=True)

        data.setdefault(FieldName.MODE, runtime_mode())
        db_up = is_db_available()
        data[FieldName.DEGRADED_MODE] = not db_up
        if not db_up:
            data[FieldName.DEGRADED_REASON] = "db_unavailable"
        # Expose whether the configured LLM provider has an API key so the
        # frontend can surface a "rule-based mode" banner instead of silently
        # showing no reasoning decisions.
        provider = settings.LLM_PROVIDER.lower().strip()
        provider_key_map = {
            FieldName.GEMINI: getattr(settings, "GEMINI_API_KEY", None),
            FieldName.ANTHROPIC: getattr(settings, "ANTHROPIC_API_KEY", None),
            FieldName.OPENAI: getattr(settings, "OPENAI_API_KEY", None),
            FieldName.GROQ: getattr(settings, "GROQ_API_KEY", None),
        }
        llm_key = provider_key_map.get(provider) or ""
        data[FieldName.LLM_AVAILABLE] = bool(llm_key and llm_key.strip())
        data[FieldName.LLM_PROVIDER] = provider
        return data

    except Exception:
        log_structured("error", "dashboard state failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
