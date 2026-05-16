"""LLM health endpoint — exposes live call metrics from the in-memory collector."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from api.config import settings
from api.constants import LLM_METRICS_WINDOW_SECONDS, FieldName
from api.services.llm_metrics import llm_metrics
from api.services.redis_store import get_redis_store

router = APIRouter(tags=["llm"])


def _llm_status(success_rate_pct: float, total_in_window: int) -> str:
    if total_in_window == 0:
        return "unknown"
    if success_rate_pct >= 80:
        return "live"
    if success_rate_pct >= 50:
        return "degraded"
    return "down"


@router.get("/llm/health")
async def llm_health() -> dict[str, Any]:
    """Return current LLM call metrics over the last 5-minute window."""
    snap = llm_metrics.snapshot(window_seconds=LLM_METRICS_WINDOW_SECONDS)
    status = _llm_status(snap[FieldName.SUCCESS_RATE_PCT], snap[FieldName.TOTAL_IN_WINDOW])

    provider = getattr(settings, "LLM_PROVIDER", "unknown").lower()
    _model_setting = {
        "gemini": ("GEMINI_MODEL", settings.GEMINI_MODEL),
        "groq": ("GROQ_MODEL", "unknown"),
        "anthropic": ("ANTHROPIC_MODEL", "unknown"),
        "openai": ("OPENAI_MODEL", "unknown"),
    }
    _attr, _default = _model_setting.get(provider, ("", "unknown"))
    model_name: str = getattr(settings, _attr, _default) if _attr else "unknown"

    # Surface the durable Redis counters so the dashboard's LLM card shows
    # totals that survive a backend restart (the in-process ring buffer alone
    # resets to zero on every redeploy).
    redis_metrics: dict[str, Any] = {}
    store = get_redis_store()
    if store is not None:
        redis_metrics = await store.get_llm_metrics()

    # Merge the durable Redis counters into the fields the existing UI reads
    # (`total_calls_lifetime`, `daily_calls`). The in-process snapshot keeps
    # owning the window-bounded fields (`success_rate_pct`, `recent_results`,
    # etc.); we only override when the durable Redis value is strictly larger,
    # which is exactly the "in-process counter was reset by a restart" case.
    snap_total = int(snap.get(FieldName.TOTAL_CALLS_LIFETIME) or 0)
    redis_total = int(redis_metrics.get(FieldName.TOTAL_CALLS) or 0)
    if redis_total > snap_total:
        snap[FieldName.TOTAL_CALLS_LIFETIME] = redis_total

    snap_daily = int(snap.get(FieldName.DAILY_CALLS) or 0)
    redis_daily = int(redis_metrics.get(FieldName.DAILY_CALLS) or 0)
    if redis_daily > snap_daily:
        snap[FieldName.DAILY_CALLS] = redis_daily

    return {
        FieldName.STATUS: status,
        FieldName.PROVIDER: provider,
        FieldName.MODEL: model_name,
        FieldName.MODEL_VAR: _attr if _attr else "unknown",
        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        FieldName.REDIS_METRICS: redis_metrics,
        **snap,
    }
