"""Memory-mode regression tests for GET /llm/health.

The endpoint reads exclusively from the in-process LLMMetricsCollector
and must never touch the DB session factory.  These tests verify:

1. Both URL forms respond 200 (root and /api prefix).
2. Response shape matches the expected schema.
3. set_db_available(False) does not affect the response — no DB is touched.
4. Recorded metrics appear correctly in the snapshot.
5. daily_calls resets to 0 when the date rolls over between snapshot() calls.
"""

from __future__ import annotations

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
    for key in ("status", "provider", "model", "timestamp", "success_rate_pct", "daily_calls"):
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
        set_db_available(False)  # leave clean for subsequent tests


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
