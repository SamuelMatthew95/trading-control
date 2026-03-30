"""Structured logging and in-memory observability primitives."""

from __future__ import annotations

import logging
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import structlog

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="unknown")


def configure_logging(level: str = "INFO") -> None:
    if structlog.is_configured():
        return

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
    ]

    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")
    structlog.configure(
        processors=[
            *pre_chain,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger("trading-control")


@dataclass
class MetricsStore:
    recent_events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=300))
    request_latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    total_requests: int = 0
    total_errors: int = 0
    agent_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def log_event(self, event_type: str, **data: Any) -> None:
        with self._lock:
            self.recent_events.appendleft(
                {
                    "event_type": event_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "request_id": request_id_ctx.get(),
                    **data,
                }
            )

    def register_request(self, latency_ms: float, *, is_error: bool = False) -> None:
        with self._lock:
            self.total_requests += 1
            self.request_latencies_ms.append(latency_ms)
            if is_error:
                self.total_errors += 1

    def update_agent(self, name: str, status: str, **data: Any) -> None:
        with self._lock:
            self.agent_status[name] = {
                "name": name,
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                **data,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latency = list(self.request_latencies_ms)
            avg_latency = round(sum(latency) / len(latency), 2) if latency else 0.0
            p95 = (
                round(sorted(latency)[max(int(len(latency) * 0.95) - 1, 0)], 2) if latency else 0.0
            )
            return {
                "uptime_seconds": int(time.time() - START_TIME),
                "total_requests": self.total_requests,
                "total_errors": self.total_errors,
                "error_rate": (
                    round((self.total_errors / self.total_requests) * 100, 2)
                    if self.total_requests
                    else 0
                ),
                "avg_latency_ms": avg_latency,
                "p95_latency_ms": p95,
                "agent_status": list(self.agent_status.values()),
                "recent_events": list(self.recent_events)[:100],
            }


START_TIME = time.time()
metrics_store = MetricsStore()


# Valid log levels for validation
VALID_LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}


def bind_request_context(request_id: str) -> None:
    structlog.contextvars.bind_contextvars(request_id=request_id)


def log_structured(level: str, message: str, **extra_data: Any) -> None:
    if level.lower() not in {
        "debug",
        "info",
        "warning",
        "error",
        "exception",
        "critical",
    }:
        level = "info"

    if "event" in extra_data:
        extra_data.pop("event")

    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message, **extra_data)
