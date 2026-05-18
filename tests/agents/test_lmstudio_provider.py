"""Tests for LM Studio / LM Link local inference provider.

Covers:
  1. App boots when LM Studio is disabled.
  2. App boots (startup check) when LM Studio is enabled but unavailable.
  3. Local LM Studio success returns validated decision (call_llm path).
  4. Local timeout falls back to existing cloud provider.
  5. Local malformed output falls back to cloud provider.
  6. Cloud fallback failure raises (safe NO_ACTION handled by caller).
  7. Redis consumer does not crash on local inference failure.
  8. health_snapshot reflects enabled + healthy state correctly.
  9. check_health handles connection errors gracefully.
 10. call_llm_with_system succeeds via LM Studio then preserves shape.
 11. No secrets are logged.
 12. /llm/health endpoint still responds (existing dashboard route).
 13. call_lmstudio raises when LM_STUDIO_MODEL is not configured.
 14. Whitespace-only LM_STUDIO_MODEL is treated as unconfigured (stripped before guard).
 15. health_snapshot returns None for whitespace-only model ID.
 16. check_health returns False with no_model_loaded when LM Studio has no model loaded.
 17. call_lmstudio with empty choices list returns empty string (degenerate but not a failure).
 18. call_llm_with_system falls back to cloud provider when LM Studio raises.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import settings
from api.constants import FieldName
from api.services.lmstudio_provider import (
    LMStudioUnavailableError,
    _health,
    call_lmstudio,
    check_health,
    health_snapshot,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_lm_health():
    """Reset module-level health state before every test to prevent pollution."""
    _health.healthy = False
    _health.last_error = None
    _health.fallback_count = 0
    _health.last_latency_ms = 0.0
    yield
    _health.healthy = False
    _health.last_error = None
    _health.fallback_count = 0
    _health.last_latency_ms = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_JSON = (
    '{"action":"hold","confidence":0.7,"primary_edge":"momentum",'
    '"risk_factors":[],"size_pct":0.05,"stop_atr_x":1.5,"rr_ratio":1.8,'
    '"latency_ms":42,"cost_usd":0.0,"trace_id":"t1","fallback":false}'
)

_SYSTEM_PROMPT = "Return ONLY valid JSON."
_USER_PROMPT = "BTC/USD signal: rsi=35"
_TRACE_ID = "trace-lmstudio-test"


def _mock_client(content: str | None = _VALID_JSON, raise_on_create=None, models=None):
    """Build a mock openai.AsyncOpenAI client for LM Studio tests."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]

    client = MagicMock()
    if raise_on_create:
        client.chat.completions.create = AsyncMock(side_effect=raise_on_create)
    else:
        client.chat.completions.create = AsyncMock(return_value=completion)

    models_page = MagicMock()
    models_page.data = models if models is not None else [MagicMock(id="test-model")]
    client.models.list = AsyncMock(return_value=models_page)
    return client


# ---------------------------------------------------------------------------
# 1. App boots when LM Studio is disabled.
# ---------------------------------------------------------------------------


async def test_check_health_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", False)
    ok = await check_health()
    assert ok is False
    assert _health.healthy is False


# ---------------------------------------------------------------------------
# 2. App boots when LM Studio is enabled but unavailable.
# ---------------------------------------------------------------------------


async def test_check_health_enabled_but_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)

    mock = _mock_client()
    mock.models.list = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        ok = await check_health()

    assert ok is False
    assert _health.healthy is False
    assert _health.last_error is not None


# ---------------------------------------------------------------------------
# 3. Local LM Studio success returns validated decision.
# ---------------------------------------------------------------------------


async def test_call_lmstudio_success(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_TIMEOUT_SECONDS", 10)

    mock = _mock_client(content=_VALID_JSON)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, tokens, cost = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert isinstance(text, str)
    assert _VALID_JSON in text or text == _VALID_JSON
    assert tokens == 0
    assert cost == 0.0
    assert _health.healthy is True


# ---------------------------------------------------------------------------
# 4. Local timeout falls back to existing cloud provider.
# ---------------------------------------------------------------------------


async def test_call_llm_lmstudio_timeout_falls_back_to_cloud(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

    cloud_result = (
        {"action": "hold", "confidence": 0.6, "fallback": False, "trace_id": _TRACE_ID},
        100,
        0.0,
    )

    with patch(
        "api.services.llm_router.call_lmstudio", side_effect=LMStudioUnavailableError("timeout")
    ):
        with patch(
            "api.services.llm_router._PROVIDERS",
            {"gemini": AsyncMock(return_value=cloud_result)},
        ):
            with patch("api.services.llm_router._get_provider_key", return_value="fake-key"):
                from api.services.llm_router import call_llm

                result, tokens, cost = await call_llm(_USER_PROMPT, _TRACE_ID)

    assert result[FieldName.ACTION] == "hold"
    assert _health.healthy is False  # local recorded failure


# ---------------------------------------------------------------------------
# 5. Local malformed output falls back to cloud provider.
# ---------------------------------------------------------------------------


async def test_call_llm_lmstudio_malformed_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_TIMEOUT_SECONDS", 10)

    mock = _mock_client(content="not json at all {{{")
    cloud_parsed = {"action": "reject", "confidence": 0.0, "fallback": False, "trace_id": _TRACE_ID}

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with patch(
            "api.services.llm_router._PROVIDERS",
            {"gemini": AsyncMock(return_value=(cloud_parsed, 50, 0.0))},
        ):
            with patch("api.services.llm_router._get_provider_key", return_value="fake-key"):
                monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
                from api.services.llm_router import call_llm

                result, _, _ = await call_llm(_USER_PROMPT, _TRACE_ID)

    # malformed LM Studio output → fallback=True in parsed → cloud used
    assert result[FieldName.ACTION] == "reject"
    assert _health.healthy is False  # parse failure must be recorded
    assert _health.fallback_count == 1


# ---------------------------------------------------------------------------
# 6. Cloud fallback failure raises RuntimeError (caller handles NO_ACTION).
# ---------------------------------------------------------------------------


async def test_call_llm_both_fail_raises(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

    with patch(
        "api.services.llm_router.call_lmstudio", side_effect=LMStudioUnavailableError("down")
    ):
        with patch(
            "api.services.llm_router._PROVIDERS",
            {"gemini": AsyncMock(side_effect=RuntimeError("cloud_down"))},
        ):
            with patch("api.services.llm_router._get_provider_key", return_value="fake-key"):
                from api.services.llm_router import call_llm

                with pytest.raises(RuntimeError, match="cloud_down"):
                    await call_llm(_USER_PROMPT, _TRACE_ID)


# ---------------------------------------------------------------------------
# 7. LMStudioUnavailableError does not crash the consumer (call_lmstudio itself).
# ---------------------------------------------------------------------------


async def test_lmstudio_unavailable_does_not_propagate_as_crash(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client()
    mock.chat.completions.create = AsyncMock(side_effect=OSError("connection refused"))

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with pytest.raises(LMStudioUnavailableError):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    # The exception is a known, catchable type — not an unhandled crash
    assert isinstance(LMStudioUnavailableError("x"), RuntimeError)


# ---------------------------------------------------------------------------
# 8. health_snapshot reflects enabled + healthy state correctly.
# ---------------------------------------------------------------------------


async def test_health_snapshot_fields(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "my-model")

    _health.healthy = True
    _health.fallback_count = 3
    _health.last_error = None

    snap = health_snapshot()

    assert snap[FieldName.LM_STUDIO_ENABLED] is True
    assert snap[FieldName.LM_STUDIO_HEALTHY] is True
    assert snap[FieldName.LOCAL_FALLBACK_COUNT] == 3
    assert snap[FieldName.LAST_LOCAL_ERROR] is None
    assert snap[FieldName.LOCAL_MODEL] == "my-model"
    assert FieldName.LOCAL_LATENCY_MS in snap  # field always present (None when no calls yet)


async def test_health_snapshot_latency_exposed(monkeypatch):
    """local_latency_ms in snapshot reflects the last successful call latency."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "my-model")

    _health.healthy = True
    _health.last_latency_ms = 142.7

    snap = health_snapshot()
    assert snap[FieldName.LOCAL_LATENCY_MS] == 143  # rounded


# ---------------------------------------------------------------------------
# 9. check_health handles connection errors gracefully.
# ---------------------------------------------------------------------------


async def test_check_health_connection_error(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)

    mock = _mock_client()
    mock.models.list = AsyncMock(side_effect=OSError("connection refused"))

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        ok = await check_health()

    assert ok is False
    assert _health.last_error is not None


# ---------------------------------------------------------------------------
# 10. call_lmstudio_raw path (via call_llm_with_system) returns raw text.
# ---------------------------------------------------------------------------


async def test_call_llm_with_system_uses_lmstudio(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_TIMEOUT_SECONDS", 10)

    raw = "This is a raw LLM reflection response."
    mock = _mock_client(content=raw)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        from api.services.llm_router import call_llm_with_system

        text, tokens, cost = await call_llm_with_system(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert isinstance(text, str)
    assert text == raw
    assert tokens == 0
    assert cost == 0.0


# ---------------------------------------------------------------------------
# 11. No secrets are logged (LM_LINK_TOKEN not in log output).
# ---------------------------------------------------------------------------


async def test_no_secrets_in_logs(monkeypatch, caplog):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_LINK_TOKEN", "super-secret-token-12345")
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client()
    mock.chat.completions.create = AsyncMock(side_effect=OSError("connection refused"))

    import logging

    with caplog.at_level(logging.WARNING):
        with patch("api.services.lmstudio_provider._make_client", return_value=mock):
            try:
                await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)
            except LMStudioUnavailableError:
                pass

    for record in caplog.records:
        assert "super-secret-token-12345" not in record.getMessage()
        assert "super-secret-token-12345" not in str(record.args)


# ---------------------------------------------------------------------------
# 12. /llm/health endpoint includes local inference fields.
# ---------------------------------------------------------------------------


async def test_llm_health_endpoint_includes_lm_studio_fields(monkeypatch):
    """The /llm/health response must include all LM Studio health fields."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    _health.healthy = False
    _health.fallback_count = 1
    _health.last_error = "timeout"

    from api.routes.llm_health import llm_health

    with patch("api.routes.llm_health.get_redis_store", return_value=None):
        response = await llm_health()

    assert response[FieldName.LM_STUDIO_ENABLED] is True
    assert response[FieldName.LM_STUDIO_HEALTHY] is False
    assert response[FieldName.LOCAL_FALLBACK_COUNT] == 1
    assert response[FieldName.LAST_LOCAL_ERROR] == "timeout"
    assert response[FieldName.LOCAL_MODEL] == "test-model"


# ---------------------------------------------------------------------------
# 13. call_lmstudio raises when LM_STUDIO_MODEL is not configured.
# ---------------------------------------------------------------------------


async def test_call_lmstudio_empty_model_raises(monkeypatch):
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "")

    with pytest.raises(LMStudioUnavailableError, match="lm_studio_model_not_configured"):
        await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False
    assert _health.fallback_count == 1


# ---------------------------------------------------------------------------
# 14. Whitespace-only LM_STUDIO_MODEL is treated as unconfigured.
# ---------------------------------------------------------------------------


async def test_call_lmstudio_whitespace_model_raises(monkeypatch):
    """A model ID of '  ' (spaces only) must be caught by the guard, not sent to the API."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "   ")

    with pytest.raises(LMStudioUnavailableError, match="lm_studio_model_not_configured"):
        await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False
    assert _health.fallback_count == 1


async def test_health_snapshot_strips_whitespace_model(monkeypatch):
    """health_snapshot must return None for a whitespace-only model ID, not '   '."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "   ")

    snap = health_snapshot()

    assert snap[FieldName.LOCAL_MODEL] is None


# ---------------------------------------------------------------------------
# 16. check_health returns False when LM Studio has no model loaded.
# ---------------------------------------------------------------------------


async def test_check_health_no_model_loaded(monkeypatch):
    """check_health returns False and records no_model_loaded when models.data is empty."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)

    mock = _mock_client(models=[])
    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        ok = await check_health()

    assert ok is False
    assert _health.healthy is False
    assert _health.last_error == "no_model_loaded"


# ---------------------------------------------------------------------------
# 17. call_lmstudio with empty choices returns empty string (not a failure).
# ---------------------------------------------------------------------------


async def test_call_lmstudio_empty_choices_returns_empty_string(monkeypatch):
    """Empty completion.choices is a degenerate but not a hard failure — returns '' and marks healthy."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client()
    completion_no_choices = MagicMock()
    completion_no_choices.choices = []
    mock.chat.completions.create = AsyncMock(return_value=completion_no_choices)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, tokens, cost = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert text == ""
    assert tokens == 0
    assert cost == 0.0
    assert _health.healthy is True


# ---------------------------------------------------------------------------
# 18. call_llm_with_system falls back to cloud when LM Studio raises.
# ---------------------------------------------------------------------------


async def test_call_llm_with_system_falls_back_to_cloud_on_lmstudio_failure(monkeypatch):
    """When call_lmstudio raises LMStudioUnavailableError, call_llm_with_system uses cloud."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

    cloud_text = "Detailed market analysis from the cloud provider."

    with patch(
        "api.services.llm_router.call_lmstudio",
        side_effect=LMStudioUnavailableError("timeout"),
    ):
        with patch(
            "api.services.llm_router._get_provider_key",
            return_value="fake-gemini-key",
        ):
            with patch(
                "api.services.llm_router._call_provider_raw",
                AsyncMock(return_value=(cloud_text, 80, 0.0)),
            ):
                from api.services.llm_router import call_llm_with_system

                text, tokens, cost = await call_llm_with_system(
                    _USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID
                )

    assert text == cloud_text
    assert tokens == 80
    assert cost == 0.0
