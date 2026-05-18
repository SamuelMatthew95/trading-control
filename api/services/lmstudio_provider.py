"""Centralized LM Studio local inference provider.

All lmstudio SDK interaction is isolated here. No agent or other module
imports the SDK directly.  Callers catch LMStudioUnavailableError and fall back
to the configured cloud provider.

Health state is module-level, updated by check_health() at startup and by
every call.  The startup probe is non-blocking — a False result means the app
continues in degraded (cloud-only) mode.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from api.config import settings
from api.constants import (
    LLM_MAX_TOKENS_TRADING,
    LLM_TEMPERATURE_TRADING,
    LM_STUDIO_PROVIDER,
    FieldName,
)
from api.observability import log_structured


class LMStudioUnavailableError(RuntimeError):
    """LM Studio is unreachable, no model is loaded, or inference failed.

    The router catches this and falls back to the cloud provider.
    """


@dataclass
class _LocalHealthState:
    healthy: bool = False
    last_error: str | None = None
    fallback_count: int = 0
    last_latency_ms: float = 0.0


_health = _LocalHealthState()


def is_local_healthy() -> bool:
    """Return True if the last health probe or call succeeded."""
    return _health.healthy


def health_snapshot() -> dict:
    """Snapshot for the /llm/health endpoint."""
    return {
        FieldName.LM_STUDIO_ENABLED: settings.LM_STUDIO_ENABLED,
        FieldName.LM_STUDIO_HEALTHY: _health.healthy,
        FieldName.LOCAL_FALLBACK_COUNT: _health.fallback_count,
        FieldName.LAST_LOCAL_ERROR: _health.last_error,
        FieldName.LOCAL_MODEL: settings.LM_STUDIO_MODEL or None,
    }


def _record_success(latency_ms: float) -> None:
    _health.healthy = True
    _health.last_error = None
    _health.last_latency_ms = latency_ms


def _record_failure(error: str) -> None:
    _health.healthy = False
    _health.last_error = error[:120]
    _health.fallback_count += 1


def _base_url() -> str:
    return f"http://{settings.LM_STUDIO_HOST}:{settings.LM_STUDIO_PORT}"


def _make_client(lms_module: object) -> object:
    """Create an AsyncClient for local LM Studio or a remote LM Link connection.

    When LM_LINK_ENABLED=True and LM_LINK_TOKEN is set the token is passed as
    api_key so the remote LM Link endpoint can authenticate the request.
    """
    kwargs: dict = {"base_url": _base_url()}
    if settings.LM_LINK_ENABLED and settings.LM_LINK_TOKEN:
        kwargs["api_key"] = settings.LM_LINK_TOKEN
    return lms_module.AsyncClient(**kwargs)  # type: ignore[attr-defined]


async def check_health() -> bool:
    """Probe LM Studio. Non-blocking: returns False if unavailable."""
    if not settings.LM_STUDIO_ENABLED:
        _health.healthy = False
        return False
    try:
        import lmstudio as lms  # noqa: PLC0415

        client = _make_client(lms)
        loaded = await asyncio.wait_for(
            client.llm.list_loaded(),
            timeout=float(settings.LM_STUDIO_TIMEOUT_SECONDS),
        )
        ok = bool(loaded)
        _health.healthy = ok
        _health.last_error = None if ok else "no_model_loaded"
        return ok
    except ImportError:
        _health.healthy = False
        _health.last_error = "lmstudio_sdk_not_installed"
        log_structured("warning", "lmstudio_sdk_not_installed")
        return False
    except Exception as exc:
        _health.healthy = False
        _health.last_error = str(exc)[:120]
        log_structured("warning", "lmstudio_health_probe_failed", exc_info=True)
        return False


async def call_lmstudio(
    prompt: str,
    system_prompt: str,
    trace_id: str,
    max_tokens: int = LLM_MAX_TOKENS_TRADING,
    temperature: float = LLM_TEMPERATURE_TRADING,
) -> tuple[str, int, float]:
    """Call LM Studio with the given system + user prompt.

    Returns (raw_text, token_count, cost_usd).
    Raises LMStudioUnavailableError on any failure so the router can fall back.
    """
    if not settings.LM_STUDIO_ENABLED:
        raise LMStudioUnavailableError("lm_studio_disabled")

    model_id = settings.LM_STUDIO_MODEL
    if not model_id:
        _record_failure("lm_studio_model_not_configured")
        raise LMStudioUnavailableError("lm_studio_model_not_configured")

    t0 = time.monotonic()
    try:
        import lmstudio as lms  # noqa: PLC0415

        client = _make_client(lms)
        result = await asyncio.wait_for(
            client.llm.respond(
                model_id,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                config={"temperature": temperature, "maxTokens": max_tokens},
            ),
            timeout=float(settings.LM_STUDIO_TIMEOUT_SECONDS),
        )
        text: str = getattr(result, "content", None) or ""
    except LMStudioUnavailableError:
        raise
    except ImportError:
        _record_failure("lmstudio_sdk_not_installed")
        raise LMStudioUnavailableError("lmstudio_sdk_not_installed") from None
    except asyncio.TimeoutError:
        _record_failure("timeout")
        log_structured(
            "warning",
            "lmstudio_timeout",
            trace_id=trace_id,
            timeout_seconds=settings.LM_STUDIO_TIMEOUT_SECONDS,
        )
        raise LMStudioUnavailableError("lmstudio_timeout") from None
    except Exception as exc:
        _record_failure(str(exc))
        log_structured("warning", "lmstudio_call_failed", trace_id=trace_id, exc_info=True)
        raise LMStudioUnavailableError(f"lmstudio_inference_failed: {exc}") from exc

    latency_ms = (time.monotonic() - t0) * 1000
    _record_success(latency_ms)
    log_structured(
        "info",
        "lmstudio_call_succeeded",
        trace_id=trace_id,
        latency_ms=round(latency_ms),
        model=settings.LM_STUDIO_MODEL,
        provider=LM_STUDIO_PROVIDER,
    )
    return text, 0, 0.0
