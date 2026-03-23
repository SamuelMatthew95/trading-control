from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.config import Settings, parse_csv_env
from api.observability import MetricsStore
from api.security import enforce_api_key
from api.utils import with_retries


def _build_request(
    path: str, method: str = "GET", api_key: str | None = None
) -> Request:
    headers = []
    if api_key is not None:
        headers.append((b"x-api-key", api_key.encode("utf-8")))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


def test_parse_csv_env_strips_and_ignores_empty_values():
    parsed = parse_csv_env(" https://a.com, ,https://b.com ,, localhost ")
    assert parsed == ["https://a.com", "https://b.com", "localhost"]


def test_settings_production_requires_secret_and_database():
    with pytest.raises(ValueError):
        Settings(NODE_ENV="production")


def test_enforce_api_key_allows_unprotected_route(monkeypatch):
    from api import security

    monkeypatch.setattr(security.settings, "API_SECRET_KEY", "top-secret")
    request = _build_request("/api/health")
    enforce_api_key(request)


def test_enforce_api_key_rejects_missing_or_wrong_key(monkeypatch):
    from api import security

    monkeypatch.setattr(security.settings, "API_SECRET_KEY", "top-secret")

    with pytest.raises(HTTPException) as missing:
        enforce_api_key(_build_request("/api/analyze"))
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as wrong:
        enforce_api_key(_build_request("/api/analyze", api_key="bad"))
    assert wrong.value.status_code == 401


def test_enforce_api_key_accepts_matching_key(monkeypatch):
    from api import security

    monkeypatch.setattr(security.settings, "API_SECRET_KEY", "top-secret")
    enforce_api_key(_build_request("/api/analyze", api_key="top-secret"))


def test_with_retries_succeeds_after_transient_failures(monkeypatch):
    from api import utils

    monkeypatch.setattr(utils.settings, "MAX_RETRIES", 2)
    monkeypatch.setattr(utils.settings, "RETRY_BACKOFF_MS", 0)

    attempts = {"count": 0}

    async def flaky_operation():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary failure")
        return "ok"

    result = asyncio.run(with_retries(flaky_operation))
    assert result == "ok"
    assert attempts["count"] == 3


def test_with_retries_raises_after_max_attempts(monkeypatch):
    from api import utils

    monkeypatch.setattr(utils.settings, "MAX_RETRIES", 1)
    monkeypatch.setattr(utils.settings, "RETRY_BACKOFF_MS", 0)

    async def always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        asyncio.run(with_retries(always_fail))


def test_metrics_store_snapshot_includes_calculated_fields():
    store = MetricsStore()
    store.register_request(100)
    store.register_request(300, is_error=True)
    store.update_agent("SIGNAL_AGENT", "running", current_task="analyze AAPL")
    store.log_event("task_started", task="analyze")

    snapshot = store.snapshot()

    assert snapshot["total_requests"] == 2
    assert snapshot["total_errors"] == 1
    assert snapshot["error_rate"] == 50.0
    assert snapshot["avg_latency_ms"] == 200.0
    assert snapshot["p95_latency_ms"] in {100, 300}
    assert snapshot["agent_status"][0]["name"] == "SIGNAL_AGENT"
    assert snapshot["recent_events"][0]["event_type"] == "task_started"
