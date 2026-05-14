"""Redis-backed persistence for notifications, decisions and LLM metrics.

Used when Postgres is unavailable (memory mode). Redis is already a hard
dependency for streams and heartbeats so this just reuses the same connection
to keep small REST-queryable lists around.

Each list is capped via LTRIM so memory usage stays bounded regardless of
how long the system runs without a Postgres restart.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.constants import (
    REDIS_DECISIONS_MAX,
    REDIS_KEY_DECISIONS_RECENT,
    REDIS_KEY_LLM_METRICS,
    REDIS_KEY_NOTIFICATIONS_READ,
    REDIS_KEY_NOTIFICATIONS_RECENT,
    REDIS_NOTIFICATIONS_MAX,
    FieldName,
)
from api.observability import log_structured


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_text(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _safe_loads(raw: Any) -> dict[str, Any] | None:
    try:
        parsed = json.loads(_to_text(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_iso_ts(raw: Any) -> float | None:
    """Best-effort ISO-8601 → Unix epoch seconds. ``None`` for unparseable input."""
    if raw is None:
        return None
    ts_str = str(raw).strip()
    if not ts_str:
        return None
    try:
        ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts_dt.tzinfo is None:
        ts_dt = ts_dt.replace(tzinfo=timezone.utc)
    return ts_dt.timestamp()


class RedisStore:
    """Thin async wrapper around Redis lists/hashes used by REST endpoints."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    # ------------------------------------------------------------------ #
    # Notifications
    # ------------------------------------------------------------------ #

    async def push_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Push a notification to ``notifications:recent`` (LPUSH + LTRIM)."""
        entry = dict(payload)
        # setdefault skips falsy values; explicitly coerce None / empty to a uuid
        # so the REST consumer can rely on a non-empty id for read tracking.
        if not entry.get("id"):
            entry["id"] = str(uuid.uuid4())
        if not entry.get(FieldName.TIMESTAMP):
            entry[FieldName.TIMESTAMP] = _now_iso()
        entry.setdefault("severity", "info")
        entry.setdefault("read", False)
        encoded = json.dumps(entry, default=str)
        try:
            # Atomic LPUSH + LTRIM in a single round trip — keeps the list
            # bounded under concurrent writers without a transient overshoot.
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpush(REDIS_KEY_NOTIFICATIONS_RECENT, encoded)
                pipe.ltrim(REDIS_KEY_NOTIFICATIONS_RECENT, 0, REDIS_NOTIFICATIONS_MAX - 1)
                await pipe.execute()
        except Exception:
            log_structured("warning", "redis_store_notification_push_failed", exc_info=True)

        # Prune ``notifications:read`` so it stays bounded by the live list.
        # Without this, mark-read ids accumulate forever even though the
        # underlying notification was trimmed long ago.
        await self._prune_read_set()
        return entry

    async def _prune_read_set(self) -> None:
        """Drop read-ids that no longer appear in ``notifications:recent``.

        Called on every push so the set is bounded by ~REDIS_NOTIFICATIONS_MAX
        ids rather than growing without limit. Best-effort: any Redis error
        leaves the previous set untouched.
        """
        try:
            live = await self.redis.lrange(REDIS_KEY_NOTIFICATIONS_RECENT, 0, -1)
            live_ids: set[str] = set()
            for raw in live:
                parsed = _safe_loads(raw)
                if parsed is None:
                    continue
                ident = parsed.get("id")
                if ident:
                    live_ids.add(str(ident))

            read_ids_raw = await self.redis.smembers(REDIS_KEY_NOTIFICATIONS_READ)
            stale = [_to_text(item) for item in read_ids_raw if _to_text(item) not in live_ids]
            if stale:
                await self.redis.srem(REDIS_KEY_NOTIFICATIONS_READ, *stale)
        except Exception:
            log_structured("warning", "redis_store_read_set_prune_failed", exc_info=True)

    async def list_notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), REDIS_NOTIFICATIONS_MAX))
        try:
            raw_items = await self.redis.lrange(REDIS_KEY_NOTIFICATIONS_RECENT, 0, safe_limit - 1)
        except Exception:
            log_structured("warning", "redis_store_notification_list_failed", exc_info=True)
            return []
        try:
            read_ids = await self.redis.smembers(REDIS_KEY_NOTIFICATIONS_READ)
        except Exception:
            read_ids = set()
        read_set = {_to_text(item) for item in read_ids or []}

        items: list[dict[str, Any]] = []
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is None:
                continue
            if str(parsed.get("id", "")) in read_set:
                parsed["read"] = True
            items.append(parsed)
        return items

    async def unread_count(self) -> int:
        try:
            raw_items = await self.redis.lrange(REDIS_KEY_NOTIFICATIONS_RECENT, 0, -1)
            read_ids = await self.redis.smembers(REDIS_KEY_NOTIFICATIONS_READ)
        except Exception:
            log_structured("warning", "redis_store_unread_count_failed", exc_info=True)
            return 0
        read_set = {_to_text(item) for item in read_ids or []}
        count = 0
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is None:
                continue
            if parsed.get("read"):
                continue
            if str(parsed.get("id", "")) in read_set:
                continue
            count += 1
        return count

    async def mark_read(self, notification_id: str) -> bool:
        try:
            await self.redis.sadd(REDIS_KEY_NOTIFICATIONS_READ, notification_id)
            return True
        except Exception:
            log_structured("warning", "redis_store_mark_read_failed", exc_info=True)
            return False

    # ------------------------------------------------------------------ #
    # Decisions
    # ------------------------------------------------------------------ #

    async def push_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = dict(payload)
        # Coerce missing or None id/timestamp to deterministic defaults so the
        # REST consumer (and the dedup key on the frontend) can rely on them.
        if not entry.get("id"):
            entry["id"] = str(uuid.uuid4())
        if not entry.get(FieldName.TIMESTAMP):
            entry[FieldName.TIMESTAMP] = _now_iso()
        encoded = json.dumps(entry, default=str)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpush(REDIS_KEY_DECISIONS_RECENT, encoded)
                pipe.ltrim(REDIS_KEY_DECISIONS_RECENT, 0, REDIS_DECISIONS_MAX - 1)
                await pipe.execute()
        except Exception:
            log_structured("warning", "redis_store_decision_push_failed", exc_info=True)
        return entry

    async def list_decisions(
        self, limit: int = 50, action: str | None = None
    ) -> list[dict[str, Any]]:
        # Pull a larger window when filtering so we still hit ``limit`` after the filter.
        fetch_window = (
            REDIS_DECISIONS_MAX if action else max(1, min(int(limit), REDIS_DECISIONS_MAX))
        )
        try:
            raw_items = await self.redis.lrange(REDIS_KEY_DECISIONS_RECENT, 0, fetch_window - 1)
        except Exception:
            log_structured("warning", "redis_store_decision_list_failed", exc_info=True)
            return []
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is None:
                continue
            if action and str(parsed.get(FieldName.ACTION, "")).lower() != action.lower():
                continue
            items.append(parsed)
            if len(items) >= int(limit):
                break
        return items

    async def decision_stats(self) -> dict[str, Any]:
        try:
            raw_items = await self.redis.lrange(REDIS_KEY_DECISIONS_RECENT, 0, -1)
        except Exception:
            log_structured("warning", "redis_store_decision_stats_failed", exc_info=True)
            return {
                "total": 0,
                "last_hour": {"buys": 0, "sells": 0, "holds": 0},
                "last_decision": None,
            }

        now_ts = time.time()
        cutoff = now_ts - 3600.0

        buys = sells = holds = 0
        last_decision: dict[str, Any] | None = None
        total = 0

        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is None:
                continue
            total += 1
            if last_decision is None:
                last_decision = parsed
            ts = _parse_iso_ts(parsed.get(FieldName.TIMESTAMP))
            if ts is None or ts < cutoff:
                # Treat malformed/missing timestamps as "out of window" so we
                # never inflate last-hour counts with rows we can't time-place.
                continue
            act = str(parsed.get(FieldName.ACTION, "")).lower()
            if act == "buy":
                buys += 1
            elif act == "sell":
                sells += 1
            elif act == "hold":
                holds += 1

        return {
            "total": total,
            "last_hour": {"buys": buys, "sells": sells, "holds": holds},
            "last_decision": last_decision,
        }

    # ------------------------------------------------------------------ #
    # LLM metrics — rolling hash counters
    # ------------------------------------------------------------------ #

    _OUTCOME_FIELD: dict[str, str] = {
        "success": "successes",
        "rate_limit": "rate_limits",
        "timeout": "timeouts",
        "error": "errors",
    }

    async def record_llm_call(
        self,
        *,
        outcome: str,
        latency_ms: float | None = None,
    ) -> None:
        """Record one LLM call result.

        ``outcome`` is one of: ``success``, ``rate_limit``, ``timeout``, ``error``.
        Counters are written in a single pipeline so a partial failure can't
        leave totals out of step with the per-outcome buckets.
        """
        outcome_field = self._OUTCOME_FIELD.get(outcome, "errors")
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.hincrby(REDIS_KEY_LLM_METRICS, "total_calls", 1)
                pipe.hincrby(REDIS_KEY_LLM_METRICS, outcome_field, 1)
                if outcome == "success" and latency_ms is not None:
                    pipe.hset(
                        REDIS_KEY_LLM_METRICS,
                        mapping={
                            "last_success_at": _now_iso(),
                            "last_latency_ms": int(latency_ms),
                        },
                    )
                await pipe.execute()
        except Exception:
            log_structured("warning", "redis_store_llm_metric_failed", exc_info=True)

    async def get_llm_metrics(self) -> dict[str, Any]:
        try:
            raw = await self.redis.hgetall(REDIS_KEY_LLM_METRICS)
        except Exception:
            log_structured("warning", "redis_store_llm_metrics_failed", exc_info=True)
            return {}
        if not raw:
            return {}

        # redis-py with decode_responses=True returns strings; coerce anyway
        # so this still works against a raw bytes client (e.g. in unit tests).
        decoded: dict[str, str] = {_to_text(k): _to_text(v) for k, v in raw.items()}

        def _int(key: str) -> int:
            try:
                return int(decoded.get(key, "0"))
            except (TypeError, ValueError):
                return 0

        return {
            "total_calls": _int("total_calls"),
            "successes": _int("successes"),
            "rate_limits": _int("rate_limits"),
            "timeouts": _int("timeouts"),
            "errors": _int("errors"),
            "last_success_at": decoded.get("last_success_at"),
            "last_latency_ms": _int("last_latency_ms"),
        }


_store_singleton: RedisStore | None = None


def get_redis_store() -> RedisStore | None:
    """Return the process-wide RedisStore, or None until ``set_redis_store`` runs."""
    return _store_singleton


def set_redis_store(store: RedisStore | None) -> None:
    """Install (or clear) the process-wide RedisStore. Called once at startup."""
    global _store_singleton
    _store_singleton = store
