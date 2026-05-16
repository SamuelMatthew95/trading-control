"""LLM provider router - switch via LLM_PROVIDER + matching API key."""

from __future__ import annotations

import asyncio
import json
import re
import time as _time

from api.config import settings
from api.constants import AgentAction, FieldName
from api.observability import log_structured
from api.services.llm_metrics import llm_metrics
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
        parsed[FieldName.FALLBACK] = False
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


async def _call_groq(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    from groq import AsyncGroq  # noqa: PLC0415

    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    response = await client.chat.completions.create(
        model=settings.GROQ_MODEL,
        max_tokens=300,
        temperature=0.2,
        messages=[
            {FieldName.ROLE: "system", FieldName.CONTENT: SYSTEM_PROMPT},
            {FieldName.ROLE: "user", FieldName.CONTENT: prompt},
        ],
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
        FieldName.MAX_TOKENS: 300,
        FieldName.TEMPERATURE: 0.2,
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
        max_tokens=300,
        temperature=0.2,
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
    retries = max(0, int(getattr(settings, "LLM_MAX_RETRIES", 2)))

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


async def _call_provider_raw(
    provider: str, prompt: str, system_prompt: str, trace_id: str
) -> tuple[str, int, float]:
    """Call a provider and return raw text (not parsed as trading JSON)."""
    if provider == "groq":
        from groq import AsyncGroq  # noqa: PLC0415

        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        response = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            max_tokens=800,
            temperature=0.3,
            messages=[
                {FieldName.ROLE: "system", FieldName.CONTENT: system_prompt},
                {FieldName.ROLE: "user", FieldName.CONTENT: prompt},
            ],
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
            FieldName.MAX_TOKENS: 800,
            FieldName.TEMPERATURE: 0.3,
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
            max_tokens=800,
            temperature=0.3,
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
        retries = max(0, int(getattr(settings, "LLM_MAX_RETRIES", 2)))

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
    prompt: str, system_prompt: str, trace_id: str
) -> tuple[str, int, float]:
    """Call the configured LLM provider with a custom system prompt.

    Returns (raw_text, tokens_used, cost_usd). The caller is responsible
    for parsing the response.
    """
    provider = settings.LLM_PROVIDER.lower().strip()
    api_key = _get_provider_key(provider)
    if not api_key:
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
    """
    Call configured LLM provider.
    To switch provider set 2 env vars:
      LLM_PROVIDER=groq
      GROQ_API_KEY=gsk_...
    """
    provider = settings.LLM_PROVIDER.lower().strip()
    if provider not in _PROVIDERS:
        raise RuntimeError(f"unknown_provider: '{provider}' - supported: {list(_PROVIDERS.keys())}")
    api_key = _get_provider_key(provider)
    if not api_key:
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
