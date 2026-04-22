from __future__ import annotations

import os
from datetime import datetime

import pytest
import pytest_asyncio

import fakeredis
from api.core.writer.safe_writer import SafeWriter
from api.in_memory_store import InMemoryStore
from api.runtime_state import set_db_available, set_runtime_store

os.environ.setdefault("ENABLE_SIGNAL_SCHEDULER", "false")

TEST_REFERENCE_DT = datetime(2024, 6, 15, 12, 0, 0)


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    """Reset global runtime state before every test to prevent store pollution.

    Without this, tests that call agent process() methods (e.g. signal_generator)
    leave events in the global InMemoryStore, causing unrelated resilience tests
    that expect an empty store to fail non-deterministically based on test order.
    """
    set_runtime_store(InMemoryStore())
    set_db_available(False)


@pytest_asyncio.fixture
async def fake_redis():
    """Provide a fresh fakeredis async instance for each test."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield redis
    await redis.aclose()


@pytest.fixture
def safe_writer() -> SafeWriter:
    """Provide a SafeWriter instance for pure unit tests."""
    return SafeWriter(session_factory=None)
