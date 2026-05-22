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

import json
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from api.config import settings
from api.constants import (
    LLM_STOP_SEQUENCES,
    LLM_TASK_HEALTH_CHECK,
    LLM_TASK_PRICE_ANALYSIS,
    LLM_TASK_TRADE_EXECUTION,
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

    Checks both the legacy LM_STUDIO_HOST:LM_STUDIO_PORT config and the
    LM_STUDIO_BASE_URL override so the guard cannot be bypassed by setting
    only the URL override.
    """
    blocked_msg = (
        "proxy endpoint was used as LM Studio destination. "
        "Set LM_STUDIO_HOST=<tailscale-ip-of-mac> (e.g. 100.112.224.78) "
        "and LM_STUDIO_PORT=1234.  "
        "To route through Tailscale userspace networking set "
        "LM_STUDIO_PROXY_URL=http://127.0.0.1:1055 instead."
    )
    host_port = f"{settings.LM_STUDIO_HOST.strip()}:{settings.LM_STUDIO_PORT}"
    if host_port in _BLOCKED_HOST_PORT:
        raise RuntimeError(f"Invalid LM_STUDIO_HOST:LM_STUDIO_PORT ({host_port}): {blocked_msg}")
    base_url_override = getattr(settings, "LM_STUDIO_BASE_URL", "").strip()
    if base_url_override:
        parsed = urlparse(base_url_override)
        try:
            base_host = (parsed.hostname or "").lower()
            base_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            # urlparse accepts invalid port strings like "notaport" without raising,
            # but accessing .port raises ValueError — surface it as a RuntimeError so
            # check_health() can catch it and return a controlled degraded response.
            raise RuntimeError(
                f"Invalid LM_STUDIO_BASE_URL: cannot parse host/port — {exc}"
            ) from exc
        base_host_port = f"{base_host}:{base_port}"
        if base_host_port in _BLOCKED_HOST_PORT:
            raise RuntimeError(
                f"Invalid LM_STUDIO_BASE_URL host:port ({base_host_port}): {blocked_msg}"
            )


def get_lm_studio_base_url() -> str:
    """Return the canonical LM Studio base URL, always ending in /v1.

    When LM_STUDIO_BASE_URL is set it takes precedence over LM_STUDIO_HOST
    and LM_STUDIO_PORT.  The /v1 suffix is appended to the URL *path* (not the
    raw string) so query/fragment components in the original URL are preserved
    without corruption.
    """
    raw = getattr(settings, "LM_STUDIO_BASE_URL", "").strip()
    if raw:
        parsed = urlparse(raw)
        path = parsed.path.rstrip("/")
        if not path.endswith("/v1"):
            path = path + "/v1"
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    host = settings.LM_STUDIO_HOST.strip()
    port = settings.LM_STUDIO_PORT
    return f"http://{host}:{port}/v1"


def _redact_url(url: str) -> str:
    """Strip userinfo and query from a URL so credentials are not logged."""
    if not url:
        return url
    try:
        p = urlparse(url)
        netloc = p.hostname or ""
        if p.port:
            netloc = f"{netloc}:{p.port}"
        return urlunparse((p.scheme, netloc, p.path, "", "", ""))
    except Exception:
        return "<url_parse_error>"


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
        base_url=_redact_url(get_lm_studio_base_url()),
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
        _health.available_models = []
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
        _health.available_models = []
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
            if not configured:
                _health.last_error = "lm_studio_model_not_configured"
                _health.healthy = False
                return False
            if configured not in model_ids:
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
        _health.available_models = []
        _health.last_error = str(exc)[:200]
        log_structured("warning", "lmstudio_health_probe_failed", exc_info=True)
        return False


def _hold_fallback_json(trace_id: str, reason: str) -> str:
    """Return a serialized safe HOLD decision for use when model output is unusable."""
    return json.dumps(
        {
            FieldName.ACTION: "hold",
            FieldName.CONFIDENCE: 0.0,
            FieldName.PRIMARY_EDGE: "lmstudio_fallback",
            FieldName.RISK_FACTORS: [reason],
            FieldName.SIZE_PCT: 0.0,
            FieldName.STOP_ATR_X: 0.0,
            FieldName.RR_RATIO: 0.0,
            FieldName.LATENCY_MS: 0,
            FieldName.COST_USD: 0.0,
            FieldName.TRACE_ID: trace_id,
            FieldName.FALLBACK: True,
        }
    )


def _extract_json_from_text(text: str) -> str:
    """Return the first valid JSON object found in text, or empty string."""
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text):
        start = text.find("{", pos)
        if start == -1:
            break
        try:
            _, end = decoder.raw_decode(text, start)
            return text[start:end]
        except json.JSONDecodeError:
            pos = start + 1
    return ""


def _get_task_params(
    task_type: str | None, default_max_tokens: int, default_temperature: float
) -> tuple[int, float]:
    """Return (max_tokens, temperature) for the given task type.

    Falls back to the caller-supplied defaults when task_type is None or unrecognised.
    Token budgets come from env-overridable settings so Render deployments can tune them
    without a code deploy.
    """
    temp = settings.LM_STUDIO_TEMPERATURE
    if task_type == LLM_TASK_TRADE_EXECUTION:
        return settings.LM_STUDIO_MAX_TOKENS_EXECUTION, temp
    if task_type == LLM_TASK_HEALTH_CHECK:
        return settings.LM_STUDIO_MAX_TOKENS_HEALTH_CHECK, temp
    if task_type == LLM_TASK_PRICE_ANALYSIS:
        return settings.LM_STUDIO_MAX_TOKENS_ANALYSIS, temp
    return default_max_tokens, temp


async def _collect_streaming_response(
    client,
    model_id: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    trace_id: str,
) -> tuple[str, str]:
    """Stream a completion and return (content, reasoning_content).

    Keeps the TCP connection alive during long model generation by consuming
    each token chunk as it arrives.  Raises the original exception on any
    mid-stream failure so the caller can retry with non-streaming.
    """
    stream = await client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        stop=LLM_STOP_SEQUENCES,
    )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    chunk_count = 0
    t_start = time.monotonic()
    async for chunk in stream:
        chunk_count += 1
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta:
            if delta.content:
                content_parts.append(delta.content)
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_parts.append(rc)
    log_structured(
        "info",
        "lmstudio_stream_completed",
        trace_id=trace_id,
        stream_secs=round(time.monotonic() - t_start, 2),
        chunk_count=chunk_count,
    )
    return "".join(content_parts), "".join(reasoning_parts)


async def call_lmstudio(
    prompt: str,
    system_prompt: str,
    trace_id: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
    task_type: str | None = None,
    *,
    parse_json: bool = True,
) -> tuple[str, int, float]:
    """Call LM Studio with the given system + user prompt.

    Non-streaming by default (LM_STUDIO_STREAM=false) — instruct models return
    short, bounded JSON in one shot so streaming adds no benefit and complicates
    response handling.  Set LM_STUDIO_STREAM=true to re-enable streaming.

    task_type selects the token budget (price_analysis / trade_execution /
    health_check); falls back to LM_STUDIO_MAX_TOKENS when None.

    When parse_json=True (default), validates that content is a recognised
    trade action JSON and returns a safe HOLD fallback when it is not.
    Set parse_json=False for freeform text calls (reflections, analysis).

    Returns (raw_text, token_count, cost_usd).
    Raises LMStudioUnavailableError on any failure so the router can fall back.
    """
    if not _is_lmstudio_effectively_enabled():
        raise LMStudioUnavailableError("lm_studio_disabled")

    model_id = settings.LM_STUDIO_MODEL.strip()
    if not model_id:
        _record_failure("lm_studio_model_not_configured")
        raise LMStudioUnavailableError("lm_studio_model_not_configured")

    _default_max = max_tokens if max_tokens is not None else settings.LM_STUDIO_MAX_TOKENS
    _default_temp = temperature if temperature is not None else settings.LM_STUDIO_TEMPERATURE
    effective_max_tokens, effective_temperature = _get_task_params(
        task_type, _default_max, _default_temp
    )

    proxy_raw = settings.LM_STUDIO_PROXY_URL.strip()
    proxy_enabled = bool(proxy_raw)
    log_structured(
        "info",
        "reasoning_llm_request",
        provider=LM_STUDIO_PROVIDER,
        base_url_host=_get_lm_studio_configured_host(),
        proxy_enabled=proxy_enabled,
        timeout_seconds=settings.LM_STUDIO_TIMEOUT_SECONDS,
        task_type=task_type or LLM_TASK_PRICE_ANALYSIS,
        max_tokens=effective_max_tokens,
        trace_id=trace_id,
    )

    messages = [
        {FieldName.ROLE: "system", FieldName.CONTENT: system_prompt},
        {FieldName.ROLE: "user", FieldName.CONTENT: prompt},
    ]

    t0 = time.monotonic()
    try:
        client = _make_client()

        if settings.LM_STUDIO_STREAM:
            raw_content, _ = await _collect_streaming_response(
                client, model_id, messages, effective_max_tokens, effective_temperature, trace_id
            )
            reasoning_present = False
            finish_reason = None
        else:
            # Non-streaming: deterministic, bounded — the right choice for instruct
            # models (Llama 3.1) that return short JSON decisions in one shot.
            completion = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=effective_max_tokens,
                temperature=effective_temperature,
                stream=False,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                stop=LLM_STOP_SEQUENCES,
            )
            msg = completion.choices[0].message if completion.choices else None
            # Only read message.content — reasoning_content is a thinking-mode field
            # not produced by instruct models such as Llama 3.1.
            raw_content = (msg.content or "") if msg else ""
            reasoning_present = bool(getattr(msg, "reasoning_content", None)) if msg else False
            finish_reason = (
                completion.choices[0].finish_reason
                if completion.choices and hasattr(completion.choices[0], "finish_reason")
                else None
            )

        log_structured(
            "info",
            "lmstudio_response_received",
            trace_id=trace_id,
            model=model_id,
            content_present=bool(raw_content),
            reasoning_content_present=reasoning_present,
            finish_reason=finish_reason,
            content_preview=raw_content[:300] if raw_content else None,
        )

        # Empty response: let the router fall back or ReasoningAgent apply HOLD.
        if not raw_content:
            _record_failure("lmstudio_empty_response")
            log_structured(
                "warning",
                "lmstudio_parse_completed",
                trace_id=trace_id,
                model=model_id,
                parse_result="empty_content",
                fallback_used=True,
            )
            raise LMStudioUnavailableError(
                "lmstudio_empty_response: model returned no parseable content"
            )

        # JSON validation: only for callers that expect a trading decision JSON.
        # Freeform calls (reflections, analysis) pass parse_json=False.
        text: str = raw_content
        if parse_json:
            parse_result = "success"
            parsed: dict | None = None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                extracted = _extract_json_from_text(text)
                if extracted:
                    try:
                        parsed = json.loads(extracted)
                        text = extracted
                    except json.JSONDecodeError:
                        parsed = None
                if parsed is None:
                    parse_result = "invalid_json"
                    log_structured(
                        "warning",
                        "lmstudio_json_invalid_hold_fallback",
                        trace_id=trace_id,
                        model=model_id,
                        parse_result=parse_result,
                        content_preview=raw_content[:300],
                        fallback_used=True,
                    )
                    text = _hold_fallback_json(trace_id, "LM Studio returned invalid or empty JSON")
                    parsed = json.loads(text)

            # Schema validation: action must be a recognised trade action.
            action = str(parsed.get(FieldName.ACTION, "")).lower().strip()  # type: ignore[union-attr]
            if action not in {"buy", "sell", "hold", "reject"}:
                parse_result = "schema_invalid"
                log_structured(
                    "warning",
                    "lmstudio_invalid_action_hold_fallback",
                    trace_id=trace_id,
                    model=model_id,
                    action_received=action,
                    parse_result=parse_result,
                    fallback_used=True,
                )
                text = _hold_fallback_json(trace_id, f"unknown action: {action!r}")

            log_structured(
                "info",
                "lmstudio_parse_completed",
                trace_id=trace_id,
                model=model_id,
                parse_result=parse_result,
                fallback_used=(parse_result not in {"success"}),
            )

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
