from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName
from api.main import app
from api.routes.trades import bot_state


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def reset_bot_state():
    bot_state.update(
        {
            FieldName.RUNNING: False,
            "status": "stopped",
            FieldName.UPTIME_MINUTES: 0,
            FieldName.ACTIVE_POSITION: None,
            FieldName.RISK_EXPOSURE: 0.0,
            FieldName.TOTAL_TRADES: 0,
            FieldName.PERFORMANCE: [0] * 30,
            FieldName.LAST_ACTION: "none",
            FieldName.LAST_ACTION_TIME: None,
        }
    )
    yield


@pytest.mark.asyncio
async def test_get_trades_returns_200(client: AsyncClient) -> None:
    r = await client.get("/trades")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_trades_success_flag(client: AsyncClient) -> None:
    r = await client.get("/trades")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_get_trades_trades_key_present(client: AsyncClient) -> None:
    r = await client.get("/trades")
    body = r.json()
    assert FieldName.TRADES in body[FieldName.DATA]


@pytest.mark.asyncio
async def test_get_trades_degraded_returns_empty_list(client: AsyncClient) -> None:
    r = await client.get("/trades")
    body = r.json()
    assert isinstance(body[FieldName.DATA][FieldName.TRADES], list)


@pytest.mark.asyncio
async def test_start_trading_returns_200(client: AsyncClient) -> None:
    r = await client.post("/trading/start")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_start_trading_success_flag(client: AsyncClient) -> None:
    r = await client.post("/trading/start")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_start_trading_status_starting(client: AsyncClient) -> None:
    r = await client.post("/trading/start")
    body = r.json()
    assert body[FieldName.DATA][FieldName.STATUS] == "starting"


@pytest.mark.asyncio
async def test_stop_trading_returns_200(client: AsyncClient) -> None:
    r = await client.post("/trading/stop")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_stop_trading_success_flag(client: AsyncClient) -> None:
    r = await client.post("/trading/stop")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_stop_trading_status_stopping(client: AsyncClient) -> None:
    r = await client.post("/trading/stop")
    body = r.json()
    assert body[FieldName.DATA][FieldName.STATUS] == "stopping"


@pytest.mark.asyncio
async def test_get_trading_status_returns_200(client: AsyncClient) -> None:
    r = await client.get("/trading/status")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_trading_status_success_flag(client: AsyncClient) -> None:
    r = await client.get("/trading/status")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_get_trading_status_running_key_present(client: AsyncClient) -> None:
    r = await client.get("/trading/status")
    body = r.json()
    assert FieldName.RUNNING in body[FieldName.DATA]


@pytest.mark.asyncio
async def test_emergency_stop_returns_200(client: AsyncClient) -> None:
    r = await client.post("/trading/emergency-stop")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_emergency_stop_success_flag(client: AsyncClient) -> None:
    r = await client.post("/trading/emergency-stop")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_emergency_stop_status_field(client: AsyncClient) -> None:
    r = await client.post("/trading/emergency-stop")
    body = r.json()
    assert body[FieldName.DATA][FieldName.STATUS] == "emergency_stopped"


@pytest.mark.asyncio
async def test_get_bots_returns_200(client: AsyncClient) -> None:
    r = await client.get("/trading/bots")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_bots_success_flag(client: AsyncClient) -> None:
    r = await client.get("/trading/bots")
    body = r.json()
    assert body[FieldName.SUCCESS] is True


@pytest.mark.asyncio
async def test_get_bots_bots_key_present(client: AsyncClient) -> None:
    r = await client.get("/trading/bots")
    body = r.json()
    assert FieldName.BOTS in body[FieldName.DATA]


@pytest.mark.asyncio
async def test_start_then_stop_running_is_false(client: AsyncClient) -> None:
    await client.post("/trading/start")
    await client.post("/trading/stop")
    r = await client.get("/trading/status")
    body = r.json()
    assert body[FieldName.DATA][FieldName.RUNNING] is False


@pytest.mark.asyncio
async def test_start_sets_running_true(client: AsyncClient) -> None:
    await client.post("/trading/start")
    r = await client.get("/trading/status")
    body = r.json()
    assert body[FieldName.DATA][FieldName.RUNNING] is True


@pytest.mark.asyncio
async def test_emergency_stop_sets_running_false(client: AsyncClient) -> None:
    await client.post("/trading/start")
    await client.post("/trading/emergency-stop")
    r = await client.get("/trading/status")
    body = r.json()
    assert body[FieldName.DATA][FieldName.RUNNING] is False


@pytest.mark.asyncio
async def test_bots_reflects_running_state(client: AsyncClient) -> None:
    await client.post("/trading/start")
    r = await client.get("/trading/bots")
    body = r.json()
    bots = body[FieldName.DATA][FieldName.BOTS]
    assert len(bots) == 1
    assert bots[0][FieldName.STATUS] == "running"
