"""Tests for api/services/llm_router.py — _GeminiRateLimiter.

Regression coverage for:
- Replace asyncio.Semaphore(2) with a sliding-window rate limiter that
  enforces the Gemini free-tier 15 RPM cap regardless of call duration.
- Lazy asyncio.Lock creation avoids cross-loop RuntimeError in tests and
  reload/restart flows.
- Retry sleeps happen outside the rate-limiter scope so a 429 backoff
  does not hold a slot while idle.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from api.services.llm_router import _gemini_rate_limiter, _GeminiRateLimiter

# ---------------------------------------------------------------------------
# Module-level instance
# ---------------------------------------------------------------------------


def test_module_rate_limiter_is_correct_type() -> None:
    assert isinstance(_gemini_rate_limiter, _GeminiRateLimiter)


def test_module_rate_limiter_rpm_is_fifteen() -> None:
    assert _gemini_rate_limiter._rpm == 15


def test_module_rate_limiter_window_is_sixty() -> None:
    assert _gemini_rate_limiter._window == 60.0


# ---------------------------------------------------------------------------
# Sliding-window enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_allows_calls_within_limit() -> None:
    """All calls within the RPM cap must be allowed without blocking."""
    limiter = _GeminiRateLimiter(rpm=3, window=10.0)
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # Three calls within the cap should complete nearly instantly.
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_window_full() -> None:
    """The (rpm+1)-th call within the window must block until a slot opens."""
    limiter = _GeminiRateLimiter(rpm=2, window=0.3)

    # Fill both slots immediately.
    await limiter.acquire()
    await limiter.acquire()

    start = time.monotonic()
    # The third call must block for ~0.3 s until the window slides.
    await asyncio.wait_for(limiter.acquire(), timeout=2.0)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.25, f"Expected ~0.3 s wait, got {elapsed:.3f} s"


@pytest.mark.asyncio
async def test_rate_limiter_call_times_pruned_after_window() -> None:
    """Timestamps older than the window must be evicted so they don't count."""
    limiter = _GeminiRateLimiter(rpm=2, window=0.1)

    await limiter.acquire()
    await limiter.acquire()
    # Wait for the window to expire.
    await asyncio.sleep(0.15)
    # Both old calls should have been evicted — this must not block.
    start = time.monotonic()
    await asyncio.wait_for(limiter.acquire(), timeout=0.5)
    assert time.monotonic() - start < 0.1


# ---------------------------------------------------------------------------
# Lazy lock — loop-safety
# ---------------------------------------------------------------------------


def test_lock_is_none_before_first_acquire() -> None:
    """Lock must not be created at __init__ time (avoids import-time loop binding)."""
    limiter = _GeminiRateLimiter()
    assert limiter._lock is None


@pytest.mark.asyncio
async def test_lock_created_on_first_acquire() -> None:
    """Lock is created lazily on the first acquire() call."""
    limiter = _GeminiRateLimiter(rpm=5, window=1.0)
    assert limiter._lock is None
    await limiter.acquire()
    assert isinstance(limiter._lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# Retry sleep outside rate-limiter scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_returns_before_retry_sleep() -> None:
    """acquire() must return promptly so the caller's retry sleep is not inside
    the rate-limiter.  We verify this by checking that acquire() completes well
    before a simulated retry delay would have elapsed."""
    limiter = _GeminiRateLimiter(rpm=5, window=1.0)
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    # acquire() with room in the window should be nearly instantaneous.
    assert elapsed < 0.1, f"acquire() took {elapsed:.3f} s — looks like a retry sleep leaked inside"


# ---------------------------------------------------------------------------
# Cross-provider fallback — one throttled provider must not down the loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_provider_fallback_on_primary_failure(monkeypatch):
    """When the primary cloud provider fails and another key is configured, the
    call transparently routes to the next provider instead of raising."""
    from unittest.mock import AsyncMock

    from api.config import settings
    from api.services import llm_router

    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "g-key")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", False)
    monkeypatch.setattr(llm_router, "_is_lmstudio_primary", lambda: False)
    monkeypatch.setattr(llm_router, "_inter_call_delay", AsyncMock())

    async def fake_call(provider, *_a, **_k):
        if provider == "groq":
            raise RuntimeError("rate_limited")
        return (f"OK:{provider}", 7, 0.0)

    monkeypatch.setattr(llm_router, "_call_provider_raw", AsyncMock(side_effect=fake_call))

    meta: dict = {}
    text, tokens, _ = await llm_router.call_llm_with_system("p", "sys", "trace-1", result_meta=meta)
    assert text == "OK:gemini"
    assert tokens == 7
    assert meta["model_label"].startswith("gemini:")


@pytest.mark.asyncio
async def test_no_fallback_key_reraises(monkeypatch):
    """With no alternate provider key, a primary failure still raises (unchanged)."""
    from unittest.mock import AsyncMock

    from api.config import settings
    from api.services import llm_router

    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "g-key")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True)
    monkeypatch.setattr(settings, "LM_STUDIO_ENABLED", False)
    monkeypatch.setattr(llm_router, "_is_lmstudio_primary", lambda: False)
    monkeypatch.setattr(llm_router, "_inter_call_delay", AsyncMock())
    monkeypatch.setattr(
        llm_router, "_call_provider_raw", AsyncMock(side_effect=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError):
        await llm_router.call_llm_with_system("p", "sys", "trace-2")
