from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName
from api.main import app
from api.main_state import get_trading_service


class MockTradingService:
    def analyze(self, symbol: str, price: float, signals: Any) -> dict[str, Any]:
        return {
            "DECISION": "FLAT",
            FieldName.CONFIDENCE: 0.5,
            FieldName.REASONING: "test",
            FieldName.POSITION_SIZE: None,
            FieldName.RISK_ASSESSMENT: None,
        }

    def run_shadow(self, symbol: str, price: float, signals: Any) -> dict[str, Any]:
        return {FieldName.MODE: "shadow"}

    def evaluate_shadow(self, symbol: str, observed_price: float) -> dict[str, Any]:
        return {FieldName.STATUS: "no_data"}


async def mock_get_trading_service() -> MockTradingService:
    return MockTradingService()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest_asyncio.fixture
async def client_with_mock():
    app.dependency_overrides[get_trading_service] = mock_get_trading_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_analyze_missing_body_returns_422(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/analyze", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_analyze_empty_symbol_returns_400(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/analyze", json={"symbol": "", "price": 50000})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_analyze_zero_price_returns_422(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/analyze", json={"symbol": "BTC/USD", "price": 0})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_analyze_valid_request_returns_200(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/analyze", json={"symbol": "BTC/USD", "price": 50000})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_analyze_valid_request_success_flag(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/analyze", json={"symbol": "BTC/USD", "price": 50000})
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_analyze_valid_request_decision_present(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/analyze", json={"symbol": "BTC/USD", "price": 50000})
    body = r.json()
    assert FieldName.DECISION in body[FieldName.DATA]


@pytest.mark.asyncio
async def test_shadow_analyze_missing_body_returns_422(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/shadow/analyze", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_shadow_analyze_empty_symbol_returns_400(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/shadow/analyze", json={"symbol": "", "price": 50000})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_shadow_analyze_valid_request_returns_200(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/shadow/analyze", json={"symbol": "BTC/USD", "price": 50000})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_shadow_analyze_valid_request_success_flag(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.post("/shadow/analyze", json={"symbol": "BTC/USD", "price": 50000})
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_shadow_evaluate_zero_price_returns_400(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.get("/shadow/evaluate/AAPL?observed_price=0")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_shadow_evaluate_negative_price_returns_400(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.get("/shadow/evaluate/AAPL?observed_price=-1")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_shadow_evaluate_no_data_returns_404(client_with_mock: AsyncClient) -> None:
    r = await client_with_mock.get("/shadow/evaluate/AAPL?observed_price=50000")
    assert r.status_code == 404
