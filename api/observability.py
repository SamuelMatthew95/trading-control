"""Structured logging and in-memory observability primitives."""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="unknown")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_ctx.get()),
        }
        extra = getattr(record, "extra_data", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return

    log_handler = logging.StreamHandler()
    log_handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(log_handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


logger = logging.getLogger("trading-control")


@dataclass
class MetricsStore:
    recent_events: Deque[Dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=300)
    )
    request_latencies_ms: Deque[float] = field(
        default_factory=lambda: deque(maxlen=500)
    )
    total_requests: int = 0
    total_errors: int = 0
    agent_status: Dict[str, Dict[str, Any]] = field(default_factory=dict)
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

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            latency = list(self.request_latencies_ms)
            avg_latency = round(sum(latency) / len(latency), 2) if latency else 0.0
            p95 = (
                round(sorted(latency)[max(int(len(latency) * 0.95) - 1, 0)], 2)
                if latency
                else 0.0
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


def log_structured(level: str, message: str, **extra_data: Any) -> None:
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(
        message, extra={"extra_data": extra_data, "request_id": request_id_ctx.get()}
    )
