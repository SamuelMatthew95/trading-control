from __future__ import annotations

import os
from datetime import datetime

import fakeredis
import pytest_asyncio

os.environ["ENABLE_SIGNAL_SCHEDULER"] = "false"

TEST_REFERENCE_DT = datetime(2024, 6, 15, 12, 0, 0)


@pytest_asyncio.fixture
async def fake_redis():
    """Provide a fresh fakeredis async instance for each test."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield redis
    await redis.aclose()
