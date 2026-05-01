"""Tests for api/services/llm_router.py — semaphore and general module checks.

Regression coverage for:
- Fix: _gemini_semaphore added at module level with value=2 to cap concurrent
  Gemini calls and stay within the 15 RPM free-tier limit.
"""

from __future__ import annotations

import asyncio

import pytest

# ---------------------------------------------------------------------------
# _gemini_semaphore
# ---------------------------------------------------------------------------


def test_gemini_semaphore_exists_and_has_value_two() -> None:
    """_gemini_semaphore must be a Semaphore initialised with value=2."""
    from api.services.llm_router import _gemini_semaphore

    assert isinstance(_gemini_semaphore, asyncio.Semaphore)
    assert _gemini_semaphore._value == 2


@pytest.mark.asyncio
async def test_gemini_semaphore_blocks_third_concurrent_acquire() -> None:
    """After two concurrent acquires, a third must block (semaphore at capacity).

    We verify the blocking behaviour by attempting a third acquire with a very
    short timeout; it must time out rather than succeed immediately.
    """
    from api.services.llm_router import _gemini_semaphore

    # Acquire the semaphore twice (consuming all available slots)
    await _gemini_semaphore.acquire()
    await _gemini_semaphore.acquire()

    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_gemini_semaphore.acquire(), timeout=0.05)
    finally:
        # Always release both slots so subsequent tests are not affected
        _gemini_semaphore.release()
        _gemini_semaphore.release()
