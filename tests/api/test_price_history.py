"""Tests for the real price-history reader (terminal chart + sparklines).

It reconstructs a chronological per-symbol price series from the market_events
Redis stream — the same prices the agents act on — so the UI shows real movement
without an extra market-data call.
"""

from __future__ import annotations

import json

import fakeredis
import pytest

from api.constants import STREAM_MARKET_EVENTS, FieldName
from api.services.dashboard import system as system_module

pytestmark = pytest.mark.asyncio


async def _seed(redis, symbol: str, samples: list[tuple[float, int]]) -> None:
    for price, ts in samples:
        await redis.xadd(
            STREAM_MARKET_EVENTS,
            {
                FieldName.PAYLOAD: json.dumps(
                    {FieldName.SYMBOL: symbol, FieldName.PRICE: price, FieldName.TS: ts}
                )
            },
        )


async def test_reconstructs_chronological_series_per_symbol(monkeypatch):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    await _seed(redis, "BTC/USD", [(100.0, 1), (101.0, 2), (102.0, 3)])
    await _seed(redis, "ETH/USD", [(50.0, 1), (51.0, 2)])

    async def _get_redis():
        return redis

    monkeypatch.setattr(system_module, "get_redis", _get_redis)

    payload = await system_module.get_price_history_payload()
    history = payload[FieldName.HISTORY]

    # Newest-first stream is reversed back to chronological order per symbol.
    assert [pt[FieldName.PRICE] for pt in history["BTC/USD"]] == [100.0, 101.0, 102.0]
    assert [pt[FieldName.PRICE] for pt in history["ETH/USD"]] == [50.0, 51.0]
    assert payload["source"] == "market_events"


async def test_skips_malformed_entries(monkeypatch):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    await redis.xadd(STREAM_MARKET_EVENTS, {FieldName.PAYLOAD: "not-json"})
    await _seed(redis, "BTC/USD", [(100.0, 1)])

    async def _get_redis():
        return redis

    monkeypatch.setattr(system_module, "get_redis", _get_redis)

    payload = await system_module.get_price_history_payload()
    assert [pt[FieldName.PRICE] for pt in payload[FieldName.HISTORY]["BTC/USD"]] == [100.0]


async def test_degrades_when_redis_unavailable(monkeypatch):
    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(system_module, "get_redis", _boom)

    payload = await system_module.get_price_history_payload()
    assert payload[FieldName.HISTORY] == {}
    assert payload["source"] == "in_memory"
