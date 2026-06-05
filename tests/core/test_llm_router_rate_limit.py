"""Tests for Gemini rate limit handling in api/services/llm_router.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # noqa: E402

from api.services.llm_router import _extract_gemini_retry_delay

# ---------------------------------------------------------------------------
# _extract_gemini_retry_delay
# ---------------------------------------------------------------------------


def test_extract_delay_with_realistic_gemini_message():
    exc = Exception("Resource has been exhausted. Please retry in 49.549664967s after a cooldown.")
    result = _extract_gemini_retry_delay(exc)
    assert result == pytest.approx(49.549664967)


def test_extract_delay_returns_none_when_no_hint():
    exc = Exception("Resource exhausted (quota exceeded for this project).")
    result = _extract_gemini_retry_delay(exc)
    assert result is None


def test_extract_delay_integer_seconds():
    exc = Exception("Rate limited. Retry in 30s please.")
    result = _extract_gemini_retry_delay(exc)
    assert result == pytest.approx(30.0)
    assert isinstance(result, float)


# ---------------------------------------------------------------------------
# _call_gemini
# ---------------------------------------------------------------------------


def _make_fake_response(text: str = '{"action": "hold"}'):
    resp = MagicMock()
    resp.text = text
    resp.usage_metadata = None
    return resp


def _make_fake_gemini_sdk():
    fake_genai = MagicMock()
    fake_genai.Client.return_value = MagicMock(models=MagicMock(generate_content=MagicMock()))
    fake_genai.types.GenerateContentConfig = MagicMock()
    fake_errors = MagicMock()
    fake_errors.ClientError = Exception
    return fake_genai, fake_errors


@pytest.mark.asyncio
async def test_call_gemini_success_no_sleep():
    """Success on first try — asyncio.sleep never called."""
    fake_response = _make_fake_response('{"action": "hold"}')

    with (
        patch("api.services.llm_router._get_gemini_api_key", return_value="fake-key"),
        patch("api.services.llm_router._get_gemini_sdk", return_value=_make_fake_gemini_sdk()),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_thread.return_value = fake_response

        from api.services.llm_router import _call_gemini

        result, tokens, cost = await _call_gemini("test prompt", "trace-001")

    mock_sleep.assert_not_called()
    assert result["action"] == "hold"


@pytest.mark.asyncio
async def test_call_gemini_rate_limit_then_success():
    """Rate limit on attempt 0, success on attempt 1 → sleep called once with extracted delay."""
    rate_exc = Exception("resource exhausted. Please retry in 15.5s")
    good_response = _make_fake_response('{"action": "buy"}')

    mock_thread = AsyncMock(side_effect=[rate_exc, good_response])

    with (
        patch("api.services.llm_router._get_gemini_api_key", return_value="fake-key"),
        patch("api.services.llm_router._get_gemini_sdk", return_value=_make_fake_gemini_sdk()),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", mock_thread),
        patch("api.services.llm_router.settings") as mock_settings,
    ):
        mock_settings.LLM_MAX_RETRIES = 2

        import api.services.llm_router as router_mod

        result, tokens, cost = await router_mod._call_gemini("test prompt", "trace-002")

    mock_sleep.assert_called_once()
    sleep_delay = mock_sleep.call_args[0][0]
    assert sleep_delay == pytest.approx(15.5)
    assert result["action"] == "buy"


@pytest.mark.asyncio
async def test_call_gemini_rate_limit_all_retries_raises():
    """All retries exhausted → original exception raised, sleep called `retries` times."""
    rate_exc = Exception("429 resource exhausted. Please retry in 10s")

    with (
        patch("api.services.llm_router._get_gemini_api_key", return_value="fake-key"),
        patch("api.services.llm_router._get_gemini_sdk", return_value=_make_fake_gemini_sdk()),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", AsyncMock(side_effect=rate_exc)),
        patch("api.services.llm_router.settings") as mock_settings,
    ):
        mock_settings.LLM_MAX_RETRIES = 2

        import api.services.llm_router as router_mod

        with pytest.raises(Exception, match="resource exhausted"):
            await router_mod._call_gemini("test prompt", "trace-003")

    # retries=2 means attempts 0..2, sleep on attempts 0 and 1 (not on last)
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_call_gemini_no_hint_falls_back_to_exponential():
    """Rate limit with no retry hint → delay is 2**attempt (not a parsed value)."""
    rate_exc = Exception("rate limit exceeded (quota)")
    good_response = _make_fake_response('{"action": "sell"}')

    mock_thread = AsyncMock(side_effect=[rate_exc, good_response])

    with (
        patch("api.services.llm_router._get_gemini_api_key", return_value="fake-key"),
        patch("api.services.llm_router._get_gemini_sdk", return_value=_make_fake_gemini_sdk()),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", mock_thread),
        patch("api.services.llm_router.settings") as mock_settings,
    ):
        mock_settings.LLM_MAX_RETRIES = 2

        import api.services.llm_router as router_mod

        await router_mod._call_gemini("test prompt", "trace-004")

    mock_sleep.assert_called_once()
    # attempt=0 → 2**0 = 1
    assert mock_sleep.call_args[0][0] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_call_gemini_delay_capped_at_120():
    """Extracted delay > 120s is capped at 120s."""
    rate_exc = Exception("resource exhausted. Please retry in 200s")
    good_response = _make_fake_response('{"action": "hold"}')

    mock_thread = AsyncMock(side_effect=[rate_exc, good_response])

    with (
        patch("api.services.llm_router._get_gemini_api_key", return_value="fake-key"),
        patch("api.services.llm_router._get_gemini_sdk", return_value=_make_fake_gemini_sdk()),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", mock_thread),
        patch("api.services.llm_router.settings") as mock_settings,
    ):
        mock_settings.LLM_MAX_RETRIES = 2

        import api.services.llm_router as router_mod

        await router_mod._call_gemini("test prompt", "trace-005")

    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(120.0)


# ---------------------------------------------------------------------------
# _call_provider_raw (gemini branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_provider_raw_gemini_rate_limit_then_success():
    """_call_provider_raw gemini branch: rate limit then success → sleep called once."""
    rate_exc = Exception("resource exhausted. Please retry in 25.0s")
    good_response = _make_fake_response("raw text output")

    mock_thread = AsyncMock(side_effect=[rate_exc, good_response])

    with (
        patch("api.services.llm_router._get_gemini_api_key", return_value="fake-key"),
        patch("api.services.llm_router._get_gemini_sdk", return_value=_make_fake_gemini_sdk()),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", mock_thread),
        patch("api.services.llm_router.settings") as mock_settings,
    ):
        mock_settings.LLM_MAX_RETRIES = 2

        import api.services.llm_router as router_mod

        text, tokens, cost = await router_mod._call_provider_raw(
            "gemini", "test prompt", "system prompt", "trace-006"
        )

    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(25.0)
    assert text == "raw text output"


# ---------------------------------------------------------------------------
# Groq throttle → instruct-model fallback
# ---------------------------------------------------------------------------


def _make_groq_response(text: str = "ok", prompt_tokens: int = 10, completion_tokens: int = 5):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    resp.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return resp


def _make_fake_groq_module(create_side_effect):
    fake_mod = MagicMock()
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=create_side_effect)
    fake_mod.AsyncGroq.return_value = client
    return fake_mod


@pytest.mark.asyncio
async def test_groq_falls_back_to_instruct_when_primary_throttled(monkeypatch):
    """A 429 on the capable Groq model transparently retries on the instruct
    model instead of raising — preventing the skip_reasoning cascade that
    starved the learning loop."""
    from api.config import settings
    from api.services import llm_router

    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")

    def _create(*args, **kwargs):
        if kwargs.get("model") == "llama-3.3-70b-versatile":
            raise Exception("Error code: 429 - rate limit exceeded")
        return _make_groq_response("fallback-text")

    with patch.dict("sys.modules", {"groq": _make_fake_groq_module(_create)}):
        text, tokens, cost = await llm_router._call_provider_raw(
            "groq", "prompt", "system", "trace-1"
        )

    assert text == "fallback-text"
    assert tokens == 15
    assert llm_router._last_groq_model == "llama-3.1-8b-instant"


@pytest.mark.asyncio
async def test_groq_uses_capable_model_when_healthy(monkeypatch):
    """No throttle — the capable primary model serves the call and is labelled."""
    from api.config import settings
    from api.services import llm_router

    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")

    calls = []

    def _create(*args, **kwargs):
        calls.append(kwargs.get("model"))
        return _make_groq_response("primary-text")

    with patch.dict("sys.modules", {"groq": _make_fake_groq_module(_create)}):
        text, _tokens, _cost = await llm_router._call_provider_raw(
            "groq", "prompt", "system", "trace-2"
        )

    assert text == "primary-text"
    assert calls == ["llama-3.3-70b-versatile"]  # fallback never invoked
    assert llm_router._last_groq_model == "llama-3.3-70b-versatile"


@pytest.mark.asyncio
async def test_groq_non_rate_limit_error_does_not_fall_back(monkeypatch):
    """A non-throttle error (e.g. auth) must propagate, not silently downgrade."""
    from api.config import settings
    from api.services import llm_router

    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")

    def _create(*args, **kwargs):
        raise Exception("invalid_api_key: authentication failed")

    with patch.dict("sys.modules", {"groq": _make_fake_groq_module(_create)}):
        with pytest.raises(Exception, match="authentication failed"):
            await llm_router._call_provider_raw("groq", "prompt", "system", "trace-3")


@pytest.mark.asyncio
async def test_groq_retries_with_backoff_when_both_tiers_throttled(monkeypatch):
    """When BOTH the capable and instruct models are 429'd, Groq backs off and
    retries the pair (parity with Gemini) instead of instantly raising → REJECT.

    REGRESSION: a transient free-tier rate-limit on both tiers used to raise
    immediately, turning ~87% of decisions into fallback:reject_signal and
    starving the learning loop. Now it succeeds on a later attempt.
    """
    from unittest.mock import AsyncMock

    from api.config import settings
    from api.services import llm_router

    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm_router, "LLM_MAX_RETRIES", 2)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(llm_router.asyncio, "sleep", sleep_mock)

    calls = {"n": 0}

    def _create(*args, **kwargs):
        calls["n"] += 1
        # First three create calls throttle (attempt-0 primary+fallback, then
        # attempt-1 primary); the fourth (attempt-1 fallback) succeeds.
        if calls["n"] <= 3:
            raise Exception("Error code: 429 - rate limit exceeded")
        return _make_groq_response("recovered-text")

    with patch.dict("sys.modules", {"groq": _make_fake_groq_module(_create)}):
        text, _tokens, _cost = await llm_router._call_provider_raw(
            "groq", "prompt", "system", "trace-retry"
        )

    assert text == "recovered-text"
    assert sleep_mock.await_count >= 1  # at least one backoff slept before recovery


@pytest.mark.asyncio
async def test_groq_raises_after_retries_exhausted_so_agent_fails_closed(monkeypatch):
    """If every attempt is throttled, Groq still raises after the bounded retries
    so the agent fails closed (REJECT) — backoff lifts success, never fabricates a
    trade."""
    from unittest.mock import AsyncMock

    from api.config import settings
    from api.services import llm_router

    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm_router, "LLM_MAX_RETRIES", 1)
    monkeypatch.setattr(llm_router.asyncio, "sleep", AsyncMock())

    def _create(*args, **kwargs):
        raise Exception("Error code: 429 - rate limit exceeded")

    with patch.dict("sys.modules", {"groq": _make_fake_groq_module(_create)}):
        with pytest.raises(Exception, match="429"):
            await llm_router._call_provider_raw("groq", "prompt", "system", "trace-exhaust")
