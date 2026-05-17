from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from api.main import app
from api.mcp.server import _TokenGuardApp, get_decisions, get_notifications


def test_mcp_mount_exists_not_404() -> None:
    """/mcp should be mounted and never return 404."""
    with TestClient(app) as client:
        response = client.get("/mcp")
    assert response.status_code != 404


def test_token_guard_blocks_without_header_when_configured(monkeypatch) -> None:
    """Token guard enforces HTTP-level bearer auth when token is configured."""
    monkeypatch.setattr("api.mcp.server.settings.MCP_SHARED_TOKEN", "secret-token")

    guarded = _TokenGuardApp(
        lambda scope, receive, send: JSONResponse({"ok": True})(scope, receive, send)
    )

    with TestClient(guarded) as client:
        response = client.get("/")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_token_guard_allows_with_valid_header(monkeypatch) -> None:
    """Token guard passes through when bearer header is valid."""
    monkeypatch.setattr("api.mcp.server.settings.MCP_SHARED_TOKEN", "secret-token")

    guarded = _TokenGuardApp(
        lambda scope, receive, send: JSONResponse({"ok": True})(scope, receive, send)
    )

    with TestClient(guarded) as client:
        response = client.get("/", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_decisions_unavailable_payload_when_store_missing(monkeypatch) -> None:
    """Decisions tool returns structured unavailable payload when Redis store is absent."""
    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: None)

    payload = await get_decisions(limit=10)

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "redis_store_not_ready"
    assert payload["items"] is None


async def test_notifications_unavailable_payload_when_store_missing(monkeypatch) -> None:
    """Notifications tool returns structured unavailable payload when Redis store is absent."""
    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: None)

    payload = await get_notifications(limit=10)

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "redis_store_not_ready"
    assert payload["items"] is None
