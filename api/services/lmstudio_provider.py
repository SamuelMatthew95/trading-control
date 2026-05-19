"""Centralized LM Studio local inference provider.

All LM Studio interaction uses the OpenAI-compatible REST API at
http://host:port/v1, accessed via the openai.AsyncOpenAI client.

No agent or other module imports openai directly for local inference;
all local calls go through this module.  Callers catch
LMStudioUnavailableError and fall back to the configured cloud provider.

Health state is module-level, updated by check_health() at startup and
by every call.  The startup probe is non-blocking — a False result means
the app continues in degraded (cloud-only) mode.

## Provider selection

Set LLM_PROVIDER=lmstudio to make LM Studio the primary provider.
This is the recommended approach and removes the need to also set
LM_STUDIO_ENABLED=true.

When LM_PROVIDER=lmstudio:
- LM Studio is always tried first (no cloud API key required).
- If LM Studio is unavailable and LLM_FALLBACK_ENABLED=false (recommended),
  the call raises immediately with a clear error.
- If LLM_FALLBACK_ENABLED=true, the router tries the first cloud provider
  that has an API key configured.

## Remote deployment with local LM Studio

A remote backend (e.g. on Render) cannot reach LM Studio running on
localhost of a developer machine. When the backend detects this
configuration (RENDER_EXTERNAL_URL is set and LM_STUDIO_HOST is
localhost/127.0.0.1), check_health() returns False with a clear error:
  "Remote backend cannot reach local LM Studio at localhost. Use a
   public tunnel, Tailscale, or run backend locally."

The /llm/health endpoint exposes remote_localhost_mismatch: true so the
dashboard can surface a helpful message instead of a vague "Connection error."

To make a remote backend reach LM Studio, use one of:
- Run the backend locally alongside LM Studio.
- Expose LM Studio through a secure tunnel (ngrok, Cloudflare Tunnel).
- Connect both machines through Tailscale and set
  LM_STUDIO_HOST=<tailscale-ip-of-mac>.
- Deploy the model somewhere the backend can reach it.

## Tailscale userspace-networking note

When Tailscale runs with --tun=userspace-networking there is no kernel TUN
device, so direct TCP to Tailscale IPs (e.g. 100.112.224.78) does NOT work.
All traffic to Tailscale peers must go through the proxy that tailscaled
exposes.  The recommended approach:

  1. Start tailscaled with --outbound-http-proxy-listen=localhost:1055
     (and optionally --socks5-server=localhost:1055 for other clients).
  2. Set LM_STUDIO_PROXY_URL=http://127.0.0.1:1055 so _make_client() passes
     it as an explicit HTTP CONNECT proxy to httpx.
  3. Set LM_STUDIO_HOST=<tailscale-ip-of-mac> (e.g. 100.112.224.78) and
     LM_STUDIO_PORT=1234.

trust_env=False is ALWAYS applied to the httpx client regardless of
LM_STUDIO_PROXY_URL — this prevents httpx from silently picking up
ALL_PROXY / HTTP_PROXY / HTTPS_PROXY environment variables that could route
traffic through the SOCKS5 listener with plain HTTP, producing the
"incompatible SOCKS version" error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

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

    The router catches this and falls back to the configured cloud provider.
    """


@dataclass
class _LocalHealthState:
    healthy: bool = False
    last_error: str | None = None
    fallback_count: int = 0
    last_latency_ms: float = 0.0
    last_failure_at: float = 0.0
    remote_localhost_mismatch: bool = False
    available_models: list[str] = field(default_factory=list)


_health = _LocalHealthState()

# After a failure, skip LM Studio for this many seconds before retrying.
_RETRY_INTERVAL_S: float = 60.0

# Host:port combos that are proxy endpoints, not valid LM Studio destinations.
_BLOCKED_HOST_PORT: frozenset[str] = frozenset({"127.0.0.1:1055", "localhost:1055", "0.0.0.0:1055"})

_LOCALHOST_NAMES: frozenset[str] = frozenset({"localhost", "127.0.0.1"})


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


def _get_lm_studio_configured_host() -> str:
    """Extract the effective LM Studio host for mismatch detection."""
    base_url = getattr(settings, "LM_STUDIO_BASE_URL", "").strip()
    if base_url:
        parsed = urlparse(base_url)
        return (parsed.hostname or "").lower()
    return settings.LM_STUDIO_HOST.strip().lower()


def is_remote_localhost_mismatch() -> bool:
    """True when backend is remote (Render) but LM Studio points at localhost.

    A remote backend (e.g. deployed on Render) cannot reach LM Studio running
    on the developer's laptop via localhost/127.0.0.1.  When this is detected,
    the health check returns a clear diagnostic instead of a vague connection
    error.
    """
    is_remote = bool(settings.RENDER_EXTERNAL_URL)
    host = _get_lm_studio_configured_host()
    return is_remote and host in _LOCALHOST_NAMES


def _is_lmstudio_primary() -> bool:
    """True when LLM_PROVIDER=lmstudio, making LM Studio the primary provider."""
    return settings.LLM_PROVIDER.lower().strip() == LM_STUDIO_PROVIDER


def _is_lmstudio_effectively_enabled() -> bool:
    """True when LM Studio should be active — either explicitly enabled or set as primary."""
    return settings.LM_STUDIO_ENABLED or _is_lmstudio_primary()


def health_snapshot() -> dict:
    """Snapshot for the /llm/health endpoint."""
    mismatch = is_remote_localhost_mismatch()
    is_enabled = _is_lmstudio_effectively_enabled()

    last_error = _health.last_error
    if mismatch and is_enabled and not last_error:
        last_error = (
            "Remote backend cannot reach local LM Studio at localhost. "
            "Use a public tunnel, Tailscale, or run backend locally."
        )

    return {
        FieldName.LM_STUDIO_ENABLED: is_enabled,
        FieldName.LM_STUDIO_HEALTHY: _health.healthy,
        FieldName.LOCAL_FALLBACK_COUNT: _health.fallback_count,
        FieldName.LAST_LOCAL_ERROR: last_error,
        FieldName.LOCAL_MODEL: settings.LM_STUDIO_MODEL.strip() or None,
        FieldName.LOCAL_LATENCY_MS: round(_health.last_latency_ms)
        if _health.last_latency_ms
        else None,
        FieldName.REACHABLE: _health.healthy,
        FieldName.REMOTE_LOCALHOST_MISMATCH: mismatch,
        FieldName.BASE_URL_HOST: _get_lm_studio_configured_host(),
        FieldName.AVAILABLE_MODELS: _health.available_models or None,
    }


def validate_lm_studio_config() -> None:
    """Raise RuntimeError if LM Studio host:port points at a proxy endpoint.

    localhost:1055 is the Tailscale SOCKS5/HTTP proxy — it must never be used
    as the LM Studio destination.  LM_STUDIO_HOST should be the Tailscale IP
    of the machine running LM Studio (e.g. 100.112.224.78).
    """
    host_port = f"{settings.LM_STUDIO_HOST.strip()}:{settings.LM_STUDIO_PORT}"
    if host_port in _BLOCKED_HOST_PORT:
        raise RuntimeError(
            f"Invalid LM_STUDIO_HOST:LM_STUDIO_PORT ({host_port}): "
            "proxy endpoint was used as LM Studio destination. "
            "Set LM_STUDIO_HOST=<tailscale-ip-of-mac> (e.g. 100.112.224.78) "
            "and LM_STUDIO_PORT=1234.  "
            "To route through Tailscale userspace networking set "
            "LM_STUDIO_PROXY_URL=http://127.0.0.1:1055 instead."
        )


def get_lm_studio_base_url() -> str:
    """Return the canonical LM Studio base URL, always ending in /v1.

    When LM_STUDIO_BASE_URL is set it takes precedence over LM_STUDIO_HOST
    and LM_STUDIO_PORT.  The /v1 suffix is appended if not already present.
    """
    base_url = getattr(settings, "LM_STUDIO_BASE_URL", "").strip().rstrip("/")
    if base_url:
        if not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        return base_url
    host = settings.LM_STUDIO_HOST.strip()
    port = settings.LM_STUDIO_PORT
    return f"http://{host}:{port}/v1"


def log_startup_config() -> None:
    """Log sanitized LM Studio config for startup diagnostics.

    Safe to call before or after check_health().  Never logs secrets.
    """
    proxy_raw = settings.LM_STUDIO_PROXY_URL.strip()
    proxy_enabled = bool(proxy_raw)
    proxy_scheme: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    if proxy_raw:
        parsed = urlparse(proxy_raw)
        proxy_scheme = parsed.scheme or None
        proxy_host = parsed.hostname or None
        proxy_port = parsed.port or None

    log_structured(
        "info",
        "lmstudio_config",
        provider=LM_STUDIO_PROVIDER,
        base_url=get_lm_studio_base_url(),
        base_url_host=_get_lm_studio_configured_host(),
        proxy_enabled=proxy_enabled,
        proxy_scheme=proxy_scheme,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        lm_link_enabled=settings.LM_LINK_ENABLED,
        model=settings.LM_STUDIO_MODEL.strip() or None,
        is_primary=_is_lmstudio_primary(),
        remote_localhost_mismatch=is_remote_localhost_mismatch(),
    )


def _record_success(latency_ms: float) -> None:
    _health.healthy = True
    _health.last_error = None
    _health.last_latency_ms = latency_ms


def _record_failure(error: str) -> None:
    _health.healthy = False
    _health.last_error = error[:200]
    _health.fallback_count += 1
    _health.last_failure_at = time.monotonic()


def _make_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client pointed at LM Studio's OpenAI-compatible endpoint.

    trust_env=False is always applied so httpx never inherits ALL_PROXY,
    HTTP_PROXY, or HTTPS_PROXY from the environment — those system proxy vars
    could silently route LM Studio HTTP traffic through the Tailscale SOCKS5
    listener, producing "incompatible SOCKS version" errors.

    When LM_STUDIO_PROXY_URL is set (e.g. http://127.0.0.1:1055), it is passed
    as an explicit HTTP CONNECT proxy transport.  This is the correct way to
    reach a Tailscale peer when tailscaled runs in userspace-networking mode
    with --outbound-http-proxy-listen.

    api_key is set to LM_LINK_TOKEN when provided (optional proxy auth);
    the local LM Studio server accepts any non-empty string.
    """
    proxy_url: str | None = settings.LM_STUDIO_PROXY_URL.strip() or None
    http_client = httpx.AsyncClient(
        proxy=proxy_url,
        trust_env=False,
    )
    return AsyncOpenAI(
        base_url=get_lm_studio_base_url(),
        api_key=settings.LM_LINK_TOKEN or "lm-studio",
        timeout=float(settings.LM_STUDIO_TIMEOUT_SECONDS),
        max_retries=0,
        http_client=http_client,
    )


async def check_health() -> bool:
    """Probe LM Studio via GET /v1/models. Non-blocking: returns False if unavailable."""
    if not _is_lmstudio_effectively_enabled():
        _health.healthy = False
        return False

    # Detect remote-backend + localhost mismatch before attempting any network call.
    if is_remote_localhost_mismatch():
        _health.healthy = False
        _health.remote_localhost_mismatch = True
        mismatch_msg = (
            "Remote backend cannot reach local LM Studio at localhost. "
            "Use a public tunnel, Tailscale, or run backend locally."
        )
        _health.last_error = mismatch_msg
        log_structured(
            "warning",
            "lmstudio_remote_localhost_mismatch",
            host=_get_lm_studio_configured_host(),
            render_url=settings.RENDER_EXTERNAL_URL,
        )
        return False

    try:
        validate_lm_studio_config()
    except RuntimeError as exc:
        _health.healthy = False
        _health.last_error = str(exc)[:200]
        log_structured("error", "lmstudio_config_invalid", exc_info=True)
        return False
    try:
        client = _make_client()
        models = await client.models.list()
        model_ids = [m.id for m in (models.data or [])]
        _health.available_models = model_ids
        ok = bool(model_ids)
        _health.healthy = ok
        if ok:
            _health.last_error = None
            configured = settings.LM_STUDIO_MODEL.strip()
            if configured and configured not in model_ids:
                _health.last_error = (
                    f"Configured model '{configured}' not found in LM Studio. "
                    f"Loaded models: {', '.join(model_ids)}"
                )
                _health.healthy = False
                return False
        else:
            _health.last_error = "no_model_loaded"
        return ok
    except Exception as exc:
        _health.healthy = False
        _health.last_error = str(exc)[:200]
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
    if not _is_lmstudio_effectively_enabled():
        raise LMStudioUnavailableError("lm_studio_disabled")

    model_id = settings.LM_STUDIO_MODEL.strip()
    if not model_id:
        _record_failure("lm_studio_model_not_configured")
        raise LMStudioUnavailableError("lm_studio_model_not_configured")

    proxy_raw = settings.LM_STUDIO_PROXY_URL.strip()
    proxy_enabled = bool(proxy_raw)
    log_structured(
        "info",
        "reasoning_llm_request",
        provider=LM_STUDIO_PROVIDER,
        base_url_host=_get_lm_studio_configured_host(),
        proxy_enabled=proxy_enabled,
        timeout_seconds=settings.LM_STUDIO_TIMEOUT_SECONDS,
        trace_id=trace_id,
    )

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
            "reasoning_llm_timeout",
            provider=LM_STUDIO_PROVIDER,
            base_url_host=_get_lm_studio_configured_host(),
            proxy_enabled=proxy_enabled,
            timeout_seconds=settings.LM_STUDIO_TIMEOUT_SECONDS,
            exc_class="APITimeoutError",
            trace_id=trace_id,
        )
        raise LMStudioUnavailableError("lmstudio_timeout") from None
    except APIConnectionError as exc:
        err_msg = str(exc)
        if is_remote_localhost_mismatch():
            err_msg = (
                "Remote backend cannot reach local LM Studio at localhost. "
                "Use a public tunnel, Tailscale, or run backend locally."
            )
        _record_failure(err_msg)
        log_structured(
            "warning",
            "reasoning_llm_connection_failed",
            provider=LM_STUDIO_PROVIDER,
            base_url_host=_get_lm_studio_configured_host(),
            proxy_enabled=proxy_enabled,
            remote_localhost_mismatch=is_remote_localhost_mismatch(),
            exc_class="APIConnectionError",
            trace_id=trace_id,
            exc_info=True,
        )
        raise LMStudioUnavailableError(f"lmstudio_connection_failed: {err_msg}") from exc
    except Exception as exc:
        _record_failure(str(exc))
        log_structured(
            "warning",
            "reasoning_llm_failed",
            provider=LM_STUDIO_PROVIDER,
            base_url_host=_get_lm_studio_configured_host(),
            proxy_enabled=proxy_enabled,
            exc_class=type(exc).__name__,
            trace_id=trace_id,
            exc_info=True,
        )
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
