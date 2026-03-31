"""LLM provider router - switch via LLM_PROVIDER + matching API key."""

from __future__ import annotations

import json

from api.config import settings
from api.observability import log_structured

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
            "action": "reject",
            "trace_id": trace_id,
            "fallback": True,
            "error": "Empty response from LLM",
            "latency_ms": 0,
            "cost_usd": cost_usd,
        }
    try:
        parsed = json.loads(text)
        parsed["fallback"] = False
        parsed["trace_id"] = trace_id
        parsed.setdefault("latency_ms", 0)
        parsed.setdefault("cost_usd", cost_usd)
        parsed.setdefault("risk_factors", [])
        return parsed
    except json.JSONDecodeError as exc:
        return {
            "action": "reject",
            "trace_id": trace_id,
            "fallback": True,
            "error": f"Invalid JSON from LLM: {exc}",
            "latency_ms": 0,
            "cost_usd": cost_usd,
        }


def _get_provider_key(provider: str) -> str:
    keys = {
        "groq": settings.GROQ_API_KEY,
        "anthropic": getattr(settings, "ANTHROPIC_API_KEY", ""),
        "openai": getattr(settings, "OPENAI_API_KEY", ""),
    }
    return keys.get(provider, "")


async def _call_groq(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    response = await client.chat.completions.create(
        model=settings.GROQ_MODEL,
        max_tokens=300,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    text = response.choices[0].message.content
    tokens = (
        response.usage.prompt_tokens + response.usage.completion_tokens if response.usage else 0
    )
    return _parse_response(text, trace_id, 0.0), tokens, 0.0


async def _call_anthropic(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    import aiohttp

    payload = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": 300,
        "temperature": 0.2,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
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
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    tokens = int(body.get("usage", {}).get("input_tokens", 0)) + int(
        body.get("usage", {}).get("output_tokens", 0)
    )
    cost_usd = round(tokens * 0.000003, 6)
    return _parse_response(text, trace_id, cost_usd), tokens, cost_usd


async def _call_openai(prompt: str, trace_id: str) -> tuple[dict, int, float]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=getattr(settings, "OPENAI_API_KEY", ""))
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        max_tokens=300,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    text = response.choices[0].message.content
    tokens = response.usage.total_tokens if response.usage else 0
    cost_usd = round(tokens * 0.0000006, 6)
    return _parse_response(text, trace_id, cost_usd), tokens, cost_usd


# To add Gemini: pip install google-generativeai, add GEMINI_API_KEY to config,
# implement _call_gemini(), and add "gemini": _call_gemini to _PROVIDERS
_PROVIDERS = {
    "groq": _call_groq,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
}


async def _call_provider_raw(
    provider: str, prompt: str, system_prompt: str, trace_id: str
) -> tuple[str, int, float]:
    """Call a provider and return raw text (not parsed as trading JSON)."""
    if provider == "groq":
        from groq import AsyncGroq

        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        response = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            max_tokens=800,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        tokens = (
            response.usage.prompt_tokens + response.usage.completion_tokens if response.usage else 0
        )
        return text, tokens, 0.0

    if provider == "anthropic":
        import aiohttp

        payload = {
            "model": settings.ANTHROPIC_MODEL,
            "max_tokens": 800,
            "temperature": 0.3,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
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
            b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"
        )
        tokens = int(body.get("usage", {}).get("input_tokens", 0)) + int(
            body.get("usage", {}).get("output_tokens", 0)
        )
        return text, tokens, round(tokens * 0.000003, 6)

    if provider == "openai":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=getattr(settings, "OPENAI_API_KEY", ""))
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            max_tokens=800,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return text, tokens, round(tokens * 0.0000006, 6)

    raise RuntimeError(f"unknown_provider: '{provider}'")


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
        raise RuntimeError(f"missing_api_key: set {provider.upper()}_API_KEY in environment")
    try:
        log_structured("info", "Calling LLM with custom prompt", provider=provider)
        result = await _call_provider_raw(provider, prompt, system_prompt, trace_id)
        log_structured("info", "LLM custom call succeeded", provider=provider)
        return result
    except Exception as exc:
        error_str = str(exc).lower()
        if "rate" in error_str or "429" in error_str or "limit" in error_str:
            log_structured("warning", "LLM rate limit hit", provider=provider, exc_info=True)
        else:
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
        raise RuntimeError(f"missing_api_key: set {provider.upper()}_API_KEY in environment")
    try:
        log_structured("info", "Calling LLM", provider=provider)
        result = await _PROVIDERS[provider](prompt, trace_id)
        log_structured("info", "LLM succeeded", provider=provider)
        return result
    except Exception as exc:
        error_str = str(exc).lower()
        if "rate" in error_str or "429" in error_str or "limit" in error_str:
            log_structured("warning", "LLM rate limit hit", provider=provider, exc_info=True)
        else:
            log_structured("warning", "LLM call failed", provider=provider, exc_info=True)
        raise
