"""Tests for the PaperBroker-sourced /positions and /pnl endpoints.

These run in the default memory-mode test environment (no PaperBroker wired),
so the routes serve the in-memory runtime-store mirror. They must always return
HTTP 200 with a real (possibly empty) payload — never 500.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName, PositionSide
from api.main import app
from api.runtime_state import get_runtime_store


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest.mark.asyncio
async def test_positions_empty_returns_200(client: AsyncClient) -> None:
    r = await client.get("/positions")
    assert r.status_code == 200
    body = r.json()
    assert body[FieldName.POSITIONS] == []
    assert body[FieldName.COUNT] == 0
    assert body[FieldName.SOURCE] == "in_memory"


@pytest.mark.asyncio
async def test_positions_reflects_mirrored_broker_position(client: AsyncClient) -> None:
    store = get_runtime_store()
    store.mirror_broker_position(
        "BTC/USD",
        {
            FieldName.SYMBOL: "BTC/USD",
            FieldName.SIDE: PositionSide.LONG,
            FieldName.QTY: 0.5,
            FieldName.ENTRY_PRICE: 40000.0,
            FieldName.CURRENT_PRICE: 42000.0,
        },
    )
    r = await client.get("/positions")
    assert r.status_code == 200
    body = r.json()
    assert body[FieldName.COUNT] == 1
    symbols = [p[FieldName.SYMBOL] for p in body[FieldName.POSITIONS]]
    assert "BTC/USD" in symbols


@pytest.mark.asyncio
async def test_pnl_returns_summary(client: AsyncClient) -> None:
    r = await client.get("/pnl")
    assert r.status_code == 200
    body = r.json()
    assert FieldName.SUMMARY in body
    assert FieldName.OPEN_POSITIONS in body
    assert FieldName.CLOSED_TRADES in body


@pytest.mark.asyncio
async def test_pnl_unrealized_reflects_open_position(client: AsyncClient) -> None:
    store = get_runtime_store()
    store.mirror_broker_position(
        "ETH/USD",
        {
            FieldName.SYMBOL: "ETH/USD",
            FieldName.SIDE: PositionSide.LONG,
            FieldName.QTY: 2.0,
            FieldName.ENTRY_PRICE: 2000.0,
            FieldName.CURRENT_PRICE: 2100.0,
        },
    )
    r = await client.get("/pnl")
    assert r.status_code == 200
    body = r.json()
    assert len(body[FieldName.OPEN_POSITIONS]) == 1
