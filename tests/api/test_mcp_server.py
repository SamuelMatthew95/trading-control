from __future__ import annotations

from api.main import app
from api.mcp.server import _debug_state_has_activity, _get_decisions, _get_notifications


def test_mcp_mount_exists_on_main_app() -> None:
    """/mcp should be mounted on the main application."""
    mounted_paths = [getattr(route, "path", "") for route in app.routes]
    assert "/mcp" in mounted_paths


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
    """Config keeps MCP_SHARED_TOKEN field for optional future auth wiring."""
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


def test_get_config_redacts_secrets() -> None:
    from api.mcp.read_tools import get_config_data

    payload = get_config_data()

    assert payload["ok"] is True
    assert payload["data"]["secrets"]["mcp_shared_token"] == "***redacted***"


async def test_get_stream_lag_degraded_when_redis_unavailable(monkeypatch) -> None:
    from api.mcp.read_tools import get_stream_lag_data

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("api.mcp.read_tools.get_redis", _boom)
    payload = await get_stream_lag_data()
    assert payload["degraded"] is True
    assert payload["reason"] == "redis_unavailable"


async def test_get_agent_grades_caps_limit(monkeypatch) -> None:
    from api.mcp.read_tools import get_agent_grades_data

    async def _fake(limit: int):
        return {"grades": [], "total": 0, "source": "in_memory", "limit_seen": limit}

    monkeypatch.setattr("api.mcp.read_tools.get_grade_history_payload", _fake)
    payload = await get_agent_grades_data(limit=999)
    assert payload["degraded"] is True
