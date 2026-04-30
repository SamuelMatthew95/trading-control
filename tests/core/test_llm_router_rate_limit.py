"""Tests for Gemini rate limit handling in api/services/llm_router.py."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


@pytest.mark.asyncio
async def test_call_gemini_success_no_sleep():
    """Success on first try — asyncio.sleep never called."""
    fake_response = _make_fake_response('{"action": "hold"}')

    with (
        patch("api.services.llm_router._get_gemini_api_key", return_value="fake-key"),
        patch.dict("sys.modules", {"google.generativeai": MagicMock()}),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        import google.generativeai as genai  # noqa: F401 — imported for patching

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
        patch.dict("sys.modules", {"google.generativeai": MagicMock()}),
        patch("api.services.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("api.services.llm_router.asyncio.to_thread", mock_thread),
        patch("api.services.llm_router.settings") as mock_settings,
    ):
        mock_settings.LLM_MAX_RETRIES = 2

        from importlib import reload

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
        patch.dict("sys.modules", {"google.generativeai": MagicMock()}),
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
        patch.dict("sys.modules", {"google.generativeai": MagicMock()}),
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
        patch.dict("sys.modules", {"google.generativeai": MagicMock()}),
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
        patch.dict("sys.modules", {"google.generativeai": MagicMock()}),
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
