from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.mcp.read_tools import (
    _safe_limit,
    get_agent_grades_data,
    get_config_data,
    get_market_data_data,
    get_stream_lag_data,
)


def test_safe_limit_caps_and_defaults() -> None:
    assert _safe_limit(-1, default=20, max_value=100) == 20
    assert _safe_limit(500, default=20, max_value=100) == 100
    assert _safe_limit(50, default=20, max_value=100) == 50


def test_get_config_redacts_all_provider_keys() -> None:
    payload = get_config_data()
    secrets = payload["data"]["secrets"]
    assert secrets["mcp_shared_token"] in (None, "***redacted***")
    assert secrets["openai_api_key"] in (None, "***redacted***")
    assert secrets["anthropic_api_key"] in (None, "***redacted***")
    assert secrets["gemini_api_key"] in (None, "***redacted***")


async def test_get_stream_lag_degraded_when_redis_down(monkeypatch) -> None:
    async def _boom():
        raise RuntimeError("down")

    monkeypatch.setattr("api.mcp.read_tools.get_redis", _boom)
    payload = await get_stream_lag_data()
    assert payload["degraded"] is True
    assert payload["source"] == "memory"


async def test_get_agent_grades_filters_since(monkeypatch) -> None:
    now = datetime.now(timezone.utc)

    async def _fake(_limit: int):
        return {
            "grades": [
                {"timestamp": (now - timedelta(days=2)).isoformat(), "score": 1},
                {"timestamp": now.isoformat(), "score": 2},
            ],
            "source": "db",
        }

    monkeypatch.setattr("api.mcp.read_tools.get_grade_history_payload", _fake)
    payload = await get_agent_grades_data(since=(now - timedelta(hours=1)).isoformat())
    assert payload["data"]["total"] == 1


async def test_get_market_data_supports_symbol_filter(monkeypatch) -> None:
    async def _fake_prices():
        return {
            "source": "redis_cache",
            "prices": {
                "BTC/USD": {"price": 1, "timestamp": datetime.now(timezone.utc).isoformat()},
                "ETH/USD": {"price": 2, "timestamp": datetime.now(timezone.utc).isoformat()},
            },
        }

    monkeypatch.setattr("api.mcp.read_tools.get_prices_payload", _fake_prices)
    payload = await get_market_data_data(symbol="ETH/USD", limit=20)
    assert payload["data"]["limit"] == 20
    assert len(payload["data"]["ticks"]) == 1
    assert payload["data"]["ticks"][0]["symbol"] == "ETH/USD"


async def test_get_agent_heartbeats_uses_db_fallback(monkeypatch) -> None:
    from api.mcp.read_tools import get_agent_heartbeats_data

    async def _redis_boom():
        raise RuntimeError("redis down")

    async def _db_rows(_now_ts: int):
        return [
            {
                "agent_name": "SignalGenerator",
                "status": "active",
                "last_heartbeat": None,
                "age_seconds": 1,
                "source": "db",
                "metadata": {},
            }
        ]

    monkeypatch.setattr("api.mcp.read_tools.get_redis", _redis_boom)
    monkeypatch.setattr("api.mcp.read_tools._db_heartbeat_rows", _db_rows)

    payload = await get_agent_heartbeats_data()
    assert payload["source"] == "db"
    assert payload["degraded"] is True
    assert payload["reason"] == "redis_unavailable_using_db"


async def test_get_agent_grades_since_excludes_unparseable_when_since_set(monkeypatch) -> None:
    now = datetime.now(timezone.utc)

    async def _fake(_limit: int):
        return {
            "grades": [
                {"timestamp": "not-a-date", "score": 1},
                {"timestamp": now.isoformat(), "score": 2},
            ],
            "source": "db",
        }

    monkeypatch.setattr("api.mcp.read_tools.get_grade_history_payload", _fake)
    payload = await get_agent_grades_data(since=(now - timedelta(hours=1)).isoformat())
    assert payload["data"]["total"] == 1
