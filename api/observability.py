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

from api.constants import FieldName

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="unknown")


def configure_logging(level: str = "INFO") -> None:
    if structlog.is_configured():
        return

    # Circular-import break: telemetry imports log_structured from this module.
    from api.telemetry import otel_log_processor  # noqa: PLC0415

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
            # Stamps otel_trace_id / otel_span_id when a span is active (no-op
            # while telemetry is disabled) — log↔trace correlation in SigNoz.
            otel_log_processor,
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
                    FieldName.EVENT_TYPE: event_type,
                    FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                    FieldName.REQUEST_ID: request_id_ctx.get(),
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
                FieldName.NAME: name,
                FieldName.STATUS: status,
                FieldName.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
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
                FieldName.UPTIME_SECONDS: int(time.time() - START_TIME),
                FieldName.TOTAL_REQUESTS: self.total_requests,
                FieldName.TOTAL_ERRORS: self.total_errors,
                FieldName.ERROR_RATE: (
                    round((self.total_errors / self.total_requests) * 100, 2)
                    if self.total_requests
                    else 0
                ),
                FieldName.AVG_LATENCY_MS: avg_latency,
                FieldName.P95_LATENCY_MS: p95,
                FieldName.AGENT_STATUS: list(self.agent_status.values()),
                FieldName.RECENT_EVENTS: list(self.recent_events)[:100],
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

    if FieldName.EVENT in extra_data:
        extra_data.pop(FieldName.EVENT)

    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message, **extra_data)
