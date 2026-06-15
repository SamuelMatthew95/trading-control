"""LLM health endpoint — exposes live call metrics from the in-memory collector."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from api.config import settings
from api.constants import LLM_METRICS_WINDOW_SECONDS, LM_STUDIO_PROVIDER, FieldName
from api.services.llm_metrics import llm_metrics
from api.services.llm_router import _find_cloud_fallback
from api.services.lmstudio_provider import (
    health_snapshot as lm_studio_health_snapshot,
)
from api.services.redis_store import get_redis_store
from api.utils import now_iso

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
    _model_setting: dict[str, tuple[str, str]] = {
        FieldName.GEMINI: ("GEMINI_MODEL", settings.GEMINI_MODEL),
        FieldName.GROQ: ("GROQ_MODEL", settings.GROQ_MODEL),
        FieldName.ANTHROPIC: ("ANTHROPIC_MODEL", getattr(settings, "ANTHROPIC_MODEL", "unknown")),
        FieldName.OPENAI: ("OPENAI_MODEL", getattr(settings, "OPENAI_MODEL", "unknown")),
        LM_STUDIO_PROVIDER: ("LM_STUDIO_MODEL", settings.LM_STUDIO_MODEL or "not configured"),
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

    # After a restart the ring buffer has no recent successes so avg_latency_ms
    # is 0 and the panel shows "--". Fall back to the last known latency from
    # Redis so the panel shows a meaningful value instead.
    if not snap.get(FieldName.AVG_LATENCY_MS):
        redis_latency = redis_metrics.get(FieldName.LAST_LATENCY_MS) or 0
        if redis_latency:
            snap[FieldName.AVG_LATENCY_MS] = redis_latency

    # Surface last_success_at at the top level so the dashboard can show
    # "last call X ago" when the current window is empty (post-restart).
    last_success_at: str | None = redis_metrics.get(FieldName.LAST_SUCCESS_AT)

    lm_snap = lm_studio_health_snapshot()
    # active_provider reflects what is actually serving requests right now.
    # When LM Studio is healthy it is always the active provider.
    # When LM Studio is configured as primary but is down with fallback enabled,
    # call_llm() routes to a cloud provider — surface that here so the dashboard
    # does not incorrectly claim LM Studio is serving.
    if lm_snap.get(FieldName.LM_STUDIO_HEALTHY):
        active_provider = LM_STUDIO_PROVIDER
    elif provider == LM_STUDIO_PROVIDER and settings.LLM_FALLBACK_ENABLED:
        active_provider = _find_cloud_fallback() or provider
    else:
        active_provider = provider

    return {
        FieldName.STATUS: status,
        FieldName.PROVIDER: provider,
        FieldName.ACTIVE_PROVIDER: active_provider,
        FieldName.MODEL: model_name,
        FieldName.MODEL_VAR: _attr if _attr else "unknown",
        FieldName.TIMESTAMP: now_iso(),
        FieldName.LAST_SUCCESS_AT: last_success_at,
        FieldName.REDIS_METRICS: redis_metrics,
        FieldName.LOCAL_INFERENCE_ENABLED: lm_snap.get(FieldName.LM_STUDIO_ENABLED, False),
        FieldName.LLM_FALLBACK_ENABLED: settings.LLM_FALLBACK_ENABLED,
        **lm_snap,
        **snap,
    }
