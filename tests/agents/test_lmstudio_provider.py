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
 45-47. Streaming transport: stream=True, non-streaming fallback, task-based token selection.
"""

from __future__ import annotations

import json
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


class _FakeAsyncStream:
    """Minimal async iterable simulating an openai streaming response."""

    def __init__(self, chunks: list):
        self._chunks = list(chunks)
        self._pos = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._pos >= len(self._chunks):
            raise StopAsyncIteration
        result = self._chunks[self._pos]
        self._pos += 1
        return result


def _make_streaming_chunk(content: str | None = None, reasoning_content: str | None = None):
    """Build a mock ChatCompletionChunk delta for streaming tests."""
    delta = MagicMock()
    delta.content = content
    delta.reasoning_content = reasoning_content
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _mock_client(
    content: str | None = _VALID_JSON,
    raise_on_create=None,
    models=None,
    reasoning_content: str | None = None,
):
    """Build a mock openai.AsyncOpenAI client.

    Dispatches on the ``stream`` kwarg passed to ``completions.create``:
    - ``stream=True``  → returns a _FakeAsyncStream with content/reasoning_content chunks.
    - ``stream=False`` → returns a non-streaming completion with ``msg.content`` set.

    When ``raise_on_create`` is given it takes precedence (useful for API error tests).
    """
    client = MagicMock()
    if raise_on_create:
        client.chat.completions.create = AsyncMock(side_effect=raise_on_create)
    else:

        async def _create(**kwargs):
            if kwargs.get("stream"):
                chunks: list = []
                if content is not None:
                    chunks.append(_make_streaming_chunk(content=content))
                if reasoning_content is not None:
                    chunks.append(_make_streaming_chunk(reasoning_content=reasoning_content))
                return _FakeAsyncStream(chunks)
            # Non-streaming completion
            msg = MagicMock()
            msg.content = content
            msg.reasoning_content = reasoning_content
            choice = MagicMock()
            choice.message = msg
            completion = MagicMock()
            completion.choices = [choice] if content is not None else []
            return completion

        client.chat.completions.create = _create

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


async def test_call_llm_lmstudio_malformed_returns_hold(monkeypatch):
    """Malformed JSON from LM Studio → HOLD returned by the provider directly.

    call_lmstudio validates the response JSON and returns a safe HOLD fallback
    when the model's output cannot be parsed.  The cloud provider is never
    called because call_lmstudio succeeds (returning HOLD), so _health.healthy
    stays True — the infrastructure is fine; only the output was bad.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_TIMEOUT_SECONDS", 10)

    mock = _mock_client(content="not json at all {{{")

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        from api.services.llm_router import call_llm

        result, _, _ = await call_llm(_USER_PROMPT, _TRACE_ID)

    # malformed output → HOLD from provider; cloud is never tried
    assert result[FieldName.ACTION] == "hold"
    assert _health.healthy is True  # infrastructure worked — parse used fallback


# ---------------------------------------------------------------------------
# 5b. Non-dict JSON (list, string, null) → HOLD, not AttributeError.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_llm_lmstudio_non_dict_json_returns_hold(monkeypatch):
    """Valid JSON that is not a dict (e.g. []) must produce HOLD, not AttributeError.

    json.loads on a list/string/null succeeds but parsed.get(...) would raise
    AttributeError.  The isinstance(candidate, dict) guard must catch this
    and route to the HOLD fallback instead of surfacing a hard failure.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_TIMEOUT_SECONDS", 10)

    for non_dict_payload in ["[]", '"just a string"', "null", "42"]:
        mock = _mock_client(content=non_dict_payload)
        with patch("api.services.lmstudio_provider._make_client", return_value=mock):
            from api.services.lmstudio_provider import call_lmstudio

            text, _, _ = await call_lmstudio("prompt", "system", _TRACE_ID, parse_json=True)
        result = json.loads(text)
        assert result[FieldName.ACTION] == "hold", f"expected hold for payload {non_dict_payload!r}"
        assert _health.healthy is True


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


async def test_call_lmstudio_empty_choices_raises_unavailable(monkeypatch):
    """Empty completion.choices raises LMStudioUnavailableError.

    An empty choices list means the model produced nothing — treat it the same
    as empty content: raise so the router can fall back or apply HOLD.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client()
    completion_no_choices = MagicMock()
    completion_no_choices.choices = []
    mock.chat.completions.create = AsyncMock(return_value=completion_no_choices)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with pytest.raises(LMStudioUnavailableError, match="lmstudio_empty_response"):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False


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


async def test_call_lmstudio_logs_request_context(monkeypatch):
    """call_lmstudio must log base_url_host and proxy_enabled before the API call."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "100.112.224.78")
    monkeypatch.setattr(settings, "LM_STUDIO_PORT", 1234)
    monkeypatch.setattr(settings, "LM_STUDIO_PROXY_URL", "http://127.0.0.1:1055")

    mock = _mock_client(content="ok")
    log_calls: list[tuple] = []

    def _capture_log(level, event, **kwargs):
        log_calls.append((level, event, kwargs))

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with patch("api.services.lmstudio_provider.log_structured", side_effect=_capture_log):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    events = [e for _, e, _ in log_calls]
    assert "reasoning_llm_request" in events
    host_logged = any(kw.get("base_url_host") == "100.112.224.78" for _, _, kw in log_calls)
    assert host_logged, f"base_url_host not in log calls: {log_calls}"


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


def test_get_lm_studio_base_url_with_query_string(monkeypatch):
    """get_lm_studio_base_url appends /v1 to the path, not after a query string.

    Regression: raw-string append previously produced 'http://host/path?q=abc/v1'
    when the URL had a query component.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://host:1234?token=abc")
    assert get_lm_studio_base_url() == "http://host:1234/v1"

    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://host:1234/base?token=abc")
    assert get_lm_studio_base_url() == "http://host:1234/base/v1"


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


def test_log_startup_config_redacts_url_credentials(monkeypatch):
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

    log_calls: list[tuple] = []

    def _capture_log(level, event, **kwargs):
        log_calls.append((level, event, kwargs))

    with patch("api.services.lmstudio_provider.log_structured", side_effect=_capture_log):
        log_startup_config()

    # Flatten all logged values to a single string for easy assertion
    logged_text = str(log_calls)
    assert "secretuser" not in logged_text
    assert "secretpass" not in logged_text
    assert "abc123" not in logged_text
    assert "tunnel.example.com" in logged_text


# ---------------------------------------------------------------------------
# P1: validate_lm_studio_config — invalid port raises RuntimeError (not ValueError)
# ---------------------------------------------------------------------------


def test_validate_config_invalid_port_raises_runtime_error(monkeypatch):
    """LM_STUDIO_BASE_URL with a non-integer port must raise RuntimeError, not ValueError.

    Regression: urllib.parse.urlparse accepts invalid port strings silently, but
    accessing parsed.port raises ValueError.  validate_lm_studio_config() only
    raised RuntimeError for blocked hosts; an invalid port escaped as ValueError
    which check_health() did not catch, crashing startup.
    """
    from api.services.lmstudio_provider import validate_lm_studio_config

    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://localhost:notaport/v1")
    with pytest.raises(RuntimeError, match="Invalid LM_STUDIO_BASE_URL"):
        validate_lm_studio_config()


def test_check_health_invalid_port_returns_false_not_crash(monkeypatch):
    """check_health() must return False (degraded) for an invalid port, not raise."""
    import pytest_asyncio  # noqa: F401 — ensure async test infra

    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "http://localhost:badport/v1")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "")

    from api.services import lmstudio_provider as _mod

    _mod._health.healthy = False

    import asyncio

    result = asyncio.get_event_loop().run_until_complete(_mod.check_health())
    assert result is False
    assert _mod._health.healthy is False
    assert _mod._health.last_error is not None


# ---------------------------------------------------------------------------
# P2: available_models cleared on check_health() failure paths
# ---------------------------------------------------------------------------


def test_check_health_clears_available_models_on_mismatch(monkeypatch):
    """Stale available_models must be cleared when a mismatch failure is detected.

    Regression: a prior successful probe set _health.available_models; a subsequent
    remote-localhost mismatch left those models in the snapshot, misrepresenting
    current LM Studio state.
    """
    from api.services import lmstudio_provider as _mod

    # Seed stale models from a prior successful probe
    _mod._health.available_models = ["llama-3-8b", "mistral-7b"]
    _mod._health.healthy = True

    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    # Simulate remote deployment where mismatch is detected
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")

    import asyncio

    result = asyncio.get_event_loop().run_until_complete(_mod.check_health())
    assert result is False
    assert _mod._health.available_models == [], "stale models must be cleared on mismatch"


def test_check_health_clears_available_models_on_network_failure(monkeypatch):
    """Stale available_models must be cleared when the /v1/models probe fails with a network error."""
    from api.services import lmstudio_provider as _mod

    _mod._health.available_models = ["old-model"]
    _mod._health.healthy = True

    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(settings, "RENDER_EXTERNAL_URL", "")
    monkeypatch.setattr(settings, "LM_STUDIO_HOST", "localhost")

    async def _failing_list(self):
        raise ConnectionRefusedError("connection refused")

    import asyncio

    from openai.resources.models import AsyncModels

    monkeypatch.setattr(AsyncModels, "list", _failing_list)

    result = asyncio.get_event_loop().run_until_complete(_mod.check_health())
    assert result is False
    assert _mod._health.available_models == [], "stale models must be cleared on network failure"


# ---------------------------------------------------------------------------
# Thinking mode: extra_body disables thinking and reasoning_content fallback
# ---------------------------------------------------------------------------


async def test_call_lmstudio_sends_enable_thinking_false(monkeypatch):
    """call_lmstudio must pass chat_template_kwargs.enable_thinking=False in extra_body.

    This disables Qwen3.5 thinking mode so the JSON decision lands in content,
    not reasoning_content.  Non-thinking models ignore the field.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(content=_VALID_JSON)
    call_kwargs: list[dict] = []

    original_create = mock.chat.completions.create

    async def capturing_create(**kwargs):
        call_kwargs.append(kwargs)
        return await original_create(**kwargs)

    mock.chat.completions.create = capturing_create

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert call_kwargs, "completions.create was never called"
    extra_body = call_kwargs[0].get("extra_body", {})
    assert extra_body.get("chat_template_kwargs", {}).get("enable_thinking") is False


async def test_call_lmstudio_empty_content_raises_unavailable(monkeypatch):
    """When message.content is empty, call_lmstudio raises LMStudioUnavailableError.

    Instruct models (Llama 3.1) always put their output in content; an empty
    content field means the model failed to produce a response.  The router
    catches LMStudioUnavailableError and falls back to cloud or HOLD.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(content=None)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with pytest.raises(LMStudioUnavailableError, match="lmstudio_empty_response"):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False


async def test_call_lmstudio_only_reasoning_content_raises_unavailable(monkeypatch):
    """reasoning_content-only response raises LMStudioUnavailableError.

    Instruct models write their answer to content, not reasoning_content.
    When content is empty the provider treats it as a model failure, not
    a parse failure, so the router can fall back rather than returning HOLD.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(
        content=None, reasoning_content="I am thinking... but I cannot form a JSON object."
    )

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with pytest.raises(LMStudioUnavailableError, match="lmstudio_empty_response"):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False


def test_extract_json_from_text_finds_embedded_json():
    """_extract_json_from_text returns the first valid JSON object found in free text."""
    from api.services.lmstudio_provider import _extract_json_from_text

    text = 'Thinking...\n{"action":"hold","confidence":0.7}\nDone.'
    result = _extract_json_from_text(text)
    assert result == '{"action":"hold","confidence":0.7}'


def test_extract_json_from_text_returns_empty_when_no_json():
    """_extract_json_from_text returns empty string when no valid JSON object exists."""
    from api.services.lmstudio_provider import _extract_json_from_text

    result = _extract_json_from_text("no json here")
    assert result == ""


def test_extract_json_from_text_handles_nested_objects():
    """_extract_json_from_text correctly handles JSON with nested objects."""
    from api.services.lmstudio_provider import _extract_json_from_text

    text = 'prefix {"outer": {"inner": 1}, "x": 2} suffix'
    result = _extract_json_from_text(text)
    import json as _json

    assert _json.loads(result) == {"outer": {"inner": 1}, "x": 2}


def test_extract_json_from_text_stray_brace_before_json():
    """Stray } before the JSON object must not prevent extraction.

    Regression: the old depth counter went negative on a lone }, so the
    next { did not set start and the candidate was never captured.
    """
    from api.services.lmstudio_provider import _extract_json_from_text

    text = 'thinking } then decided: {"action": "buy"} end'
    assert _extract_json_from_text(text) == '{"action": "buy"}'


def test_extract_json_from_text_brace_inside_string():
    """} inside a quoted value must not confuse the extractor.

    Regression: the old depth counter decremented on every } including those
    inside string literals, producing wrong depth and a missed object.
    """
    from api.services.lmstudio_provider import _extract_json_from_text

    text = 'prefix {"note": "contains } brace", "action": "hold"} suffix'
    import json as _json

    result = _extract_json_from_text(text)
    assert _json.loads(result) == {"note": "contains } brace", "action": "hold"}


def test_extract_json_from_text_truncated_json_returns_empty():
    """Truncated JSON (model hit token limit mid-generation) returns empty string, not a crash.

    raw_decode raises JSONDecodeError on incomplete input; the function must
    catch it and return '' so call_lmstudio leaves text empty and the router's
    normal parse-failure / cloud-fallback path takes over.
    """
    from api.services.lmstudio_provider import _extract_json_from_text

    assert _extract_json_from_text('{"action": "buy", "confiden') == ""
    assert _extract_json_from_text('{"nested": {"x": 1') == ""
    assert _extract_json_from_text("") == ""


async def test_call_lmstudio_empty_content_raises_not_returns_empty(monkeypatch):
    """Empty content (e.g. model hit token limit before writing anything) raises, not returns ''.

    Previously call_lmstudio returned ("", 0, 0.0) and relied on the router's
    parse-failure path.  Now it raises LMStudioUnavailableError so the router
    can fall back to cloud or the ReasoningAgent can apply HOLD.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(content=None)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with pytest.raises(LMStudioUnavailableError, match="lmstudio_empty_response"):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False


async def test_call_lmstudio_uses_lmstudio_max_tokens_default(monkeypatch):
    """call_lmstudio default max_tokens comes from settings.LM_STUDIO_MAX_TOKENS when task_type=None."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_MAX_TOKENS", 256)

    mock = _mock_client(content=_VALID_JSON)
    captured: list[dict] = []
    original_create = mock.chat.completions.create

    async def spy(**kwargs):
        captured.append(kwargs)
        return await original_create(**kwargs)

    mock.chat.completions.create = spy

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert captured, "completions.create was never called"
    assert captured[0]["max_tokens"] == 256
    assert captured[0].get("stream") is False


# ---------------------------------------------------------------------------
# 45-47. Streaming transport: stream=True, fallback, task-based token selection
# ---------------------------------------------------------------------------


async def test_call_lmstudio_uses_nonstreaming(monkeypatch):
    """call_lmstudio must use stream=False for bounded, deterministic JSON output.

    Instruct models (Llama 3.1) return short JSON decisions in one shot;
    non-streaming is simpler and more reliable than streaming.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(content=_VALID_JSON)
    captured: list[dict] = []
    original_create = mock.chat.completions.create

    async def spy(**kwargs):
        captured.append(kwargs)
        return await original_create(**kwargs)

    mock.chat.completions.create = spy

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, _, _ = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert captured[0].get("stream") is False
    assert "response_format" not in captured[0]
    assert text == _VALID_JSON


async def test_call_lmstudio_nonstreaming_api_error_raises(monkeypatch):
    """A connection error from the non-streaming request raises LMStudioUnavailableError.

    call_lmstudio always uses stream=False; any API error propagates as
    LMStudioUnavailableError so the router can fall back.
    """
    from openai import APIConnectionError

    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(raise_on_create=APIConnectionError(request=MagicMock()))

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with pytest.raises(LMStudioUnavailableError):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False


async def test_call_lmstudio_task_type_price_analysis_uses_analysis_tokens(monkeypatch):
    """task_type='price_analysis' selects settings.LM_STUDIO_MAX_TOKENS_ANALYSIS (1024)."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_MAX_TOKENS_ANALYSIS", 1024)

    mock = _mock_client(content=_VALID_JSON)
    captured: list[dict] = []
    original_create = mock.chat.completions.create

    async def spy(**kwargs):
        captured.append(kwargs)
        return await original_create(**kwargs)

    mock.chat.completions.create = spy

    from api.constants import LLM_TASK_PRICE_ANALYSIS

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        await call_lmstudio(
            _USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID, task_type=LLM_TASK_PRICE_ANALYSIS
        )

    assert captured[0]["max_tokens"] == 1024
    assert captured[0].get("stream") is False


# ---------------------------------------------------------------------------
# 48-52. Llama instruct model: non-streaming success, empty/reasoning-only
#        raises, invalid JSON HOLD, unknown action HOLD, model env var.
# ---------------------------------------------------------------------------


async def test_call_lmstudio_nonstreaming_reads_message_content(monkeypatch):
    """Non-streaming (default): reads message.content, returns clean JSON. (48)"""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(content=_VALID_JSON)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, tokens, cost = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert text == _VALID_JSON
    assert tokens == 0
    assert cost == 0.0
    assert _health.healthy is True


async def test_call_lmstudio_reasoning_content_only_raises_unavailable(monkeypatch):
    """Only reasoning_content set, content empty → LMStudioUnavailableError. (49)

    Instruct models write their answer to content, not reasoning_content.
    Empty content is treated as a provider failure so the router can fall back.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(content=None, reasoning_content='{"action":"buy"}')

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        with pytest.raises(LMStudioUnavailableError, match="lmstudio_empty_response"):
            await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert _health.healthy is False


async def test_call_lmstudio_streaming_ignores_delta_reasoning_content(monkeypatch):
    """_collect_streaming_response ignores delta.reasoning_content; only delta.content used. (50)"""
    from api.services.lmstudio_provider import _collect_streaming_response

    # Build a fake client that streams one reasoning chunk and one content chunk.
    content_chunk = _make_streaming_chunk(content=_VALID_JSON)
    reasoning_chunk = _make_streaming_chunk(reasoning_content="some thinking ignored")

    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_FakeAsyncStream([reasoning_chunk, content_chunk])
    )

    content, reasoning = await _collect_streaming_response(
        client, "test-model", [], 256, 0.0, _TRACE_ID
    )
    assert content == _VALID_JSON
    assert reasoning == "some thinking ignored"  # collected but never used by call_lmstudio


async def test_call_lmstudio_invalid_json_returns_hold(monkeypatch):
    """Invalid JSON in content → HOLD fallback JSON returned (not raise). (51)"""
    import json as _json

    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    mock = _mock_client(content="Sure! Here is my analysis: {{{not json}}}")

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, tokens, cost = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    parsed = _json.loads(text)
    assert parsed["action"] == "hold"
    assert parsed["fallback"] is True
    assert _health.healthy is True  # parse failure is not a provider infrastructure failure


async def test_call_lmstudio_unknown_action_returns_hold(monkeypatch):
    """Valid JSON with unknown action → HOLD fallback JSON returned. (52)"""
    import json as _json

    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")

    bad_action_json = '{"action":"maybe","confidence":0.5,"trace_id":"t1"}'
    mock = _mock_client(content=bad_action_json)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, tokens, cost = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    parsed = _json.loads(text)
    assert parsed["action"] == "hold"
    assert parsed["fallback"] is True
    assert _health.healthy is True


async def test_call_lmstudio_model_env_var_sent_in_payload(monkeypatch):
    """LM_STUDIO_MODEL env var controls the model field sent in the completions request."""
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "meta-llama-3.1-8b-instruct")

    mock = _mock_client(content=_VALID_JSON)
    captured: list[dict] = []
    original_create = mock.chat.completions.create

    async def spy(**kwargs):
        captured.append(kwargs)
        return await original_create(**kwargs)

    mock.chat.completions.create = spy

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    assert captured[0]["model"] == "meta-llama-3.1-8b-instruct"
    assert captured[0].get("stream") is False


async def test_call_lmstudio_task_type_uses_caller_temperature(monkeypatch):
    """Explicit temperature= override must survive _get_task_params; settings default is not used.

    Regression for bug where _get_task_params always returned settings.LM_STUDIO_TEMPERATURE
    and silently discarded the caller's resolved temperature.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_TEMPERATURE", 0.0)  # default

    mock = _mock_client(content=_VALID_JSON)
    captured: list[dict] = []
    original_create = mock.chat.completions.create

    async def spy(**kwargs):
        captured.append(kwargs)
        return await original_create(**kwargs)

    mock.chat.completions.create = spy

    from api.constants import LLM_TASK_PRICE_ANALYSIS

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        await call_lmstudio(
            _USER_PROMPT,
            _SYSTEM_PROMPT,
            _TRACE_ID,
            temperature=0.7,  # explicit override
            task_type=LLM_TASK_PRICE_ANALYSIS,
        )

    # The explicit 0.7 must reach the API call, not the settings default of 0.0.
    assert captured[0]["temperature"] == pytest.approx(0.7)


async def test_call_lmstudio_streaming_fallback_to_nonstreaming(monkeypatch):
    """Mid-stream drop retries once with stream=False before failing.

    Regression for bug where streaming mode had no retry — any chunk-iteration
    exception surfaced immediately as LMStudioUnavailableError.
    """
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_MODEL", "test-model")
    monkeypatch.setattr(settings, "LM_STUDIO_STREAM", True)

    call_count = 0

    async def flaky_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs.get("stream"):
            # Streaming call fails with a mid-stream error
            raise RuntimeError("stream dropped")
        # Non-streaming retry succeeds
        msg = MagicMock()
        msg.content = _VALID_JSON
        msg.reasoning_content = None
        choice = MagicMock()
        choice.message = msg
        completion = MagicMock()
        completion.choices = [choice]
        return completion

    mock = MagicMock()
    mock.chat.completions.create = flaky_create
    models_page = MagicMock()
    models_page.data = [MagicMock(id="test-model")]
    mock.models.list = AsyncMock(return_value=models_page)

    with patch("api.services.lmstudio_provider._make_client", return_value=mock):
        text, _, _ = await call_lmstudio(_USER_PROMPT, _SYSTEM_PROMPT, _TRACE_ID)

    # call 1 = streaming (failed), call 2 = non-streaming retry (succeeded)
    assert call_count == 2
    assert text == _VALID_JSON
    assert _health.healthy is True
