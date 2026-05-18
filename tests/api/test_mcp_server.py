from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from api.main import app
from api.mcp.server import _debug_state_has_activity, _get_decisions, _get_notifications


def test_mcp_mount_exists_on_main_app() -> None:
    """/mcp should be mounted on the main application."""
    mounted_paths = [getattr(route, "path", "") for route in app.routes]
    assert "/mcp" in mounted_paths


def _ok_app() -> Starlette:
    async def ok(_request):
        return JSONResponse({"ok": True})

    return Starlette(routes=[Route("/", ok)])


async def test_decisions_unavailable_payload_when_store_missing(monkeypatch) -> None:
    """Decisions helper returns structured unavailable payload when Redis store is absent."""
    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: None)

    payload = await _get_decisions(limit=10)

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "redis_store_not_ready"
    assert payload["items"] is None


async def test_notifications_unavailable_payload_when_store_missing(monkeypatch) -> None:
    """Notifications helper returns structured unavailable payload when Redis store is absent."""
    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: None)

    payload = await _get_notifications(limit=10)

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "redis_store_not_ready"
    assert payload["items"] is None


def test_settings_exposes_mcp_shared_token_field() -> None:
    """Config must define MCP_SHARED_TOKEN so env-based auth can be enforced."""
    from api.config import settings

    assert hasattr(settings, "MCP_SHARED_TOKEN")
    assert isinstance(settings.MCP_SHARED_TOKEN, str)


def test_debug_state_has_activity_uses_real_fields() -> None:
    payload = {
        "has_data": False,
        "counts": {
            "decisions": 1,
            "notifications": 0,
            "open_positions": 0,
            "closed_trades": 0,
            "equity_points": 0,
        },
        "latest_decision": None,
    }
    assert _debug_state_has_activity(payload) is True


def test_debug_state_has_activity_false_when_empty() -> None:
    payload = {
        "has_data": False,
        "counts": {
            "decisions": 0,
            "notifications": 0,
            "open_positions": 0,
            "closed_trades": 0,
            "equity_points": 0,
        },
        "latest_decision": None,
        "latest_notification": None,
        "latest_open_position": None,
        "latest_closed_trade": None,
    }
    assert _debug_state_has_activity(payload) is False
