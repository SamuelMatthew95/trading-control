"""Centralized LM Studio local inference provider.

All LM Studio interaction uses the OpenAI-compatible REST API at
http://host:port/v1, accessed via the openai.AsyncOpenAI client.

No agent or other module imports openai directly for local inference;
all local calls go through this module.  Callers catch
LMStudioUnavailableError and fall back to the configured cloud provider.

Health state is module-level, updated by check_health() at startup and
by every call.  The startup probe is non-blocking — a False result means
the app continues in degraded (cloud-only) mode.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

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
    last_failure_at: float = 0.0


_health = _LocalHealthState()

# After a failure, skip LM Studio for this many seconds before retrying.
_RETRY_INTERVAL_S: float = 60.0


def is_local_healthy() -> bool:
    """Return True if the last health probe or call succeeded."""
    return _health.healthy


def should_try_local() -> bool:
    """True when LM Studio should be attempted.

    Returns True if the provider is currently healthy, OR if enough time has
    elapsed since the last failure to warrant a retry attempt.  This prevents
    the router from waiting up to LM_STUDIO_TIMEOUT_SECONDS on every call when
    LM Studio is known-dead.
    """
    if _health.healthy:
        return True
    return (time.monotonic() - _health.last_failure_at) >= _RETRY_INTERVAL_S


def health_snapshot() -> dict:
    """Snapshot for the /llm/health endpoint."""
    return {
        FieldName.LM_STUDIO_ENABLED: settings.LM_STUDIO_ENABLED,
        FieldName.LM_STUDIO_HEALTHY: _health.healthy,
        FieldName.LOCAL_FALLBACK_COUNT: _health.fallback_count,
        FieldName.LAST_LOCAL_ERROR: _health.last_error,
        FieldName.LOCAL_MODEL: settings.LM_STUDIO_MODEL.strip() or None,
        FieldName.LOCAL_LATENCY_MS: round(_health.last_latency_ms)
        if _health.last_latency_ms
        else None,
    }


def _record_success(latency_ms: float) -> None:
    _health.healthy = True
    _health.last_error = None
    _health.last_latency_ms = latency_ms


def _record_failure(error: str) -> None:
    _health.healthy = False
    _health.last_error = error[:120]
    _health.fallback_count += 1
    _health.last_failure_at = time.monotonic()


def _make_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client pointed at LM Studio's OpenAI-compatible endpoint.

    LM Studio exposes /v1 at http://host:port/v1.
    api_key is set to LM_LINK_TOKEN when provided (optional proxy auth in
    front of LM Studio); the local LM Studio server accepts any non-empty string.
    LM Link itself is Tailscale-based — set LM_STUDIO_HOST to the Tailscale
    hostname/IP of your GPU machine and LM Link handles the network layer.

    When LM_LINK_ENABLED, we pass trust_env=False to the underlying httpx client
    so it ignores ALL_PROXY / HTTP_PROXY env vars set by Tailscale.  Routing to
    the Tailscale peer happens at the OS network layer; sending the HTTP stream
    through the SOCKS5 proxy a second time produces "incompatible SOCKS version"
    and "peerapi: unknown peer" errors in the Tailscale daemon.
    """
    http_client = httpx.AsyncClient(trust_env=False) if settings.LM_LINK_ENABLED else None
    return AsyncOpenAI(
        base_url=f"http://{settings.LM_STUDIO_HOST}:{settings.LM_STUDIO_PORT}/v1",
        api_key=settings.LM_LINK_TOKEN or "lm-studio",
        timeout=float(settings.LM_STUDIO_TIMEOUT_SECONDS),
        max_retries=0,
        http_client=http_client,
    )


async def check_health() -> bool:
    """Probe LM Studio via GET /v1/models. Non-blocking: returns False if unavailable."""
    if not settings.LM_STUDIO_ENABLED:
        _health.healthy = False
        return False
    try:
        client = _make_client()
        models = await client.models.list()
        ok = bool(models.data)
        _health.healthy = ok
        _health.last_error = None if ok else "no_model_loaded"
        return ok
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

    model_id = settings.LM_STUDIO_MODEL.strip()
    if not model_id:
        _record_failure("lm_studio_model_not_configured")
        raise LMStudioUnavailableError("lm_studio_model_not_configured")

    t0 = time.monotonic()
    try:
        client = _make_client()
        completion = await client.chat.completions.create(
            model=model_id,
            messages=[
                {FieldName.ROLE: "system", FieldName.CONTENT: system_prompt},
                {FieldName.ROLE: "user", FieldName.CONTENT: prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text: str = (completion.choices[0].message.content or "") if completion.choices else ""
    except LMStudioUnavailableError:
        raise
    except APITimeoutError:
        _record_failure("timeout")
        log_structured(
            "warning",
            "lmstudio_timeout",
            trace_id=trace_id,
            timeout_seconds=settings.LM_STUDIO_TIMEOUT_SECONDS,
        )
        raise LMStudioUnavailableError("lmstudio_timeout") from None
    except APIConnectionError as exc:
        _record_failure(str(exc))
        log_structured("warning", "lmstudio_connection_failed", trace_id=trace_id, exc_info=True)
        raise LMStudioUnavailableError(f"lmstudio_connection_failed: {exc}") from exc
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
        model=model_id,
        provider=LM_STUDIO_PROVIDER,
    )
    return text, 0, 0.0
