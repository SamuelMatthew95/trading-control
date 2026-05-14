"""In-process LLM call metrics collector."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from threading import Lock

from api.constants import (
    LLM_CALL_DELAY_MS,
    LLM_METRICS_MAX_RECORDS,
    LLM_METRICS_WINDOW_SECONDS,
    LLMCallResult,
)


def _async_fire_and_forget(coro) -> None:
    """Schedule ``coro`` on the running loop without awaiting it.

    Used so synchronous ``record_*`` callers can publish to Redis without
    refactoring every callsite into an async function. If no loop is running
    (rare — record_* is called from the LLM router which is async), the
    coroutine is closed silently so we never leak a warning.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    loop.create_task(coro)


async def _record_redis_outcome(outcome: str, latency_ms: float | None = None) -> None:
    # Imported lazily to avoid a circular import (redis_store imports
    # observability which can transitively pull in this module).
    from api.services.redis_store import get_redis_store

    store = get_redis_store()
    if store is None:
        return
    with suppress(Exception):
        await store.record_llm_call(outcome=outcome, latency_ms=latency_ms)


@dataclass
class CallRecord:
    ts: float = field(default_factory=time.monotonic)
    result: LLMCallResult = LLMCallResult.SUCCESS
    latency_ms: float = 0.0


class LLMMetricsCollector:
    """Thread-safe ring buffer tracking the last N LLM call results."""

    def __init__(self, max_records: int = LLM_METRICS_MAX_RECORDS) -> None:
        self._records: deque[CallRecord] = deque(maxlen=max_records)
        self._lock = Lock()
        self._total_calls: int = 0
        self._daily_calls: int = 0
        self._daily_date: str = ""
        self._dynamic_delay_ms: int | None = None
        self._last_error_message: str | None = None
        self._last_error_kind: str | None = None
        self._last_error_at: str | None = None

    def _today(self) -> str:
        return date.today().isoformat()

    def _refresh_daily_date(self) -> None:
        today = self._today()
        if today != self._daily_date:
            self._daily_date = today
            self._daily_calls = 0

    def _record(self, result: LLMCallResult, latency_ms: float = 0.0) -> None:
        with self._lock:
            self._refresh_daily_date()
            self._records.append(CallRecord(result=result, latency_ms=latency_ms))
            self._total_calls += 1
            self._daily_calls += 1

    def set_call_delay_ms(self, ms: int) -> None:
        """GradeAgent calls this to raise the inter-call delay when rate-limiting occurs."""
        with self._lock:
            self._dynamic_delay_ms = max(0, ms)

    def get_call_delay_ms(self) -> int:
        """Return the active call delay: dynamic value if set, else the compiled default."""
        with self._lock:
            return (
                self._dynamic_delay_ms if self._dynamic_delay_ms is not None else LLM_CALL_DELAY_MS
            )

    def record_success(self, latency_ms: float) -> None:
        self._record(LLMCallResult.SUCCESS, latency_ms)
        _async_fire_and_forget(_record_redis_outcome("success", latency_ms))

    def record_rate_limit(self) -> None:
        self._record(LLMCallResult.RATE_LIMITED)
        _async_fire_and_forget(_record_redis_outcome("rate_limit"))

    def record_timeout(self) -> None:
        self._record(LLMCallResult.TIMEOUT)
        _async_fire_and_forget(_record_redis_outcome("timeout"))

    def record_error(self, *, message: str | None = None, kind: str = "error") -> None:
        self._record(LLMCallResult.ERROR)
        with self._lock:
            self._last_error_kind = kind
            self._last_error_message = (message or "").strip()[:240] or None
            self._last_error_at = datetime.now(timezone.utc).isoformat()
        _async_fire_and_forget(_record_redis_outcome("error"))

    def snapshot(self, window_seconds: int = LLM_METRICS_WINDOW_SECONDS) -> dict:
        """Metrics snapshot for the last *window_seconds* seconds."""
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            self._refresh_daily_date()
            window = [r for r in self._records if r.ts >= cutoff]
            recent_10 = list(self._records)[-10:]
            total_calls = self._total_calls
            daily_calls = self._daily_calls
            effective_delay_ms = (
                self._dynamic_delay_ms if self._dynamic_delay_ms is not None else LLM_CALL_DELAY_MS
            )
            grade_adjusted = self._dynamic_delay_ms is not None
            last_error_kind = self._last_error_kind
            last_error_message = self._last_error_message
            last_error_at = self._last_error_at

        successes = [r for r in window if r.result == LLMCallResult.SUCCESS]
        total_w = len(window)
        success_count = len(successes)

        return {
            "window_seconds": window_seconds,
            "total_in_window": total_w,
            "success_count": success_count,
            "success_rate_pct": round(success_count / total_w * 100, 1) if total_w else 0.0,
            "avg_latency_ms": (
                round(sum(r.latency_ms for r in successes) / success_count) if successes else 0.0
            ),
            "rate_limited_count": sum(1 for r in window if r.result == LLMCallResult.RATE_LIMITED),
            "timeout_count": sum(1 for r in window if r.result == LLMCallResult.TIMEOUT),
            "error_count": sum(1 for r in window if r.result == LLMCallResult.ERROR),
            "total_calls_lifetime": total_calls,
            "daily_calls": daily_calls,
            "effective_delay_ms": effective_delay_ms,
            "grade_adjusted_delay": grade_adjusted,
            "last_error": {
                "kind": last_error_kind,
                "message": last_error_message,
                "at": last_error_at,
            },
            "recent_results": [
                {
                    "result": r.result,
                    "latency_ms": round(r.latency_ms)
                    if r.result == LLMCallResult.SUCCESS
                    else None,
                }
                for r in recent_10
            ],
        }


llm_metrics = LLMMetricsCollector()
