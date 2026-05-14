"""LLM health endpoint — exposes live call metrics from the in-memory collector."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from api.config import settings
from api.constants import LLM_METRICS_WINDOW_SECONDS
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
    status = _llm_status(snap["success_rate_pct"], snap["total_in_window"])

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

    # Merge the durable Redis totals into the lifetime fields the existing UI
    # already reads (`total_calls_lifetime`). The in-process snapshot keeps
    # owning the window-bounded fields (`success_rate_pct`, `daily_calls`,
    # `recent_results`, etc.); we only override the cumulative counters when
    # Redis has a strictly larger value, which means "survived a restart".
    snap_total = int(snap.get("total_calls_lifetime") or 0)
    redis_total = int(redis_metrics.get("total_calls") or 0)
    if redis_total > snap_total:
        snap["total_calls_lifetime"] = redis_total

    return {
        "status": status,
        "provider": provider,
        "model": model_name,
        "model_var": _attr if _attr else "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "redis_metrics": redis_metrics,
        **snap,
    }
