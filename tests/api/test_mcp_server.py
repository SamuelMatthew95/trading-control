from __future__ import annotations

from api.main import app
from api.mcp.server import (
    _classify_health_tool,
    _debug_state_has_activity,
    _get_debug_state_tool,
    _get_decisions,
    _get_health_summary_tool,
    _get_notifications,
    _get_performance_trends_tool,
    _get_pnl_tool,
    _get_service_health_tool,
    _get_trade_feed_tool,
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


async def test_notifications_normalize_historical_fallback_from_decisions(monkeypatch) -> None:
    store = None

    class _Store:
        async def list_decisions(self, limit: int, action: str | None = None):
            nonlocal store
            store = self
            self.last_limit = limit
            return [
                {
                    "trace_id": "t-1",
                    "action": "buy",
                    "symbol": "BTC/USD",
                    "reason": "fallback:skip_reasoning",
                    "llm_succeeded": False,
                }
            ]

        async def list_notifications(self, limit: int):
            return [
                {
                    "trace_id": "t-1",
                    "type": "trade_signal",
                    "title": "BUY signal — BTC/USD",
                    "severity": "info",
                    "action": "buy",
                }
            ]

    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: _Store())
    payload = await _get_notifications(limit=10)
    item = payload["data"]["items"][0]
    assert item["type"] == "fallback_trade_blocked"
    assert item["notification_type"] == "decision_degraded"
    assert item["action"] == "hold"
    assert item["original_action"] == "buy"
    assert item["llm_succeeded"] is False
    assert getattr(store, "last_limit", None) == 10000


async def test_debug_state_normalizes_latest_notification_from_fallback_decision(
    monkeypatch,
) -> None:
    class _Store:
        async def list_decisions(self, limit: int, action: str | None = None):
            return [
                {
                    "trace_id": "t-1",
                    "action": "sell",
                    "symbol": "BTC/USD",
                    "reasoning_summary": "fallback due to LLM outage",
                    "llm_succeeded": False,
                }
            ]

    async def _debug_payload():
        return {
            "latest_notification": {
                "trace_id": "t-1",
                "type": "trade_signal",
                "title": "SELL signal — BTC/USD",
                "severity": "info",
            }
        }

    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: _Store())
    monkeypatch.setattr("api.mcp.server.get_debug_state_payload", _debug_payload)
    payload = await _get_debug_state_tool()
    latest = payload["data"]["latest_notification"]
    assert latest["type"] == "fallback_trade_blocked"
    assert latest["severity"] == "warning"
    assert latest["action"] == "hold"


async def test_debug_state_normalization_is_read_only(monkeypatch) -> None:
    class _Store:
        async def list_decisions(self, limit: int, action: str | None = None):
            return [
                {
                    "trace_id": "t-1",
                    "action": "sell",
                    "symbol": "AAPL",
                    "reason": "fallback:skip_reasoning",
                    "llm_succeeded": False,
                }
            ]

    latest_notification = {
        "id": "n-1",
        "trace_id": "t-1",
        "type": "trade_signal",
        "title": "SELL signal — AAPL",
        "severity": "info",
        "action": "sell",
        "read": False,
        "timestamp": "2026-05-21T00:00:00+00:00",
        "symbol": "AAPL",
    }

    async def _debug_payload():
        return {"latest_notification": latest_notification}

    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: _Store())
    monkeypatch.setattr("api.mcp.server.get_debug_state_payload", _debug_payload)
    payload = await _get_debug_state_tool()
    normalized = payload["data"]["latest_notification"]
    assert normalized["type"] == "fallback_trade_blocked"
    assert normalized["notification_type"] == "decision_degraded"
    assert normalized["original_action"] == "sell"
    assert normalized["action"] == "hold"
    assert normalized["severity"] == "warning"
    assert latest_notification["type"] == "trade_signal"
    assert latest_notification["action"] == "sell"


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
        await _get_service_health_tool(),
        await _get_debug_state_tool(),
        await _get_pnl_tool(),
        await _get_trade_feed_tool(),
        await _get_performance_trends_tool(),
        await _get_health_summary_tool(),
        await _classify_health_tool(),
    ]:
        assert payload.get("ok") is not None
        assert payload.get("degraded") is not None
        assert payload.get("source") is not None
        assert payload.get("generated_at") is not None
        assert isinstance(payload.get("data"), dict)
        assert "status" not in payload


async def test_wrap_payload_normalizes_non_canonical_source(monkeypatch) -> None:
    async def _raw_payload():
        return {"source": "redis_hydrated", "counts": {}}

    monkeypatch.setattr("api.mcp.server.get_debug_state_payload", _raw_payload)
    payload = await _get_debug_state_tool()
    assert payload["source"] == "in_memory"
    assert payload["data"]["upstream_source"] == "redis_hydrated"


async def test_health_summary_marks_degraded_for_raw_db_fallback(monkeypatch) -> None:
    async def _debug_payload():
        return {"source": "in_memory", "counts": {}}

    async def _pnl_payload():
        return {"source": "db", "pnl": []}

    async def _trade_feed_payload(limit: int, session_id: str | None):
        return {"source": "db_error", "empty_reason": "db_degraded", "trades": []}

    monkeypatch.setattr("api.mcp.server.get_debug_state_payload", _debug_payload)
    monkeypatch.setattr("api.mcp.server.get_pnl_payload", _pnl_payload)
    monkeypatch.setattr("api.mcp.server.get_trade_feed_payload", _trade_feed_payload)

    payload = await _get_health_summary_tool()
    assert payload["ok"] is False
    assert payload["degraded"] is True
    assert payload["reason"] == "component_unavailable"


async def test_service_health_degraded_when_db_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("api.mcp.server.is_db_available", lambda: False)
    payload = await _get_service_health_tool()
    assert payload["ok"] is True
    assert payload["degraded"] is True
    assert payload["reason"] == "db_unavailable"


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


async def test_classify_health_degraded_when_db_unavailable(monkeypatch) -> None:
    async def _debug_payload():
        return {"has_data": True, "counts": {"decisions": 1}}

    monkeypatch.setattr("api.mcp.server.get_debug_state_payload", _debug_payload)
    monkeypatch.setattr("api.mcp.server.is_db_available", lambda: False)
    payload = await _classify_health_tool()
    assert payload["ok"] is True
    assert payload["degraded"] is True
    assert payload["reason"] == "db_unavailable"
    assert payload["data"]["classification"] == "expected_memory_mode_noise"


async def test_health_summary_reports_fallback_hold_decision_mode(monkeypatch) -> None:
    class _Store:
        async def list_decisions(self, limit: int, action: str | None = None):
            return [
                {
                    "trace_id": "t-1",
                    "action": "hold",
                    "reasoning_summary": "fallback:skip_reasoning",
                    "llm_succeeded": False,
                }
            ]

        async def list_notifications(self, limit: int):
            return []

    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: _Store())
    payload = await _get_health_summary_tool()
    assert payload["data"]["decision_mode"] == "fallback_hold"
    assert payload["data"]["llm_succeeded_recently"] is False
    assert payload["data"]["reasoning_status"] == "degraded"


async def test_classify_health_keeps_ok_true_for_fallback_hold_signal(monkeypatch) -> None:
    class _Store:
        async def list_decisions(self, limit: int, action: str | None = None):
            return [
                {
                    "trace_id": "t-1",
                    "action": "hold",
                    "reasoning_summary": "fallback:skip_reasoning",
                    "llm_succeeded": False,
                }
            ]

        async def list_notifications(self, limit: int):
            return []

    async def _debug_payload():
        return {"has_data": True, "counts": {"decisions": 1}}

    monkeypatch.setattr("api.mcp.server.get_redis_store", lambda: _Store())
    monkeypatch.setattr("api.mcp.server.get_debug_state_payload", _debug_payload)
    monkeypatch.setattr("api.mcp.server.is_db_available", lambda: True)
    payload = await _classify_health_tool()
    assert payload["ok"] is True
    assert payload["degraded"] is True
    assert payload["reason"] == "decision_reasoning_degraded"


async def test_trade_feed_wrapper_adds_empty_reason_when_count_zero(monkeypatch) -> None:
    async def _trade_feed_payload(limit: int, session_id: str | None):
        return {"trades": [], "count": 0, "source": "in_memory"}

    monkeypatch.setattr("api.mcp.server.get_trade_feed_payload", _trade_feed_payload)
    payload = await _get_trade_feed_tool()
    assert payload["data"]["empty_reason"] == "no_trade_lifecycle_events"


async def test_pnl_wrapper_does_not_add_empty_reason_to_error_payload(monkeypatch) -> None:
    async def _bad_pnl_payload():
        return {"ok": False, "degraded": True, "reason": "component_unavailable", "data": {}}

    monkeypatch.setattr("api.mcp.server.get_pnl_payload", _bad_pnl_payload)
    payload = await _get_pnl_tool()
    assert payload["ok"] is False
    assert "empty_reason" not in payload["data"]
