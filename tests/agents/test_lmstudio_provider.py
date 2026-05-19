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
 19. should_try_local returns True when healthy.
 20. should_try_local returns False immediately after a failure (within cooldown).
 21. should_try_local returns True again after the cooldown elapses.
 22. _make_client always uses trust_env=False regardless of LM_LINK_ENABLED.
 23. validate_lm_studio_config raises when host:port is 127.0.0.1:1055 (proxy endpoint).
 24. validate_lm_studio_config raises when host:port is localhost:1055 (proxy endpoint).
 25. validate_lm_studio_config raises when host:port is 0.0.0.0:1055 (proxy endpoint).
 26. validate_lm_studio_config passes for a valid Tailscale IP and port 1234.
 27. get_lm_studio_base_url returns http://host:port/v1.
 28. _make_client uses LM_STUDIO_PROXY_URL as explicit proxy (not as base_url).
 29. check_health returns False and logs error when config is invalid.
 30. _make_client uses no proxy when LM_STUDIO_PROXY_URL is empty.
 31. call_lmstudio logs base_url_host and proxy_enabled before the call.
 32-37. Remote localhost mismatch detection and LLM_PROVIDER=lmstudio mode.
 38-41. validate_lm_studio_config also blocks LM_STUDIO_BASE_URL proxy endpoints (P2 regression).
 42-44. _is_lmstudio_effectively_enabled covers LLM_PROVIDER=lmstudio without flag (P2 regression).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import settings
from api.constants import FieldName
from api.services.lmstudio_provider import (
    _RETRY_INTERVAL_S,
    LMStudioUnavailableError,
    _health,
    _is_lmstudio_effectively_enabled,
    _make_client,
    call_lmstudio,
    check_health,
    get_lm_studio_base_url,
    health_snapshot,
    is_remote_localhost_mismatch,
    should_try_local,
    validate_lm_studio_config,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_lm_health():
    """Reset module-level health state before every test to prevent pollution."""
    _health.healthy = False
    _health.last_error = None
    _health.fallback_count = 0
    _health.last_latency_ms = 0.0
    _health.last_failure_at = 0.0
    yield
    _health.healthy = False
    _health.last_error = None
    _health.fallback_count = 0
    _health.last_latency_ms = 0.0
    _health.last_failure_at = 0.0


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


# ---------------------------------------------------------------------------
# 19-21. should_try_local cooldown prevents hammering a dead LM Studio server.
# ---------------------------------------------------------------------------


def test_should_try_local_returns_true_when_healthy():
    """Returns True immediately when health state is good."""
    _health.healthy = True
    assert should_try_local() is True


def test_should_try_local_returns_false_within_cooldown():
    """Returns False just after a failure, while within the retry interval."""
    import time

    _health.healthy = False
    _health.last_failure_at = time.monotonic()  # failed right now
    assert should_try_local() is False


def test_should_try_local_returns_true_after_cooldown():
    """Returns True once the retry interval has elapsed since the last failure."""
    import time

    _health.healthy = False
    # Simulate last failure was (interval + 1) seconds ago
    _health.last_failure_at = time.monotonic() - (_RETRY_INTERVAL_S + 1.0)
    assert should_try_local() is True


# ---------------------------------------------------------------------------
# 22. _make_client always uses trust_env=False regardless of LM_LINK_ENABLED.
# ---------------------------------------------------------------------------


def test_make_client_always_uses_trust_env_false(monkeypatch):
    """trust_env=False must be set on the httpx client regardless of LM_LINK_ENABLED.

    Prevents httpx from silently picking up ALL_PROXY/HTTP_PROXY/HTTPS_PROXY env
    vars that could route LM Studio HTTP to the Tailscale SOCKS5 listener.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_PROXY_URL", "")

    captured: list = []

    def capturing_client(*args, **kwargs):
        captured.append(kwargs)
        return MagicMock()

    with patch("api.services.lmstudio_provider.httpx.AsyncClient", side_effect=capturing_client):
        with patch("api.services.lmstudio_provider.AsyncOpenAI", return_value=MagicMock()):
            for lm_link_val in (True, False):
                monkeypatch.setattr(settings, "LM_LINK_ENABLED", lm_link_val)
                captured.clear()
                _make_client()
                assert captured[0].get("trust_env") is False, (
                    f"trust_env must be False when LM_LINK_ENABLED={lm_link_val}"
                )


# ---------------------------------------------------------------------------
# 23-25. validate_lm_studio_config rejects proxy endpoints as destination.
# ---------------------------------------------------------------------------


def test_validate_config_rejects_127_0_0_1_port_1055(monkeypatch):
    """127.0.0.1:1055 is the Tailscale proxy — must not be used as LM Studio host."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1055)
    with pytest.raises(RuntimeError, match="proxy endpoint was used as LM Studio destination"):
        validate_lm_studio_config()


def test_validate_config_rejects_localhost_port_1055(monkeypatch):
    """localhost:1055 is the Tailscale proxy — must not be used as LM Studio host."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1055)
    with pytest.raises(RuntimeError, match="proxy endpoint was used as LM Studio destination"):
        validate_lm_studio_config()


def test_validate_config_rejects_0_0_0_0_port_1055(monkeypatch):
    """0.0.0.0:1055 is a proxy-like binding — must not be used as LM Studio host."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "0.0.0.0")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1055)
    with pytest.raises(RuntimeError, match="proxy endpoint was used as LM Studio destination"):
        validate_lm_studio_config()


# ---------------------------------------------------------------------------
# 26. validate_lm_studio_config accepts a valid Tailscale IP.
# ---------------------------------------------------------------------------


def test_validate_config_accepts_tailscale_ip(monkeypatch):
    """A Tailscale IP with port 1234 is a valid LM Studio destination."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    validate_lm_studio_config()  # must not raise


# ---------------------------------------------------------------------------
# 27. get_lm_studio_base_url always returns http://host:port/v1.
# ---------------------------------------------------------------------------


def test_get_lm_studio_base_url(monkeypatch):
    """Base URL is always http://host:port/v1."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    assert get_lm_studio_base_url() == "http://100.112.224.78:1234/v1"


def test_get_lm_studio_base_url_strips_host_whitespace(monkeypatch):
    """Leading/trailing whitespace in LM_STUDIO_HOST is stripped."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "  100.112.224.78  ")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    assert get_lm_studio_base_url() == "http://100.112.224.78:1234/v1"


# ---------------------------------------------------------------------------
# 28. _make_client passes proxy URL as proxy transport, not as base_url.
# ---------------------------------------------------------------------------


def test_make_client_proxy_url_not_used_as_base_url(monkeypatch):
    """LM_STUDIO_PROXY_URL must be the proxy transport, never the base_url."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_PROXY_URL", "http://127.0.0.1:1055")

    captured_httpx: list = []
    captured_openai: list = []

    real_httpx_async_client = __import__("httpx").AsyncClient

    def capturing_httpx(*args, **kwargs):
        captured_httpx.append(kwargs)
        return real_httpx_async_client(*args, **kwargs)

    with patch("api.services.lmstudio_provider.httpx.AsyncClient", side_effect=capturing_httpx):
        with patch("api.services.lmstudio_provider.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            captured_openai.clear()
            mock_openai.side_effect = lambda **kw: captured_openai.append(kw) or MagicMock()
            _make_client()

    # httpx got the proxy URL
    assert captured_httpx[0].get("proxy") == "http://127.0.0.1:1055"
    # AsyncOpenAI base_url is the LM Studio URL, not the proxy
    assert captured_openai[0]["base_url"] == "http://100.112.224.78:1234/v1"
    assert "1055" not in captured_openai[0]["base_url"]


# ---------------------------------------------------------------------------
# 29. check_health returns False and records error for invalid config.
# ---------------------------------------------------------------------------


async def test_check_health_invalid_config_returns_false(monkeypatch):
    """check_health must return False (not raise) when LM Studio config is invalid."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1055)

    ok = await check_health()

    assert ok is False
    assert _health.healthy is False
    assert _health.last_error is not None
    assert "proxy" in (_health.last_error or "").lower()


# ---------------------------------------------------------------------------
# 30. _make_client sets proxy=None when LM_STUDIO_PROXY_URL is empty.
# ---------------------------------------------------------------------------


def test_make_client_no_proxy_when_url_empty(monkeypatch):
    """proxy=None when LM_STUDIO_PROXY_URL is empty — no proxy is applied."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_PROXY_URL", "")

    captured: list = []

    def capturing_client(*args, **kwargs):
        captured.append(kwargs)
        return MagicMock()

    with patch("api.services.lmstudio_provider.httpx.AsyncClient", side_effect=capturing_client):
        with patch("api.services.lmstudio_provider.AsyncOpenAI", return_value=MagicMock()):
            _make_client()

    assert captured[0].get("proxy") is None


# ---------------------------------------------------------------------------
# 31. call_lmstudio logs base_url_host and proxy_enabled before the call.
# ---------------------------------------------------------------------------


async def test_call_lmstudio_logs_request_context(monkeypatch, capsys):
    """call_lmstudio must log base_url_host and proxy_enabled before the API call.

    log_structured() writes to stdout (structlog) — use capsys, not caplog.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_PROXY_URL", "http://127.0.0.1:1055")

    mock = _mock_client(content="ok")

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    out = capsys.readouterr().out
    assert "reasoning_llm_request" in out
    assert "100.112.224.78" in out


# ---------------------------------------------------------------------------
# 32-37. Remote localhost mismatch detection and LLM_PROVIDER=lmstudio mode.
# ---------------------------------------------------------------------------


def test_is_remote_localhost_mismatch_true_when_render_and_localhost(monkeypatch):
    """Returns True when RENDER_EXTERNAL_URL is set and host is localhost."""
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    assert is_remote_localhost_mismatch() is True


def test_is_remote_localhost_mismatch_true_for_127_0_0_1(monkeypatch):
    """Returns True when RENDER_EXTERNAL_URL is set and host is 127.0.0.1."""
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    assert is_remote_localhost_mismatch() is True


def test_is_remote_localhost_mismatch_false_when_no_render_url(monkeypatch):
    """Returns False when RENDER_EXTERNAL_URL is not set (local dev)."""
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", None)
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    assert is_remote_localhost_mismatch() is False


def test_is_remote_localhost_mismatch_false_for_tailscale_ip(monkeypatch):
    """Returns False when host is a non-localhost Tailscale IP."""
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    assert is_remote_localhost_mismatch() is False


def test_is_remote_localhost_mismatch_reads_base_url_host(monkeypatch):
    """When LM_STUDIO_BASE_URL is set, extracts host from URL for mismatch check."""
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")  # should be overridden
    assert is_remote_localhost_mismatch() is True


async def test_check_health_returns_false_with_mismatch_error(monkeypatch):
    """check_health returns False with a clear error when remote + localhost mismatch."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")

    ok = await check_health()

    assert ok is False
    assert _health.healthy is False
    assert _health.last_error is not None
    assert "Remote backend" in (_health.last_error or "")
    assert "localhost" in (_health.last_error or "")


async def test_health_snapshot_includes_mismatch_field(monkeypatch):
    """health_snapshot always includes remote_localhost_mismatch field."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")

    snap = health_snapshot()

    assert FieldName.REMOTE_LOCALHOST_MISMATCH in snap
    assert snap[FieldName.REMOTE_LOCALHOST_MISMATCH] is True
    assert snap[FieldName.REACHABLE] is False
    assert snap[FieldName.BASE_URL_HOST] == "localhost"


async def test_check_health_stores_available_models(monkeypatch):
    """check_health stores the list of loaded model IDs from /v1/models."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", None)

    model_a = MagicMock()
    model_a.id = "test-model"
    model_b = MagicMock()
    model_b.id = "other-model"
    mock = _mock_client(models=[model_a, model_b])

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        ok = await check_health()

    assert ok is True
    assert _health.available_models == ["test-model", "other-model"]
    snap = health_snapshot()
    assert snap[FieldName.AVAILABLE_MODELS] == ["test-model", "other-model"]


async def test_check_health_configured_model_not_in_loaded_models(monkeypatch):
    """check_health returns False when configured model is not in the loaded models list."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "my-specific-model")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", None)

    loaded = MagicMock()
    loaded.id = "other-model"
    mock = _mock_client(models=[loaded])

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        ok = await check_health()

    assert ok is False
    assert _health.healthy is False
    assert "not found" in (_health.last_error or "").lower()
    assert "other-model" in (_health.last_error or "")


async def test_llm_provider_lmstudio_enables_lm_studio(monkeypatch):
    """LLM_PROVIDER=lmstudio makes LM Studio effectively enabled without LM_STUDIO_ENABLED."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", False)  # not explicitly enabled
    monkeypatch.setattr(settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", None)

    mock = _mock_client(content=_VALID_JSON)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, _, _ = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert text == _VALID_JSON
    assert _health.healthy is True


def test_get_lm_studio_base_url_uses_base_url_when_set(monkeypatch):
    """get_lm_studio_base_url uses LM_STUDIO_BASE_URL when set."""
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://localhost:1234")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "10.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 9999)
    assert get_lm_studio_base_url() == "http://localhost:1234/v1"


def test_get_lm_studio_base_url_appends_v1_if_missing(monkeypatch):
    """get_lm_studio_base_url appends /v1 when LM_STUDIO_BASE_URL lacks it."""
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://192.168.1.10:1234")
    assert get_lm_studio_base_url() == "http://192.168.1.10:1234/v1"


def test_get_lm_studio_base_url_no_double_v1(monkeypatch):
    """get_lm_studio_base_url does not double the /v1 suffix."""
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://192.168.1.10:1234/v1")
    assert get_lm_studio_base_url() == "http://192.168.1.10:1234/v1"


def test_get_lm_studio_base_url_strips_trailing_slash(monkeypatch):
    """get_lm_studio_base_url handles LM_STUDIO_BASE_URL with a trailing slash.

    Regression: 'http://localhost:1234/v1/' previously produced
    'http://localhost:1234/v1/v1' because the /v1 check ran before the
    rstrip('/').
    """
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://localhost:1234/v1/")
    assert get_lm_studio_base_url() == "http://localhost:1234/v1"

    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://localhost:1234/")
    assert get_lm_studio_base_url() == "http://localhost:1234/v1"


# ---------------------------------------------------------------------------
# Regression: validate_lm_studio_config must also block LM_STUDIO_BASE_URL
# pointing at the Tailscale proxy endpoint (P2 fix).
# ---------------------------------------------------------------------------


def test_validate_config_rejects_base_url_with_proxy_host_port(monkeypatch):
    """LM_STUDIO_BASE_URL=http://127.0.0.1:1055/v1 must be blocked by the guard.

    Regression: validate_lm_studio_config previously only checked
    LM_STUDIO_HOST:LM_STUDIO_PORT, so setting LM_STUDIO_BASE_URL bypassed
    the proxy-endpoint guard entirely.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")  # valid host
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)  # valid port
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://127.0.0.1:1055/v1")
    with pytest.raises(RuntimeError, match="proxy endpoint was used as LM Studio destination"):
        validate_lm_studio_config()


def test_validate_config_rejects_base_url_localhost_port_1055(monkeypatch):
    """LM_STUDIO_BASE_URL=http://localhost:1055 is blocked even with valid host:port."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://localhost:1055")
    with pytest.raises(RuntimeError, match="proxy endpoint was used as LM Studio destination"):
        validate_lm_studio_config()


def test_validate_config_accepts_valid_base_url(monkeypatch):
    """LM_STUDIO_BASE_URL with a valid Tailscale IP passes validation."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://100.112.224.78:1234/v1")
    validate_lm_studio_config()  # must not raise


def test_validate_config_ignores_empty_base_url(monkeypatch):
    """validate_lm_studio_config skips LM_STUDIO_BASE_URL check when it is empty."""
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    validate_lm_studio_config()  # must not raise


# ---------------------------------------------------------------------------
# Regression: _is_lmstudio_effectively_enabled returns True for LLM_PROVIDER=lmstudio
# even when LM_STUDIO_ENABLED=False (startup probe gate fix — P2).
# ---------------------------------------------------------------------------


def test_is_lmstudio_effectively_enabled_true_when_primary(monkeypatch):
    """LLM_PROVIDER=lmstudio must make effectively_enabled return True.

    Regression: api/main.py startup probe was gated on settings.LM_STUDIO_ENABLED
    only, so LLM_PROVIDER=lmstudio + LM_STUDIO_ENABLED=False skipped the probe.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "lmstudio")
    assert _is_lmstudio_effectively_enabled() is True


def test_is_lmstudio_effectively_enabled_true_when_flag_set(monkeypatch):
    """LM_STUDIO_ENABLED=True makes effectively_enabled return True."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    assert _is_lmstudio_effectively_enabled() is True


def test_is_lmstudio_effectively_enabled_false_when_both_off(monkeypatch):
    """Neither LM_STUDIO_ENABLED nor LLM_PROVIDER=lmstudio → returns False."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    assert _is_lmstudio_effectively_enabled() is False


# ---------------------------------------------------------------------------
# Regression: check_health marks unhealthy when LM_STUDIO_MODEL is blank (P2 fix).
# ---------------------------------------------------------------------------


async def test_check_health_blank_model_returns_false_and_unhealthy(monkeypatch):
    """check_health returns False and marks unhealthy when LM_STUDIO_MODEL is blank.

    Regression: when models are loaded but LM_STUDIO_MODEL='', _health.healthy was
    left True because the configured-model check was gated on `if configured`.
    call_lmstudio() would then immediately raise lm_studio_model_not_configured,
    creating a misleading healthy/active dashboard state — especially dangerous
    with LLM_FALLBACK_ENABLED=false.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", None)

    mock = _mock_client()  # returns one loaded model in models.data
    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        ok = await check_health()

    assert ok is False
    assert _health.healthy is False
    assert _health.last_error == "lm_studio_model_not_configured"


# ---------------------------------------------------------------------------
# URL sanitization in log_startup_config
# ---------------------------------------------------------------------------


def test_log_startup_config_redacts_url_credentials(monkeypatch, capsys):
    """log_startup_config must not emit userinfo or query tokens from LM_STUDIO_BASE_URL.

    Regression: base_url was logged as-is; authenticated tunnel URLs
    (e.g. https://user:token@host/v1?key=abc) would leak credentials into
    structured logs despite the "Never logs secrets" contract.
    """
    from api.services.lmstudio_provider import log_startup_config

    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(
        settings,
        "LM_STUDIO_BASE_URL",
        "http://secretuser:secretpass@tunnel.example.com:8080/v1?token=abc123",
    )
    monkeypatch.setattr(settings, "LM_STUDIO_PROXY_URL", "")

    log_startup_config()

    out = capsys.readouterr().out
    assert "secretuser" not in out
    assert "secretpass" not in out
    assert "abc123" not in out
    assert "tunnel.example.com" in out
