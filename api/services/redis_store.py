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
from datetime import date as date_cls
from typing import Any

from redis.asyncio import Redis

from api.constants import (
    AGENT_GRADE_HISTORY_MAX,
    REDIS_CLOSED_TRADES_MAX,
    REDIS_DECISIONS_MAX,
    REDIS_KEY_AGENT_GRADE_HISTORY,
    REDIS_KEY_CLOSED_TRADES_RECENT,
    REDIS_KEY_DECISIONS_RECENT,
    REDIS_KEY_LLM_DAILY_CALLS,
    REDIS_KEY_LLM_METRICS,
    REDIS_KEY_NOTIFICATIONS_READ,
    REDIS_KEY_NOTIFICATIONS_RECENT,
    REDIS_KEY_PROPOSALS_RECENT,
    REDIS_KEY_TOOL_TELEMETRY,
    REDIS_NOTIFICATIONS_MAX,
    REDIS_PROPOSALS_MAX,
    FieldName,
)
from api.observability import log_structured
from api.utils import bytes_to_text, now_iso, parse_iso_timestamp, safe_json_loads


def _today_iso() -> str:
    return date_cls.today().isoformat()


def _safe_loads(raw: Any) -> dict[str, Any] | None:
    """Decode a Redis value to a dict; ``None`` for non-dict / unparseable input."""
    parsed = safe_json_loads(raw)
    return parsed if isinstance(parsed, dict) else None


def _parse_iso_ts(raw: Any) -> float | None:
    """Best-effort ISO-8601 → Unix epoch seconds. ``None`` for unparseable input."""
    return parse_iso_timestamp(raw)


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
        if not entry.get(FieldName.ID):
            entry[FieldName.ID] = str(uuid.uuid4())
        if not entry.get(FieldName.TIMESTAMP):
            entry[FieldName.TIMESTAMP] = now_iso()
        entry.setdefault(FieldName.SEVERITY, "info")
        entry.setdefault(FieldName.READ, False)
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
                ident = parsed.get(FieldName.ID)
                if ident:
                    live_ids.add(str(ident))

            read_ids_raw = await self.redis.smembers(REDIS_KEY_NOTIFICATIONS_READ)
            stale = [
                bytes_to_text(item) for item in read_ids_raw if bytes_to_text(item) not in live_ids
            ]
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
        read_set = {bytes_to_text(item) for item in read_ids or []}

        items: list[dict[str, Any]] = []
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is None:
                continue
            if str(parsed.get(FieldName.ID, "")) in read_set:
                parsed[FieldName.READ] = True
            items.append(parsed)
        return items

    async def unread_count(self) -> int:
        try:
            raw_items = await self.redis.lrange(REDIS_KEY_NOTIFICATIONS_RECENT, 0, -1)
            read_ids = await self.redis.smembers(REDIS_KEY_NOTIFICATIONS_READ)
        except Exception:
            log_structured("warning", "redis_store_unread_count_failed", exc_info=True)
            return 0
        read_set = {bytes_to_text(item) for item in read_ids or []}
        count = 0
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is None:
                continue
            if parsed.get(FieldName.READ):
                continue
            if str(parsed.get(FieldName.ID, "")) in read_set:
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
        if not entry.get(FieldName.ID):
            entry[FieldName.ID] = str(uuid.uuid4())
        if not entry.get(FieldName.TIMESTAMP):
            entry[FieldName.TIMESTAMP] = now_iso()
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
                FieldName.TOTAL: 0,
                FieldName.LAST_HOUR: {FieldName.BUYS: 0, FieldName.SELLS: 0, FieldName.HOLDS: 0},
                FieldName.LAST_DECISION: None,
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
            FieldName.TOTAL: total,
            FieldName.LAST_HOUR: {
                FieldName.BUYS: buys,
                FieldName.SELLS: sells,
                FieldName.HOLDS: holds,
            },
            FieldName.LAST_DECISION: last_decision,
        }

    # ------------------------------------------------------------------ #
    # Closed trades — durable round-trip history behind the header PnL
    # ------------------------------------------------------------------ #

    async def push_closed_trade(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Push one completed round-trip to ``closed_trades:recent`` (LPUSH+LTRIM).

        The PaperBroker's equity (and therefore the header PnL) survives
        restarts in Redis; without this list the trades that produced that PnL
        vanished on every redeploy, leaving a number no visible trade explains.
        """
        entry = dict(payload)
        if not entry.get(FieldName.TIMESTAMP):
            entry[FieldName.TIMESTAMP] = now_iso()
        encoded = json.dumps(entry, default=str)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpush(REDIS_KEY_CLOSED_TRADES_RECENT, encoded)
                pipe.ltrim(REDIS_KEY_CLOSED_TRADES_RECENT, 0, REDIS_CLOSED_TRADES_MAX - 1)
                await pipe.execute()
        except Exception:
            log_structured("warning", "redis_store_closed_trade_push_failed", exc_info=True)
        return entry

    async def list_closed_trades(
        self, limit: int = REDIS_CLOSED_TRADES_MAX
    ) -> list[dict[str, Any]]:
        """Recent closed round-trips, newest first."""
        safe_limit = max(1, min(int(limit), REDIS_CLOSED_TRADES_MAX))
        try:
            raw_items = await self.redis.lrange(REDIS_KEY_CLOSED_TRADES_RECENT, 0, safe_limit - 1)
        except Exception:
            log_structured("warning", "redis_store_closed_trade_list_failed", exc_info=True)
            return []
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is not None:
                items.append(parsed)
        return items

    # ------------------------------------------------------------------ #
    # Proposals — durable mirror of the voteable proposal queue
    # ------------------------------------------------------------------ #

    async def push_proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Push one proposal to ``proposals:recent`` (LPUSH + LTRIM).

        Proposals are published to the STREAM_PROPOSALS event bus, but the
        dashboard reads them from the persisted store. In memory mode that store
        (InMemoryStore.event_history) is wiped on every restart, so without this
        durable mirror the Proposals page emptied on each redeploy. Stores the
        proposal payload verbatim; startup hydration replays it into the store.
        """
        entry = dict(payload)
        if not entry.get(FieldName.TIMESTAMP):
            entry[FieldName.TIMESTAMP] = now_iso()
        encoded = json.dumps(entry, default=str)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpush(REDIS_KEY_PROPOSALS_RECENT, encoded)
                pipe.ltrim(REDIS_KEY_PROPOSALS_RECENT, 0, REDIS_PROPOSALS_MAX - 1)
                await pipe.execute()
        except Exception:
            log_structured("warning", "redis_store_proposal_push_failed", exc_info=True)
        return entry

    async def list_proposals(self, limit: int = REDIS_PROPOSALS_MAX) -> list[dict[str, Any]]:
        """Recent proposals, newest first."""
        safe_limit = max(1, min(int(limit), REDIS_PROPOSALS_MAX))
        try:
            raw_items = await self.redis.lrange(REDIS_KEY_PROPOSALS_RECENT, 0, safe_limit - 1)
        except Exception:
            log_structured("warning", "redis_store_proposal_list_failed", exc_info=True)
            return []
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is not None:
                items.append(parsed)
        return items

    # ------------------------------------------------------------------ #
    # LLM metrics — rolling hash counters
    # ------------------------------------------------------------------ #

    _OUTCOME_FIELD: dict[str, str] = {
        FieldName.SUCCESS: "successes",
        FieldName.RATE_LIMIT: "rate_limits",
        FieldName.TIMEOUT: "timeouts",
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
        leave totals out of step with the per-outcome buckets. We also bump
        the per-day call counter (``llm:daily_calls:{date}``) so ``daily_calls``
        survives a backend restart — the in-process snapshot resets to 0,
        but the dashboard pulls the durable Redis value via /llm/health.
        """
        outcome_field = self._OUTCOME_FIELD.get(outcome, "errors")
        daily_key = REDIS_KEY_LLM_DAILY_CALLS.format(date=_today_iso())
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.hincrby(REDIS_KEY_LLM_METRICS, "total_calls", 1)
                pipe.hincrby(REDIS_KEY_LLM_METRICS, outcome_field, 1)
                pipe.incr(daily_key)
                if outcome == "success" and latency_ms is not None:
                    pipe.hset(
                        REDIS_KEY_LLM_METRICS,
                        mapping={
                            FieldName.LAST_SUCCESS_AT: now_iso(),
                            FieldName.LAST_LATENCY_MS: int(latency_ms),
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

        # ``daily_calls`` lives in its own per-date key — fetch even when the
        # lifetime hash is empty so a fresh-restart day still reports activity.
        daily_calls = await self._daily_call_count()

        if not raw and daily_calls == 0:
            return {}

        # redis-py with decode_responses=True returns strings; coerce anyway
        # so this still works against a raw bytes client (e.g. in unit tests).
        decoded: dict[str, str] = {
            bytes_to_text(k): bytes_to_text(v) for k, v in (raw or {}).items()
        }

        def _int(key: str) -> int:
            try:
                return int(decoded.get(key, "0"))
            except (TypeError, ValueError):
                return 0

        return {
            "total_calls": _int("total_calls"),
            FieldName.SUCCESSES: _int("successes"),
            FieldName.RATE_LIMITS: _int("rate_limits"),
            FieldName.TIMEOUTS: _int("timeouts"),
            FieldName.ERRORS: _int("errors"),
            FieldName.LAST_SUCCESS_AT: decoded.get(FieldName.LAST_SUCCESS_AT),
            FieldName.LAST_LATENCY_MS: _int("last_latency_ms"),
            "daily_calls": daily_calls,
        }

    async def _daily_call_count(self) -> int:
        """Return today's durable LLM call count (``llm:daily_calls:{today}``)."""
        try:
            raw = await self.redis.get(REDIS_KEY_LLM_DAILY_CALLS.format(date=_today_iso()))
        except Exception:
            log_structured("warning", "redis_store_daily_calls_failed", exc_info=True)
            return 0
        if raw is None:
            return 0
        try:
            return int(bytes_to_text(raw))
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------ #
    # Per-agent grade history — durable streak tracking for promotion
    # ------------------------------------------------------------------ #

    async def record_agent_grade(self, agent_name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Append one grade snapshot to ``agent:grade_history:{name}`` (LPUSH+LTRIM).

        Snapshots are deduped/throttled by the caller; this just persists them
        capped at ``AGENT_GRADE_HISTORY_MAX`` so the list stays bounded.
        """
        entry = dict(snapshot)
        if not entry.get(FieldName.TIMESTAMP):
            entry[FieldName.TIMESTAMP] = now_iso()
        key = REDIS_KEY_AGENT_GRADE_HISTORY.format(name=agent_name)
        encoded = json.dumps(entry, default=str)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpush(key, encoded)
                pipe.ltrim(key, 0, AGENT_GRADE_HISTORY_MAX - 1)
                await pipe.execute()
        except Exception:
            log_structured("warning", "redis_store_agent_grade_push_failed", exc_info=True)
        return entry

    async def list_agent_grades(self, agent_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Recent grade snapshots for one agent, newest first."""
        safe_limit = max(1, min(int(limit), AGENT_GRADE_HISTORY_MAX))
        key = REDIS_KEY_AGENT_GRADE_HISTORY.format(name=agent_name)
        try:
            raw_items = await self.redis.lrange(key, 0, safe_limit - 1)
        except Exception:
            log_structured("warning", "redis_store_agent_grade_list_failed", exc_info=True)
            return []
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            parsed = _safe_loads(raw)
            if parsed is not None:
                items.append(parsed)
        return items

    # ------------------------------------------------------------------ #
    # Tool telemetry — durable snapshot of the in-process ToolRegistry
    # ------------------------------------------------------------------ #

    async def save_tool_telemetry(self, snapshot: dict[str, Any]) -> None:
        """Persist the ToolRegistry telemetry snapshot (single JSON blob)."""
        try:
            await self.redis.set(REDIS_KEY_TOOL_TELEMETRY, json.dumps(snapshot, default=str))
        except Exception:
            log_structured("warning", "redis_store_tool_telemetry_save_failed", exc_info=True)

    async def load_tool_telemetry(self) -> dict[str, Any]:
        """Load the persisted ToolRegistry telemetry snapshot ({} if absent)."""
        try:
            raw = await self.redis.get(REDIS_KEY_TOOL_TELEMETRY)
        except Exception:
            log_structured("warning", "redis_store_tool_telemetry_load_failed", exc_info=True)
            return {}
        parsed = _safe_loads(raw) if raw is not None else None
        return parsed or {}


_store_singleton: RedisStore | None = None


def get_redis_store() -> RedisStore | None:
    """Return the process-wide RedisStore, or None until ``set_redis_store`` runs."""
    return _store_singleton


def set_redis_store(store: RedisStore | None) -> None:
    """Install (or clear) the process-wide RedisStore. Called once at startup."""
    global _store_singleton
    _store_singleton = store
