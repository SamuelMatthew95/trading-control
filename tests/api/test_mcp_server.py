from __future__ import annotations

from api.main import app
from api.mcp.server import (
    _debug_state_has_activity,
    _get_decisions,
    _get_notifications,
    classify_health,
    get_debug_state,
    get_health_summary,
    get_performance_trends,
    get_pnl,
    get_service_health,
    get_trade_feed,
)


def test_mcp_mount_exists_on_main_app() -> None:
    """/mcp should be mounted on the main application."""
    mounted_paths = [getattr(route, "path", "") for route in app.routes]
    assert "/mcp" in mounted_paths


async def test_decisions_unavailable_payload_when_store_missing(monkeypatch) -> None:
    """Decisions helper returns structured unavailable payload when Redis store is absent."""
    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: None)

    payload = await _get_decisions(limit=10)

    assert payload["ok"] is False
    assert payload["reason"] == "redis_store_not_ready"
    assert payload["data"]["items"] == []
    assert "status" not in payload


async def test_notifications_unavailable_payload_when_store_missing(monkeypatch) -> None:
    """Notifications helper returns structured unavailable payload when Redis store is absent."""
    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: None)

    payload = await _get_notifications(limit=10)

    assert payload["ok"] is False
    assert payload["reason"] == "redis_store_not_ready"
    assert payload["data"]["items"] == []
    assert "status" not in payload


async def test_mcp_tools_standard_envelope(monkeypatch) -> None:
    async def _ok_payload():
        return {
            "ok": True,
            "degraded": False,
            "source": "in_memory",
            "generated_at": "x",
            "data": {},
        }

    monkeypatch.setattr("api.mcp.server.get_debug_state_payload", _ok_payload)
    monkeypatch.setattr("api.mcp.server.get_pnl_payload", _ok_payload)
    monkeypatch.setattr("api.mcp.server.get_performance_trends_payload", _ok_payload)
    monkeypatch.setattr(
        "api.mcp.server.get_trade_feed_payload", lambda limit, session_id: _ok_payload()
    )

    for payload in [
        await get_service_health(),
        await get_debug_state(),
        await get_pnl(),
        await get_trade_feed(),
        await get_performance_trends(),
        await get_health_summary(),
        await classify_health(),
    ]:
        assert payload.get("ok") is not None
        assert payload.get("degraded") is not None
        assert payload.get("source") is not None
        assert payload.get("generated_at") is not None
        assert isinstance(payload.get("data"), dict)
        assert "status" not in payload


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
