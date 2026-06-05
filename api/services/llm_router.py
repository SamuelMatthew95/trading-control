"""LLM provider router - switch via LLM_PROVIDER + matching API key."""

from __future__ import annotations

import asyncio
import json
import re
import time as _time

from api.config import settings
from api.constants import (
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS_ANALYSIS,
    LLM_MAX_TOKENS_TRADING,
    LLM_TASK_PRICE_ANALYSIS,
    LLM_TEMPERATURE_ANALYSIS,
    LLM_TEMPERATURE_TRADING,
    LM_STUDIO_PROVIDER,
    MAX_BACKOFF_SECONDS,
    AgentAction,
    FieldName,
)
from api.observability import log_structured
from api.services.llm_metrics import llm_metrics
from api.services.lmstudio_provider import (
    LMStudioUnavailableError,
    _is_lmstudio_primary,
    call_lmstudio,
    should_try_local,
)
from api.services.lmstudio_provider import (
    _record_failure as _record_lm_failure,
)
from api.utils import get_nested

_GEMINI_RPM = 15
_GEMINI_WINDOW = 60.0


class _GeminiRateLimiter:
    """Sliding-window rate limiter enforcing the Gemini free-tier 15 RPM cap.

    acquire() blocks until there is room in the current 60-second window,
    records the call timestamp, then returns immediately.  Callers must
    perform their own retry sleeps *outside* this scope so a 429 backoff
    does not hold a rate-limiter slot while idle.

    The asyncio.Lock is created lazily on the first call to acquire() so it
    always binds to the running event loop — avoiding the cross-loop
    RuntimeError that occurs when primitives are built at import time.
    """

    def __init__(self, rpm: int = _GEMINI_RPM, window: float = _GEMINI_WINDOW) -> None:
        self._rpm = rpm
        self._window = window
        self._call_times: list[float] = []
        self._lock: asyncio.Lock | None = None

    async def acquire(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            while True:
                now = _time.monotonic()
                self._call_times = [t for t in self._call_times if t > now - self._window]
                if len(self._call_times) < self._rpm:
                    self._call_times.append(now)
                    return
                wait = self._window - (now - self._call_times[0])
                if wait > 0:
                    await asyncio.sleep(wait)


_gemini_rate_limiter = _GeminiRateLimiter()

SYSTEM_PROMPT = (
    "Return ONLY valid JSON with keys: action, confidence, primary_edge, "
    "risk_factors, size_pct, stop_atr_x, rr_ratio, latency_ms, cost_usd, "
    "trace_id, fallback. action must be one of: buy, sell, hold, reject."
)


def _parse_response(text: str, trace_id: str, cost_usd: float = 0.0) -> dict:
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence
        text = text[3:]
        # Remove language identifier if present (e.g. "json\n")
        if "\n" in text:
            first_line, rest = text.split("\n", 1)
            if first_line.strip() in {"json", "JSON", ""}:
                text = rest
        # Remove closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    # Clean up any remaining whitespace and handle edge cases
    text = text.strip()
    if not text:
        return {
            FieldName.ACTION: AgentAction.REJECT,
            FieldName.TRACE_ID: trace_id,
            FieldName.FALLBACK: True,
            FieldName.ERROR: "Empty response from LLM",
            FieldName.LATENCY_MS: 0,
            FieldName.COST_USD: cost_usd,
        }
    try:
        parsed = json.loads(text)
        # Preserve fallback=True already set by a downstream provider (e.g. lmstudio HOLD
        # substitution from _hold_fallback_json) — don't overwrite it with False.
        parsed.setdefault(FieldName.FALLBACK, False)
        parsed[FieldName.TRACE_ID] = trace_id
        parsed.setdefault(FieldName.LATENCY_MS, 0)
        parsed.setdefault(FieldName.COST_USD, cost_usd)
        parsed.setdefault(FieldName.RISK_FACTORS, [])
        return parsed
    except json.JSONDecodeError as exc:
        return {
            FieldName.ACTION: AgentAction.REJECT,
            FieldName.TRACE_ID: trace_id,
            FieldName.FALLBACK: True,
            FieldName.ERROR: f"Invalid JSON from LLM: {exc}",
            FieldName.LATENCY_MS: 0,
            FieldName.COST_USD: cost_usd,
        }


def _get_provider_key(provider: str) -> str:
    keys = {
        FieldName.GROQ: settings.GROQ_API_KEY,
        FieldName.ANTHROPIC: getattr(settings, "ANTHROPIC_API_KEY", ""),
        FieldName.OPENAI: getattr(settings, "OPENAI_API_KEY", ""),
        FieldName.GEMINI: getattr(settings, "GEMINI_API_KEY", ""),
    }
    return keys.get(provider, "")


# Tracks the Groq model that actually served the most recent call, so a
# throttle-triggered fallback to the instruct model is attributed correctly in
# the decision's model_used label (the learning loop grades per-model). Best
# effort, consistent with the rest of the label resolution.
_last_groq_model: str | None = None


def _groq_backoff_delay(attempt: int) -> float:
    """Deterministic exponential backoff (no jitter), capped at MAX_BACKOFF_SECONDS."""
    return float(min(2**attempt, MAX_BACKOFF_SECONDS))


async def _groq_completion(
    *, system_prompt: str, prompt: str, max_tokens: int, temperature: float, trace_id: str
):
    """Call Groq with the capable model, degrading to the lighter instruct model
    when the primary is throttled, and retrying the pair with bounded backoff
    when BOTH are rate-limited (429 / quota / rate-limit).

    Parity with the Gemini path: a transient free-tier 429 no longer becomes an
    instant raise → REJECT. Only after the bounded retries are exhausted does it
    raise, so the agent still fails closed (never a blind trade). Non-rate-limit
    errors raise immediately — backoff only helps throttling.
    """
    global _last_groq_model
    from groq import AsyncGroq  # noqa: PLC0415

    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    primary = settings.GROQ_MODEL
    fallback = settings.GROQ_FALLBACK_MODEL
    retries = max(0, int(LLM_MAX_RETRIES))

    async def _create(model: str):
        return await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {FieldName.ROLE: "system", FieldName.CONTENT: system_prompt},
                {FieldName.ROLE: "user", FieldName.CONTENT: prompt},
            ],
        )

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        # Tier 1 — the capable primary model.
        try:
            response = await _create(primary)
            _last_groq_model = primary
            return response
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            last_exc = exc

        # Tier 2 — primary throttled → lighter instruct model (separate headroom).
        if fallback and fallback != primary:
            log_structured(
                "warning",
                "groq_primary_throttled_falling_back_to_instruct",
                trace_id=trace_id,
                primary_model=primary,
                fallback_model=fallback,
            )
            try:
                response = await _create(fallback)
                _last_groq_model = fallback
                return response
            except Exception as exc:
                if not _is_rate_limit_error(exc):
                    raise
                last_exc = exc

        # Both tiers throttled — bounded backoff, then retry the pair.
        if attempt < retries:
            delay = _groq_backoff_delay(attempt)
            log_structured(
                "warning",
                "groq_rate_limit_retry",
                attempt=attempt + 1,
                backoff_seconds=delay,
                trace_id=trace_id,
            )
            await asyncio.sleep(delay)

    # Retries exhausted — surface the throttle so the caller fails closed (REJECT).
    raise last_exc if last_exc is not None else RuntimeError("groq_rate_limited")


async def _call_groq(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    response = await _groq_completion(
        system_prompt=SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=LLM_MAX_TOKENS_TRADING,
        temperature=LLM_TEMPERATURE_TRADING,
        trace_id=trace_id,
    )
    text = response.choices[0].message.content
    tokens = (
        response.usage.prompt_tokens + response.usage.completion_tokens if response.usage else 0
    )
    return _parse_response(text, trace_id, 0.0), tokens, 0.0


async def _call_anthropic(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    import aiohttp  # noqa: PLC0415

    payload = {
        FieldName.MODEL: settings.ANTHROPIC_MODEL,
        FieldName.MAX_TOKENS: LLM_MAX_TOKENS_TRADING,
        FieldName.TEMPERATURE: LLM_TEMPERATURE_TRADING,
        FieldName.SYSTEM: SYSTEM_PROMPT,
        FieldName.MESSAGES: [{FieldName.ROLE: "user", FieldName.CONTENT: prompt}],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": getattr(settings, "ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        ) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"anthropic_status_{resp.status}")
            body = await resp.json()
    text = "".join(
        b.get(FieldName.TEXT, "")
        for b in body.get(FieldName.CONTENT, [])
        if b.get(FieldName.TYPE) == "text"
    )
    tokens = int(get_nested(body, "usage", "input_tokens", default=0)) + int(
        get_nested(body, "usage", "output_tokens", default=0)
    )
    cost_usd = round(tokens * 0.000003, 6)
    return _parse_response(text, trace_id, cost_usd), tokens, cost_usd


async def _call_openai(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    from openai import AsyncOpenAI  # noqa: PLC0415

    client = AsyncOpenAI(api_key=getattr(settings, "OPENAI_API_KEY", ""))
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        max_tokens=LLM_MAX_TOKENS_TRADING,
        temperature=LLM_TEMPERATURE_TRADING,
        messages=[
            {FieldName.ROLE: "system", FieldName.CONTENT: SYSTEM_PROMPT},
            {FieldName.ROLE: "user", FieldName.CONTENT: prompt},
        ],
    )
    text = response.choices[0].message.content
    tokens = response.usage.total_tokens if response.usage else 0
    cost_usd = round(tokens * 0.0000006, 6)
    return _parse_response(text, trace_id, cost_usd), tokens, cost_usd


def _extract_gemini_retry_delay(exc: Exception) -> float | None:
    """Parse the suggested retry delay from a Gemini ResourceExhausted message."""
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _gemini_backoff_delay(exc: Exception, attempt: int) -> float:
    """Deterministic backoff delay (no jitter/randomness)."""
    suggested = _extract_gemini_retry_delay(exc)
    if suggested is not None:
        return min(suggested, 120.0)
    return float(2**attempt)


def _is_gemini_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "429" in message
        or FieldName.RATE in message
        or FieldName.QUOTA in message
        or "resource exhausted" in message
    )


def _is_gemini_daily_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "requests/day" in message or "per day" in message or "daily limit" in message


def _is_gemini_model_not_found_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "404" in message or "not found" in message or "model not found" in message


def _get_gemini_api_key() -> str:
    api_key = (_get_provider_key("gemini") or "").strip()
    if not api_key:
        raise RuntimeError("missing_api_key: set GEMINI_API_KEY in environment")
    return api_key


def _get_gemini_sdk():
    from google import genai  # noqa: PLC0415
    from google.genai import errors as genai_errors  # noqa: PLC0415

    return genai, genai_errors


async def _call_gemini(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    genai, genai_errors = _get_gemini_sdk()
    client = genai.Client(api_key=_get_gemini_api_key())
    model_name = settings.GEMINI_MODEL
    retries = max(0, int(LLM_MAX_RETRIES))

    for attempt in range(retries + 1):
        # Acquire a rate-limiter slot before each attempt (not held during sleep).
        await _gemini_rate_limiter.acquire()
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=genai.types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            )
            text = response.text or ""
            usage = getattr(response, "usage_metadata", None)
            tokens = int(getattr(usage, "total_token_count", 0) or 0)
            return _parse_response(text, trace_id, 0.0), tokens, 0.0
        except genai_errors.ClientError as exc:
            if _is_gemini_model_not_found_error(exc):
                raise RuntimeError(
                    f"gemini_model_not_found: {model_name} (check GEMINI_MODEL env var)"
                ) from exc
            if _is_gemini_daily_quota_error(exc):
                raise RuntimeError("gemini_daily_quota_exhausted") from exc
            if _is_gemini_rate_limit_error(exc) and attempt < retries:
                delay = _gemini_backoff_delay(exc, attempt)
                log_structured(
                    "warning",
                    "gemini_rate_limit_retry",
                    attempt=attempt + 1,
                    backoff_seconds=delay,
                    trace_id=trace_id,
                )
                await asyncio.sleep(delay)
                continue
            raise
        except Exception as exc:
            if _is_gemini_rate_limit_error(exc) and attempt < retries:
                delay = _gemini_backoff_delay(exc, attempt)
                log_structured(
                    "warning",
                    "gemini_rate_limit_retry",
                    attempt=attempt + 1,
                    backoff_seconds=delay,
                    trace_id=trace_id,
                )
                await asyncio.sleep(delay)
                continue
            raise
    raise RuntimeError("gemini_call_failed_without_exception")


_PROVIDERS = {
    FieldName.GROQ: _call_groq,
    FieldName.ANTHROPIC: _call_anthropic,
    FieldName.OPENAI: _call_openai,
    FieldName.GEMINI: _call_gemini,
}

# Providers that authenticate via local connection rather than an API key.
# The api_key presence check in call_llm / call_llm_with_system is skipped
# for these provider names.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({LM_STUDIO_PROVIDER})


def _model_name_for(provider: str) -> str:
    """Configured model id for a given provider name."""
    if provider == FieldName.GROQ:
        return settings.GROQ_MODEL
    if provider == FieldName.ANTHROPIC:
        return settings.ANTHROPIC_MODEL
    if provider == FieldName.OPENAI:
        return settings.OPENAI_MODEL
    if provider == FieldName.GEMINI:
        return settings.GEMINI_MODEL
    if provider == LM_STUDIO_PROVIDER:
        return settings.LM_STUDIO_MODEL
    return provider


def active_provider_and_model() -> tuple[str, str]:
    """Return the (provider, model) the router is *configured* to use right now.

    Used as a best-effort default label. The actual provider for a given call —
    including an lmstudio→cloud fallback — is reported via the ``result_meta``
    out-parameter of :func:`call_llm_with_system`, which callers should prefer.
    """
    if _is_lmstudio_primary():
        return LM_STUDIO_PROVIDER, settings.LM_STUDIO_MODEL
    provider = settings.LLM_PROVIDER.lower().strip()
    return provider, _model_name_for(provider)


def active_model_label() -> str:
    """``"provider:model"`` label for the configured LLM, e.g. ``"gemini:gemini-1.5-flash"``."""
    provider, model = active_provider_and_model()
    return f"{provider}:{model}"


def _set_model_label(meta: dict | None, provider: str) -> None:
    """Record the *actually-used* provider:model on the caller's result_meta.

    This is how a decision is attributed to the real provider even when an
    lmstudio-primary request transparently fell back to a cloud provider.
    """
    if meta is not None:
        # For Groq, prefer the model that actually served the call — a throttle
        # fallback may have downgraded the capable model to the instruct one,
        # and the learning loop grades per-model, so the label must be truthful.
        if provider == FieldName.GROQ and _last_groq_model:
            model = _last_groq_model
        else:
            model = _model_name_for(provider)
        meta["model_label"] = f"{provider}:{model}"


def _find_cloud_fallback() -> str | None:
    """Return the first cloud provider that has an API key configured.

    Used when LLM_PROVIDER=lmstudio and LLM_FALLBACK_ENABLED=true.
    """
    candidates = [
        ("groq", settings.GROQ_API_KEY or ""),
        ("gemini", getattr(settings, "GEMINI_API_KEY", "") or ""),
        ("anthropic", getattr(settings, "ANTHROPIC_API_KEY", "") or ""),
        ("openai", getattr(settings, "OPENAI_API_KEY", "") or ""),
    ]
    for p, key in candidates:
        if key.strip():
            return p
    return None


async def _call_provider_raw(
    provider: str, prompt: str, system_prompt: str, trace_id: str
) -> tuple[str, int, float]:
    """Call a provider and return raw text (not parsed as trading JSON)."""
    if provider == "groq":
        response = await _groq_completion(
            system_prompt=system_prompt,
            prompt=prompt,
            max_tokens=LLM_MAX_TOKENS_ANALYSIS,
            temperature=LLM_TEMPERATURE_ANALYSIS,
            trace_id=trace_id,
        )
        text = response.choices[0].message.content or ""
        tokens = (
            response.usage.prompt_tokens + response.usage.completion_tokens if response.usage else 0
        )
        return text, tokens, 0.0

    if provider == "anthropic":
        import aiohttp  # noqa: PLC0415

        payload = {
            FieldName.MODEL: settings.ANTHROPIC_MODEL,
            FieldName.MAX_TOKENS: LLM_MAX_TOKENS_ANALYSIS,
            FieldName.TEMPERATURE: LLM_TEMPERATURE_ANALYSIS,
            FieldName.SYSTEM: system_prompt,
            FieldName.MESSAGES: [{FieldName.ROLE: "user", FieldName.CONTENT: prompt}],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": getattr(settings, "ANTHROPIC_API_KEY", ""),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            ) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"anthropic_status_{resp.status}")
                body = await resp.json()
        text = "".join(
            b.get(FieldName.TEXT, "")
            for b in body.get(FieldName.CONTENT, [])
            if b.get(FieldName.TYPE) == "text"
        )
        tokens = int(get_nested(body, "usage", "input_tokens", default=0)) + int(
            get_nested(body, "usage", "output_tokens", default=0)
        )
        return text, tokens, round(tokens * 0.000003, 6)

    if provider == "openai":
        from openai import AsyncOpenAI  # noqa: PLC0415

        client = AsyncOpenAI(api_key=getattr(settings, "OPENAI_API_KEY", ""))
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            max_tokens=LLM_MAX_TOKENS_ANALYSIS,
            temperature=LLM_TEMPERATURE_ANALYSIS,
            messages=[
                {FieldName.ROLE: "system", FieldName.CONTENT: system_prompt},
                {FieldName.ROLE: "user", FieldName.CONTENT: prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return text, tokens, round(tokens * 0.0000006, 6)

    if provider == "gemini":
        genai, genai_errors = _get_gemini_sdk()
        client = genai.Client(api_key=_get_gemini_api_key())
        model_name = settings.GEMINI_MODEL
        retries = max(0, int(LLM_MAX_RETRIES))

        for attempt in range(retries + 1):
            await _gemini_rate_limiter.acquire()
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(system_instruction=system_prompt),
                )
                text = response.text or ""
                usage = getattr(response, "usage_metadata", None)
                tokens = int(getattr(usage, "total_token_count", 0) or 0)
                return text, tokens, 0.0
            except genai_errors.ClientError as exc:
                if _is_gemini_model_not_found_error(exc):
                    raise RuntimeError(
                        f"gemini_model_not_found: {model_name} (check GEMINI_MODEL env var)"
                    ) from exc
                if _is_gemini_daily_quota_error(exc):
                    raise RuntimeError("gemini_daily_quota_exhausted") from exc
                if _is_gemini_rate_limit_error(exc) and attempt < retries:
                    delay = _gemini_backoff_delay(exc, attempt)
                    log_structured(
                        "warning",
                        "gemini_rate_limit_retry",
                        attempt=attempt + 1,
                        backoff_seconds=delay,
                        trace_id=trace_id,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except Exception as exc:
                if _is_gemini_rate_limit_error(exc) and attempt < retries:
                    delay = _gemini_backoff_delay(exc, attempt)
                    log_structured(
                        "warning",
                        "gemini_rate_limit_retry",
                        attempt=attempt + 1,
                        backoff_seconds=delay,
                        trace_id=trace_id,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise RuntimeError("gemini_raw_call_failed_without_exception")

    raise RuntimeError(f"unknown_provider: '{provider}'")


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "429" in msg
        or "rate limit" in msg
        or FieldName.RATELIMIT in msg
        or FieldName.QUOTA in msg
        or "resource exhausted" in msg
        or "too many requests" in msg
    )


def _is_timeout_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return FieldName.TIMEOUT in msg or "timed out" in msg or FieldName.DEADLINE in msg


async def _inter_call_delay() -> None:
    """Sleep the active inter-call delay.

    GradeAgent can raise this dynamically (via llm_metrics.set_call_delay_ms)
    when it detects sustained rate-limiting; the change takes effect on the
    next call without any restart.
    """
    delay_ms = llm_metrics.get_call_delay_ms()
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)


async def call_llm_with_system(
    prompt: str,
    system_prompt: str,
    trace_id: str,
    *,
    task_type: str | None = None,
    result_meta: dict | None = None,
) -> tuple[str, int, float]:
    """Call the configured LLM provider with a custom system prompt.

    When LLM_PROVIDER=lmstudio or LM_STUDIO_ENABLED=true, LM Studio is
    attempted first.  Fallback behaviour depends on LLM_FALLBACK_ENABLED:
      - LLM_PROVIDER=lmstudio + LLM_FALLBACK_ENABLED=false (recommended):
        failures raise immediately; Gemini is never called.
      - LLM_PROVIDER=lmstudio + LLM_FALLBACK_ENABLED=true:
        falls back to the first cloud provider with an API key configured.
      - LM_STUDIO_ENABLED=true with a cloud LLM_PROVIDER:
        falls back to the configured cloud provider (legacy behaviour).

    task_type selects the LM Studio token budget (price_analysis /
    trade_execution / health_check).  Ignored for cloud providers.

    Returns (raw_text, tokens_used, cost_usd). The caller is responsible
    for parsing the response.
    """
    lm_primary = _is_lmstudio_primary()
    # Bypass cooldown when there is no usable cloud path: fallback disabled, or enabled
    # but no cloud API key configured.  The cooldown only makes sense when there is a
    # live cloud alternative to route to — without one, suppressing local retries just
    # extends the outage.
    _cloud_available = settings.LLM_FALLBACK_ENABLED and bool(_find_cloud_fallback())
    use_lmstudio = (lm_primary and not _cloud_available) or (
        (lm_primary or settings.LM_STUDIO_ENABLED) and should_try_local()
    )

    if use_lmstudio:
        try:
            t0 = _time.monotonic()
            result = await call_lmstudio(
                prompt,
                system_prompt,
                trace_id,
                task_type=task_type or LLM_TASK_PRICE_ANALYSIS,
                parse_json=False,  # freeform text — caller handles parsing
            )
            llm_metrics.record_success(latency_ms=(_time.monotonic() - t0) * 1000)
            _set_model_label(result_meta, LM_STUDIO_PROVIDER)
            return result
        except LMStudioUnavailableError as exc:
            if lm_primary and not settings.LLM_FALLBACK_ENABLED:
                msg = f"lmstudio_unavailable: {exc}"
                llm_metrics.record_error(message=msg, kind="lmstudio_unavailable")
                raise RuntimeError(msg) from exc
            log_structured(
                "info",
                "lmstudio_unavailable_falling_back",
                reason=str(exc),
                trace_id=trace_id,
            )

    # Determine cloud provider — when lmstudio is primary, find a configured fallback.
    if lm_primary:
        provider = _find_cloud_fallback()
        if not provider:
            msg = (
                "lmstudio_unavailable_no_fallback: LM Studio failed and "
                "LLM_FALLBACK_ENABLED=true but no cloud API key is configured. "
                "Set GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY."
            )
            llm_metrics.record_error(message=msg, kind="config")
            raise RuntimeError(msg)
    else:
        provider = settings.LLM_PROVIDER.lower().strip()

    api_key = _get_provider_key(provider)
    if not api_key and provider not in _LOCAL_PROVIDERS:
        msg = f"missing_api_key: set {provider.upper()}_API_KEY in environment"
        llm_metrics.record_error(message=msg, kind="config")
        raise RuntimeError(msg)
    await _inter_call_delay()
    t0 = _time.monotonic()
    try:
        log_structured("info", "Calling LLM with custom prompt", provider=provider)
        result = await _call_provider_raw(provider, prompt, system_prompt, trace_id)
        latency_ms = (_time.monotonic() - t0) * 1000
        llm_metrics.record_success(latency_ms=latency_ms)
        _set_model_label(result_meta, provider)
        log_structured(
            "info", "LLM custom call succeeded", provider=provider, latency_ms=round(latency_ms)
        )
        return result
    except Exception as exc:
        if _is_rate_limit_error(exc):
            llm_metrics.record_rate_limit()
            log_structured("warning", "LLM rate limit hit", provider=provider, exc_info=True)
        elif _is_timeout_error(exc):
            llm_metrics.record_timeout()
            log_structured("warning", "LLM timeout", provider=provider, exc_info=True)
        else:
            llm_metrics.record_error(message=str(exc), kind="provider_error")
            log_structured("warning", "LLM custom call failed", provider=provider, exc_info=True)
        raise


async def call_llm(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    """Call configured LLM provider and return a parsed trading decision.

    When LLM_PROVIDER=lmstudio or LM_STUDIO_ENABLED=true, LM Studio is
    attempted first.  Fallback behaviour depends on LLM_FALLBACK_ENABLED:
      - LLM_PROVIDER=lmstudio + LLM_FALLBACK_ENABLED=false (recommended):
        failures raise immediately; Gemini is never called.
      - LLM_PROVIDER=lmstudio + LLM_FALLBACK_ENABLED=true:
        falls back to the first cloud provider with an API key configured.
      - LM_STUDIO_ENABLED=true with a cloud LLM_PROVIDER:
        falls back to the configured cloud provider (legacy behaviour).

    To switch the cloud provider set two env vars:
      LLM_PROVIDER=groq
      GROQ_API_KEY=gsk_...
    """
    lm_primary = _is_lmstudio_primary()
    # Bypass cooldown when there is no usable cloud path: fallback disabled, or enabled
    # but no cloud API key configured.  The cooldown only makes sense when there is a
    # live cloud alternative to route to — without one, suppressing local retries just
    # extends the outage.
    _cloud_available = settings.LLM_FALLBACK_ENABLED and bool(_find_cloud_fallback())
    use_lmstudio = (lm_primary and not _cloud_available) or (
        (lm_primary or settings.LM_STUDIO_ENABLED) and should_try_local()
    )

    if use_lmstudio:
        try:
            t0 = _time.monotonic()
            raw_text, tokens, cost = await call_lmstudio(prompt, SYSTEM_PROMPT, trace_id)
            latency_ms = (_time.monotonic() - t0) * 1000
            parsed = _parse_response(raw_text, trace_id, cost)
            if not parsed.get(FieldName.FALLBACK):
                parsed[FieldName.PROVIDER] = LM_STUDIO_PROVIDER
                llm_metrics.record_success(latency_ms=latency_ms)
                return parsed, tokens, cost
            _record_lm_failure("parse_returned_fallback")
            if lm_primary and not settings.LLM_FALLBACK_ENABLED:
                err = parsed.get(FieldName.ERROR, "malformed response")
                msg = f"lmstudio_parse_failed: {err}"
                llm_metrics.record_error(message=msg, kind="lmstudio_parse_failed")
                raise RuntimeError(msg)
            log_structured(
                "info",
                "lmstudio_parse_failed_falling_back",
                error=parsed.get(FieldName.ERROR),
                trace_id=trace_id,
            )
        except LMStudioUnavailableError as exc:
            if lm_primary and not settings.LLM_FALLBACK_ENABLED:
                msg = f"lmstudio_unavailable: {exc}"
                llm_metrics.record_error(message=msg, kind="lmstudio_unavailable")
                raise RuntimeError(msg) from exc
            log_structured(
                "info",
                "lmstudio_unavailable_falling_back",
                reason=str(exc),
                trace_id=trace_id,
            )

    # Determine cloud provider — when lmstudio is primary, find a configured fallback.
    if lm_primary:
        provider = _find_cloud_fallback()
        if not provider:
            msg = (
                "lmstudio_unavailable_no_fallback: LM Studio failed and "
                "LLM_FALLBACK_ENABLED=true but no cloud API key is configured. "
                "Set GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY."
            )
            llm_metrics.record_error(message=msg, kind="config")
            raise RuntimeError(msg)
    else:
        provider = settings.LLM_PROVIDER.lower().strip()

    if provider not in _PROVIDERS:
        raise RuntimeError(f"unknown_provider: '{provider}' - supported: {list(_PROVIDERS.keys())}")
    api_key = _get_provider_key(provider)
    if not api_key and provider not in _LOCAL_PROVIDERS:
        msg = f"missing_api_key: set {provider.upper()}_API_KEY in environment"
        llm_metrics.record_error(message=msg, kind="config")
        raise RuntimeError(msg)
    await _inter_call_delay()
    t0 = _time.monotonic()
    try:
        log_structured("info", "Calling LLM", provider=provider)
        result = await _PROVIDERS[provider](prompt, trace_id)
        latency_ms = (_time.monotonic() - t0) * 1000
        llm_metrics.record_success(latency_ms=latency_ms)
        log_structured("info", "LLM succeeded", provider=provider, latency_ms=round(latency_ms))
        return result
    except Exception as exc:
        if _is_rate_limit_error(exc):
            llm_metrics.record_rate_limit()
            log_structured("warning", "LLM rate limit hit", provider=provider, exc_info=True)
        elif _is_timeout_error(exc):
            llm_metrics.record_timeout()
            log_structured("warning", "LLM timeout", provider=provider, exc_info=True)
        else:
            llm_metrics.record_error(message=str(exc), kind="provider_error")
            log_structured("warning", "LLM call failed", provider=provider, exc_info=True)
        raise
