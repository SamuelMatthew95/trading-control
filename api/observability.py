from __future__ import annotations

import contextvars
import logging
from datetime import datetime
from typing import Any, Dict

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

metrics_store: Dict[str, Any] = {
    "requests_total": 0,
    "errors_total": 0,
    "startup_at": None,
}


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    if metrics_store["startup_at"] is None:
        metrics_store["startup_at"] = datetime.utcnow().isoformat()


def log_structured(event: str, **fields: Any) -> None:
    logger = logging.getLogger("api.observability")
    payload = {"event": event, "request_id": request_id_ctx.get(), **fields}
    logger.info(payload)
