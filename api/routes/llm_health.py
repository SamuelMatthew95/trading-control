"""LLM health endpoint — exposes live call metrics from the in-memory collector."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from api.config import settings
from api.constants import LLM_METRICS_WINDOW_SECONDS
from api.services.llm_metrics import llm_metrics

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

    return {
        "status": status,
        "provider": provider,
        "model": model_name,
        "model_var": _attr if _attr else "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **snap,
    }
