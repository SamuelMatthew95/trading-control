from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.mcp.read_tools import (
    _safe_limit,
    get_agent_grades_data,
    get_config_data,
    get_llm_health_data,
    get_market_data_data,
    get_positions_data,
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
    assert payload["source"] == "in_memory"


async def test_get_stream_lag_warns_when_required_stream_has_no_group(monkeypatch) -> None:
    class _Redis:
        async def xinfo_stream(self, _stream_name: str):
            return {"length": 0, "last-generated-id": "0-0"}

        async def xinfo_groups(self, stream_name: str):
            if stream_name == "signals":
                return []
            return [{"name": "workers", "pending": 0, "lag": 0, "consumers": 1}]

    async def _fake_get_redis():
        return _Redis()

    monkeypatch.setattr("api.mcp.read_tools.get_redis", _fake_get_redis)
    payload = await get_stream_lag_data()
    signals = [item for item in payload["data"]["streams"] if item.get("stream") == "signals"]
    assert signals
    assert signals[0]["health"] == "warning"
    assert signals[0]["reason"] == "no_active_consumers"


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


async def test_get_market_data_reports_total_count(monkeypatch) -> None:
    now = datetime.now(timezone.utc).isoformat()

    async def _fake_prices():
        return {
            "source": "redis_cache",
            "prices": {
                "BTC/USD": {"price": 1, "timestamp": now},
                "ETH/USD": {"price": 2, "timestamp": now},
            },
        }

    monkeypatch.setattr("api.mcp.read_tools.get_prices_payload", _fake_prices)
    payload = await get_market_data_data(limit=1)
    assert payload["data"]["total"] == 2
    assert len(payload["data"]["ticks"]) == 1


async def test_get_positions_memory_fallback_filters_non_open(monkeypatch) -> None:
    from api.runtime_state import get_runtime_store

    monkeypatch.setattr("api.mcp.read_tools.is_db_available", lambda: False)
    store = get_runtime_store()
    store.positions.clear()
    store.positions["BTC/USD"] = {"symbol": "BTC/USD", "side": "long", "qty": 1.0}
    store.positions["ETH/USD"] = {"symbol": "ETH/USD", "side": "flat", "qty": 0.0}

    payload = await get_positions_data()
    assert payload["degraded"] is True
    assert len(payload["data"]["positions"]) == 1
    assert payload["data"]["positions"][0]["symbol"] == "BTC/USD"


async def test_get_llm_health_degraded_on_full_error_rate(monkeypatch) -> None:
    class _Metrics:
        @staticmethod
        def snapshot():
            return {
                "success_rate_pct": 0.0,
                "rate_limited_count": 1,
                "effective_delay_ms": 200,
                "last_error": {"at": "2026-05-21T00:00:00+00:00"},
                "last_success_at": None,
            }

    monkeypatch.setattr("api.mcp.read_tools.llm_metrics", _Metrics())
    payload = await get_llm_health_data()
    assert payload["degraded"] is True
    assert payload["reason"] == "llm_provider_unhealthy"
