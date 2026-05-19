"""Memory-mode regression tests for GET /llm/health.

The endpoint reads exclusively from the in-process LLMMetricsCollector
and must never touch the DB session factory.  These tests verify:

1. Both URL forms respond 200 (root and /api prefix).
2. Response shape matches the expected schema.
3. set_db_available(False) does not affect the response — no DB is touched.
4. Recorded metrics appear correctly in the snapshot.
5. daily_calls resets to 0 when the date rolls over between snapshot() calls.
6. GradeAgent._adjust_llm_call_rate only bumps delay when new 429s appear.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.runtime_state import set_db_available
from api.services.llm_metrics import LLMMetricsCollector


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


# ---------------------------------------------------------------------------
# 1 + 2  both URL forms return 200 with expected fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_health_root_path(client: AsyncClient):
    r = await client.get("/llm/health")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "status",
        "provider",
        "active_provider",
        "model",
        "model_var",
        "timestamp",
        "success_rate_pct",
        "daily_calls",
        "lm_studio_enabled",
        "lm_studio_healthy",
    ):
        assert key in data, f"missing key: {key}"


@pytest.mark.asyncio
async def test_llm_health_api_prefix(client: AsyncClient):
    r = await client.get("/api/llm/health")
    assert r.status_code == 200
    assert "status" in r.json()


# ---------------------------------------------------------------------------
# 3  DB unavailable — must still return 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_health_memory_mode(client: AsyncClient):
    """Endpoint must succeed with DB unavailable (no DB session opened)."""
    set_db_available(False)
    try:
        r = await client.get("/llm/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("live", "degraded", "down", "unknown")
    finally:
        set_db_available(True)


# ---------------------------------------------------------------------------
# 4  recorded metrics appear in the snapshot
# ---------------------------------------------------------------------------


def test_snapshot_reflects_recorded_calls():
    col = LLMMetricsCollector(max_records=50)
    col.record_success(latency_ms=123.0)
    col.record_success(latency_ms=456.0)
    col.record_rate_limit()
    snap = col.snapshot()

    assert snap["success_count"] == 2
    assert snap["rate_limited_count"] == 1
    assert snap["total_in_window"] == 3
    assert snap["daily_calls"] == 3
    assert snap["total_calls_lifetime"] == 3
    assert snap["avg_latency_ms"] == round((123.0 + 456.0) / 2)


def test_snapshot_includes_last_error_details():
    col = LLMMetricsCollector(max_records=50)
    col.record_error(message="missing_api_key: set GEMINI_API_KEY in environment", kind="config")
    snap = col.snapshot()

    assert "last_error" in snap
    assert snap["last_error"]["kind"] == "config"
    assert "missing_api_key" in (snap["last_error"]["message"] or "")
    assert snap["last_error"]["at"]


# ---------------------------------------------------------------------------
# 5  daily_calls rolls over to 0 when date changes without new calls
# ---------------------------------------------------------------------------


def test_snapshot_daily_calls_reset_on_date_rollover(monkeypatch):
    col = LLMMetricsCollector(max_records=50)

    # Seed some calls under a fake "yesterday"
    monkeypatch.setattr(col, "_today", lambda: "2000-01-01")
    col.record_success(latency_ms=10.0)
    col.record_success(latency_ms=20.0)
    assert col._daily_calls == 2

    # Advance the clock to "today" without recording any new calls
    monkeypatch.setattr(col, "_today", lambda: "2000-01-02")
    snap = col.snapshot()

    assert snap["daily_calls"] == 0, "daily_calls must reset when date changes in snapshot()"
    assert snap["total_calls_lifetime"] == 2, "lifetime counter must not be affected"


# ---------------------------------------------------------------------------
# 6  effective_delay_ms and grade_adjusted_delay are present
# ---------------------------------------------------------------------------


def test_snapshot_delay_fields_present():
    col = LLMMetricsCollector()
    snap = col.snapshot()
    assert "effective_delay_ms" in snap
    assert "grade_adjusted_delay" in snap
    assert snap["grade_adjusted_delay"] is False

    col.set_call_delay_ms(500)
    snap2 = col.snapshot()
    assert snap2["effective_delay_ms"] == 500
    assert snap2["grade_adjusted_delay"] is True


# ---------------------------------------------------------------------------
# 7  _adjust_llm_call_rate: single burst must not ratchet on repeat cycles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adjust_llm_call_rate_no_repeat_ratchet():
    """A burst of 3+ RL calls must only bump the delay ONCE per burst.

    If subsequent grading cycles observe the same window count (old events
    still inside the 5-minute window, no new 429s), the delay must not keep
    increasing to the cap.
    """
    import unittest.mock as mock

    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.agents.pipeline_agents import GradeAgent
    from api.services.llm_metrics import LLMMetricsCollector

    # Isolated metrics collector so we don't pollute the module singleton
    isolated = LLMMetricsCollector()
    isolated.record_rate_limit()
    isolated.record_rate_limit()
    isolated.record_rate_limit()  # count = 3, at threshold
    snap = isolated.snapshot()
    assert snap["rate_limited_count"] == 3

    bus = mock.AsyncMock(spec=EventBus)
    dlq = mock.AsyncMock(spec=DLQManager)
    agent = GradeAgent(bus=bus, dlq=dlq)

    base_delay = isolated.get_call_delay_ms()

    # First call — count exceeded threshold and is higher than last recorded (0)
    # Patch the module-level singleton inside pipeline_agents
    import api.services.agents.pipeline_agents as _pa

    original = _pa._llm_metrics
    _pa._llm_metrics = isolated
    try:
        await agent._adjust_llm_call_rate(snap)
        delay_after_first = isolated.get_call_delay_ms()
        assert delay_after_first > base_delay, "delay must increase on first burst"

        # Second call with the SAME snapshot (no new 429s, window still draining)
        await agent._adjust_llm_call_rate(snap)
        delay_after_second = isolated.get_call_delay_ms()
        assert delay_after_second == delay_after_first, (
            "delay must NOT increase again when rate_limited_count has not grown"
        )

        # Third call — still the same snapshot
        await agent._adjust_llm_call_rate(snap)
        assert isolated.get_call_delay_ms() == delay_after_first, (
            "repeated cycles with identical snapshot must not ratchet to cap"
        )
    finally:
        _pa._llm_metrics = original


@pytest.mark.asyncio
async def test_adjust_llm_call_rate_new_burst_after_reset():
    """After count drops below threshold (reset), a new burst triggers again."""
    import unittest.mock as mock

    import api.services.agents.pipeline_agents as _pa
    from api.events.bus import EventBus
    from api.events.dlq import DLQManager
    from api.services.agents.pipeline_agents import GradeAgent
    from api.services.llm_metrics import LLMMetricsCollector

    isolated = LLMMetricsCollector()
    bus = mock.AsyncMock(spec=EventBus)
    dlq = mock.AsyncMock(spec=DLQManager)
    agent = GradeAgent(bus=bus, dlq=dlq)

    original = _pa._llm_metrics
    _pa._llm_metrics = isolated
    try:
        # First burst: 3 rate limits → bump once
        for _ in range(3):
            isolated.record_rate_limit()
        snap_burst1 = isolated.snapshot()
        await agent._adjust_llm_call_rate(snap_burst1)
        delay_after_burst1 = isolated.get_call_delay_ms()

        # Simulate the window draining: pass a snapshot with count below threshold.
        # We pass a minimal dict because _adjust_llm_call_rate only reads rate_limited_count.
        await agent._adjust_llm_call_rate({"rate_limited_count": 0})
        # _last_rl_count_at_adjustment resets to 0 so the next burst can trigger again.

        # Second burst: 4 new rate limits → should bump again
        for _ in range(4):
            isolated.record_rate_limit()
        snap_burst2 = isolated.snapshot()
        await agent._adjust_llm_call_rate(snap_burst2)
        delay_after_burst2 = isolated.get_call_delay_ms()

        assert delay_after_burst2 > delay_after_burst1, (
            "a new burst after the window drains must bump the delay again"
        )
    finally:
        _pa._llm_metrics = original


# ---------------------------------------------------------------------------
# active_provider routing — cloud fallback vs local inference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_provider_is_cloud_when_lm_studio_disabled(client: AsyncClient, monkeypatch):
    """active_provider equals the configured cloud provider when LM Studio is off."""
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", False)
    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "gemini")

    r = await client.get("/llm/health")
    assert r.status_code == 200
    data = r.json()
    assert data["active_provider"] == "gemini"
    assert data["provider"] == "gemini"


@pytest.mark.asyncio
async def test_active_provider_is_lmstudio_when_healthy(client: AsyncClient, monkeypatch):
    """active_provider is 'lmstudio' when local inference is enabled and healthy."""
    from api.config import settings as app_settings
    from api.services.lmstudio_provider import _health

    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "gemini")
    _health.healthy = True
    try:
        r = await client.get("/llm/health")
        assert r.status_code == 200
        data = r.json()
        assert data["active_provider"] == "lmstudio"
        assert data["provider"] == "gemini"
        assert data["lm_studio_healthy"] is True
    finally:
        _health.healthy = False


@pytest.mark.asyncio
async def test_active_provider_falls_back_when_lmstudio_unhealthy(client: AsyncClient, monkeypatch):
    """active_provider reverts to cloud when LM Studio is enabled but not healthy."""
    from api.config import settings as app_settings
    from api.services.lmstudio_provider import _health

    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "groq")
    _health.healthy = False

    r = await client.get("/llm/health")
    assert r.status_code == 200
    data = r.json()
    assert data["active_provider"] == "groq"
    assert data["lm_studio_healthy"] is False


# ---------------------------------------------------------------------------
# 10  avg_latency_ms falls back to Redis last_latency_ms when ring buffer empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_health_avg_latency_fallback_from_redis(client: AsyncClient, monkeypatch):
    """After a restart (empty ring buffer), avg_latency_ms uses redis last_latency_ms."""
    from unittest.mock import AsyncMock, patch

    from api.routes.llm_health import llm_metrics as route_metrics

    # Ensure in-process buffer has no successes
    route_metrics._records.clear()
    route_metrics._total_calls = 0
    route_metrics._daily_calls = 0

    fake_redis_metrics = {
        "total_calls": 85,
        "daily_calls": 85,
        "last_latency_ms": 1234,
        "last_success_at": "2026-05-18T10:00:00+00:00",
        "successes": 85,
        "rate_limits": 0,
        "timeouts": 0,
        "errors": 0,
    }

    mock_store = AsyncMock()
    mock_store.get_llm_metrics = AsyncMock(return_value=fake_redis_metrics)

    with patch("api.routes.llm_health.get_redis_store", return_value=mock_store):
        r = await client.get("/llm/health")

    assert r.status_code == 200
    data = r.json()
    assert data["avg_latency_ms"] == 1234, "should fall back to Redis last_latency_ms"
    assert data["total_calls_lifetime"] == 85
    assert data["last_success_at"] == "2026-05-18T10:00:00+00:00"


@pytest.mark.asyncio
async def test_llm_health_avg_latency_not_overridden_when_ring_buffer_active(
    client: AsyncClient, monkeypatch
):
    """When ring buffer has recent successes, avg_latency_ms comes from the buffer, not Redis."""
    from unittest.mock import AsyncMock, patch

    from api.services.llm_metrics import LLMMetricsCollector

    col = LLMMetricsCollector(max_records=50)
    col.record_success(latency_ms=500.0)

    fake_redis_metrics = {
        "total_calls": 100,
        "daily_calls": 100,
        "last_latency_ms": 9999,  # should NOT override the ring-buffer value
        "last_success_at": "2026-05-18T10:00:00+00:00",
        "successes": 100,
        "rate_limits": 0,
        "timeouts": 0,
        "errors": 0,
    }

    mock_store = AsyncMock()
    mock_store.get_llm_metrics = AsyncMock(return_value=fake_redis_metrics)

    with patch("api.routes.llm_health.get_redis_store", return_value=mock_store):
        with patch("api.routes.llm_health.llm_metrics", col):
            r = await client.get("/llm/health")

    assert r.status_code == 200
    data = r.json()
    assert data["avg_latency_ms"] == 500, "ring-buffer latency must not be overridden by Redis"


# ---------------------------------------------------------------------------
# LLM_PROVIDER=lmstudio routing behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_health_shows_lmstudio_model_when_provider_is_lmstudio(
    client: AsyncClient, monkeypatch
):
    """When LLM_PROVIDER=lmstudio, model field shows LM_STUDIO_MODEL."""
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LM_STUDIO_MODEL", "my-local-model-7b")

    with patch("api.routes.llm_health.get_redis_store", return_value=None):
        r = await client.get("/llm/health")

    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "my-local-model-7b"
    assert data["provider"] == "lmstudio"


@pytest.mark.asyncio
async def test_llm_health_includes_remote_localhost_mismatch_field(
    client: AsyncClient, monkeypatch
):
    """health endpoint always includes remote_localhost_mismatch field."""
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", True)
    monkeypatch.setattr(app_settings, "LM_STUDIO_HOST", "localhost")
    monkeypatch.setattr(app_settings, "LM_STUDIO_BASE_URL", "")
    monkeypatch.setattr(app_settings, "RENDER_EXTERNAL_URL", "https://my-app.onrender.com")

    with patch("api.routes.llm_health.get_redis_store", return_value=None):
        r = await client.get("/llm/health")

    assert r.status_code == 200
    data = r.json()
    assert "remote_localhost_mismatch" in data
    assert data["remote_localhost_mismatch"] is True


@pytest.mark.asyncio
async def test_llm_health_includes_llm_fallback_enabled_field(client: AsyncClient, monkeypatch):
    """health endpoint exposes llm_fallback_enabled so the dashboard can show it."""
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", False)

    with patch("api.routes.llm_health.get_redis_store", return_value=None):
        r = await client.get("/llm/health")

    assert r.status_code == 200
    data = r.json()
    assert "llm_fallback_enabled" in data
    assert data["llm_fallback_enabled"] is False


@pytest.mark.asyncio
async def test_call_llm_lmstudio_primary_no_fallback_raises(monkeypatch):
    """When LLM_PROVIDER=lmstudio and LLM_FALLBACK_ENABLED=false, failure raises immediately."""
    from api.config import settings as app_settings
    from api.services.lmstudio_provider import LMStudioUnavailableError

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", False)
    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", False)

    from api.services.llm_router import call_llm

    with patch(
        "api.services.llm_router.call_lmstudio",
        side_effect=LMStudioUnavailableError("connection refused"),
    ):
        with pytest.raises(RuntimeError, match="lmstudio_unavailable"):
            await call_llm("test prompt", "trace-id-001")


@pytest.mark.asyncio
async def test_call_llm_lmstudio_primary_does_not_call_gemini_without_key(monkeypatch):
    """When LLM_PROVIDER=lmstudio, Gemini is not called even if it's set as LLM_PROVIDER fallback."""
    from api.config import settings as app_settings
    from api.services.lmstudio_provider import LMStudioUnavailableError

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", False)
    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", False)
    monkeypatch.setattr(app_settings, "GEMINI_API_KEY", None)

    gemini_called = []

    from api.services.llm_router import call_llm

    async def _fake_gemini(*a, **kw):  # pragma: no cover
        gemini_called.append(True)
        return ({}, 0, 0.0)

    with patch(
        "api.services.llm_router.call_lmstudio",
        side_effect=LMStudioUnavailableError("offline"),
    ):
        with patch("api.services.llm_router._PROVIDERS", {"gemini": _fake_gemini}):
            with pytest.raises(RuntimeError, match="lmstudio_unavailable"):
                await call_llm("test prompt", "trace-id-002")

    assert not gemini_called, "Gemini must not be called when LLM_FALLBACK_ENABLED=false"


@pytest.mark.asyncio
async def test_call_llm_lmstudio_primary_fallback_to_cloud_when_enabled(monkeypatch):
    """When LLM_PROVIDER=lmstudio and LLM_FALLBACK_ENABLED=true, falls back to first cloud with key."""
    from api.config import settings as app_settings
    from api.services.lmstudio_provider import LMStudioUnavailableError

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", True)
    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", False)
    monkeypatch.setattr(app_settings, "GROQ_API_KEY", "gsk_fake_key")

    cloud_result = (
        {"action": "hold", "confidence": 0.5, "fallback": False, "trace_id": "t"},
        10,
        0.0,
    )

    from api.services.llm_router import call_llm

    with patch(
        "api.services.llm_router.call_lmstudio",
        side_effect=LMStudioUnavailableError("offline"),
    ):
        with patch(
            "api.services.llm_router._PROVIDERS",
            {"groq": AsyncMock(return_value=cloud_result)},
        ):
            result, _, _ = await call_llm("test prompt", "trace-id-003")

    assert result["action"] == "hold"


@pytest.mark.asyncio
async def test_active_provider_is_cloud_fallback_when_lmstudio_primary_is_down(
    client: AsyncClient, monkeypatch
):
    """active_provider is the cloud fallback when LLM_PROVIDER=lmstudio is unhealthy.

    Regression: with LLM_PROVIDER=lmstudio, LM Studio unhealthy, and
    LLM_FALLBACK_ENABLED=true, call_llm() routes to a cloud provider via
    _find_cloud_fallback(). The endpoint was computing active_provider as the
    configured provider ("lmstudio") instead of the actual serving provider.
    """
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", True)

    with patch("api.routes.llm_health._find_cloud_fallback", return_value="groq"):
        with patch("api.routes.llm_health.get_redis_store", return_value=None):
            r = await client.get("/llm/health")

    assert r.status_code == 200
    data = r.json()
    assert data["provider"] == "lmstudio"
    assert data["lm_studio_healthy"] is False
    assert data["active_provider"] == "groq", (
        "active_provider must be the cloud fallback, not 'lmstudio'"
    )


@pytest.mark.asyncio
async def test_active_provider_stays_lmstudio_when_fallback_disabled(
    client: AsyncClient, monkeypatch
):
    """active_provider stays lmstudio when fallback is off (no cloud routing)."""
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", False)

    with patch("api.routes.llm_health.get_redis_store", return_value=None):
        r = await client.get("/llm/health")

    assert r.status_code == 200
    data = r.json()
    assert data["active_provider"] == "lmstudio"


@pytest.mark.asyncio
async def test_call_llm_parse_failure_no_fallback_raises(monkeypatch):
    """When LLM_PROVIDER=lmstudio, LLM_FALLBACK_ENABLED=false, and _parse_response returns
    fallback=True (malformed/non-JSON LM Studio response), call_llm must raise rather than
    silently routing to a cloud provider."""
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", False)
    monkeypatch.setattr(app_settings, "LM_STUDIO_ENABLED", False)

    from api.services.llm_router import call_llm

    cloud_called = []

    async def _fake_cloud(*a, **kw):  # pragma: no cover
        cloud_called.append(True)
        return ({}, 0, 0.0)

    # call_lmstudio returns malformed (non-JSON) text; _parse_response sets fallback=True
    with patch(
        "api.services.llm_router.call_lmstudio",
        return_value=("not valid json {{", 5, 0.001),
    ):
        with patch("api.services.llm_router._PROVIDERS", {"groq": _fake_cloud}):
            with pytest.raises(RuntimeError, match="lmstudio_parse_failed"):
                await call_llm("test prompt", "trace-parse-001")

    assert not cloud_called, "cloud provider must not be called when fallback is disabled"


# ---------------------------------------------------------------------------
# Cooldown behaviour: should_try_local() honoured when LLM_PROVIDER=lmstudio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_llm_lmstudio_primary_respects_cooldown_fallback_enabled(monkeypatch):
    """When LLM_PROVIDER=lmstudio and should_try_local() is False, go to cloud directly.

    Regression: use_lmstudio was computed as `lm_primary OR ...`, bypassing the
    60-second cooldown whenever LLM_PROVIDER=lmstudio. This caused every call to
    block for LM_STUDIO_TIMEOUT_SECONDS before cloud fallback when LM Studio was down.
    """
    from api.config import settings as app_settings
    from api.services.lmstudio_provider import LMStudioUnavailableError

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", True)

    cloud_result = (
        {"action": "hold", "confidence": 0.5, "fallback": False, "trace_id": "t"},
        10,
        0.0,
    )
    call_lmstudio_called = []

    async def _fake_call_lmstudio(*a, **kw):  # pragma: no cover
        call_lmstudio_called.append(True)
        raise LMStudioUnavailableError("should not be called")

    from api.services.llm_router import call_llm

    with patch("api.services.llm_router.should_try_local", return_value=False):
        with patch("api.services.llm_router.call_lmstudio", side_effect=_fake_call_lmstudio):
            with patch(
                "api.services.llm_router._PROVIDERS",
                {"groq": AsyncMock(return_value=cloud_result)},
            ):
                with patch("api.services.llm_router._get_provider_key", return_value="fake-key"):
                    with patch("api.services.llm_router._find_cloud_fallback", return_value="groq"):
                        result, _, _ = await call_llm("test prompt", "trace-cooldown-001")

    assert not call_lmstudio_called, "LM Studio must not be called during cooldown"
    assert result["action"] == "hold"


@pytest.mark.asyncio
async def test_call_llm_lmstudio_primary_cooldown_no_fallback_raises(monkeypatch):
    """When LLM_PROVIDER=lmstudio, cooldown active, and fallback disabled, raise immediately."""
    from api.config import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr(app_settings, "LLM_FALLBACK_ENABLED", False)

    from api.services.llm_router import call_llm

    with patch("api.services.llm_router.should_try_local", return_value=False):
        with pytest.raises(RuntimeError, match="lmstudio_unavailable"):
            await call_llm("test prompt", "trace-cooldown-002")
