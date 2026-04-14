"""Tests for GET /dashboard/pnl/paired — paired P&L endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.main import app

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMPTY_PNL = {
    "closed_trades": [],
    "open_positions": [],
    "summary": {
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "closed_trades": 0,
        "winning_trades": 0,
        "win_rate_percent": 0.0,
        "open_positions": 0,
    },
    "timestamp": datetime.now(timezone.utc).isoformat(),
}


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        yield c


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


async def test_paired_pnl_returns_expected_keys(client):
    """GET /dashboard/pnl/paired must return closed_trades, open_positions, summary."""
    with (
        patch("api.routes.dashboard_v2.MetricsAggregator") as mock_agg_cls,
        patch("api.routes.dashboard_v2.AsyncSessionFactory") as mock_factory,
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_agg = AsyncMock()
        mock_agg.get_paired_pnl = AsyncMock(return_value=_EMPTY_PNL)
        mock_agg_cls.return_value = mock_agg

        response = await client.get("/dashboard/pnl/paired")

    assert response.status_code == 200
    data = response.json()
    assert "closed_trades" in data
    assert "open_positions" in data
    assert "summary" in data
    summary = data["summary"]
    for key in (
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
        "closed_trades",
        "winning_trades",
        "win_rate_percent",
        "open_positions",
    ):
        assert key in summary, f"summary missing key: {key}"


async def test_paired_pnl_db_unavailable_returns_fallback(client):
    """When DB raises, endpoint returns a zero-filled fallback (no 500)."""
    with patch("api.routes.dashboard_v2.AsyncSessionFactory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("db_down"))
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        response = await client.get("/dashboard/pnl/paired")

    assert response.status_code == 200
    data = response.json()
    assert data["closed_trades"] == []
    assert data["open_positions"] == []
    assert data["summary"]["total_pnl"] == 0.0


# ---------------------------------------------------------------------------
# MetricsAggregator unit tests for get_paired_pnl()
# ---------------------------------------------------------------------------


async def test_get_paired_pnl_closed_trades_math():
    """get_paired_pnl() correctly aggregates realized PnL and win rate."""
    from api.services.metrics_aggregator import MetricsAggregator

    closed_rows = [
        {
            "symbol": "BTC/USD",
            "side": "sell",
            "qty": 0.1,
            "entry_price": 50000.0,
            "exit_price": 55000.0,
            "pnl": 500.0,
            "pnl_percent": 10.0,
            "grade": "A",
            "status": "filled",
            "filled_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "order_id": None,
            "execution_trace_id": "trace-1",
        },
        {
            "symbol": "ETH/USD",
            "side": "sell",
            "qty": 1.0,
            "entry_price": 3000.0,
            "exit_price": 2700.0,
            "pnl": -300.0,
            "pnl_percent": -10.0,
            "grade": "D",
            "status": "filled",
            "filled_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "order_id": None,
            "execution_trace_id": "trace-2",
        },
    ]

    def _make_result(rows):
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            _make_result(closed_rows),  # first call: closed trades
            _make_result([]),  # second call: open positions
        ]
    )

    agg = MetricsAggregator(mock_session)
    data = await agg.get_paired_pnl()

    assert len(data["closed_trades"]) == 2
    summary = data["summary"]
    assert summary["realized_pnl"] == pytest.approx(200.0)  # 500 - 300
    assert summary["closed_trades"] == 2
    assert summary["winning_trades"] == 1
    assert summary["win_rate_percent"] == pytest.approx(50.0)
    assert summary["open_positions"] == 0


async def test_get_paired_pnl_open_position_unrealized():
    """get_paired_pnl() computes unrealized PnL for open positions from Redis price."""
    import json as _json

    from api.services.metrics_aggregator import MetricsAggregator

    open_rows = [
        {
            "symbol": "BTC/USD",
            "side": "long",
            "qty": 0.1,
            "avg_cost": 50000.0,
            "unrealized_pnl": 0.0,
            "strategy_id": "strat-1",
        }
    ]

    def _make_result(rows):
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            _make_result([]),  # closed trades: empty
            _make_result(open_rows),  # open positions
        ]
    )

    # Redis returns current price of 55,000 (10% above entry)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_json.dumps({"price": 55000.0}).encode())

    agg = MetricsAggregator(mock_session)
    data = await agg.get_paired_pnl(redis_client=mock_redis)

    assert len(data["open_positions"]) == 1
    pos = data["open_positions"][0]
    # unrealized PnL = (55000 - 50000) * 0.1 = 500
    assert pos["unrealized_pnl"] == pytest.approx(500.0)
    assert pos["unrealized_pnl_pct"] == pytest.approx(10.0)
    summary = data["summary"]
    assert summary["unrealized_pnl"] == pytest.approx(500.0)
    assert summary["open_positions"] == 1


async def test_get_paired_pnl_no_redis_falls_back_to_avg_cost():
    """When no Redis client, open position unrealized PnL falls back to 0 (price = avg_cost)."""
    from api.services.metrics_aggregator import MetricsAggregator

    open_rows = [
        {
            "symbol": "BTC/USD",
            "side": "long",
            "qty": 1.0,
            "avg_cost": 50000.0,
            "unrealized_pnl": 0.0,
            "strategy_id": "strat-1",
        }
    ]

    def _make_result(rows):
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            _make_result([]),
            _make_result(open_rows),
        ]
    )

    agg = MetricsAggregator(mock_session)
    data = await agg.get_paired_pnl(redis_client=None)

    pos = data["open_positions"][0]
    # No price → falls back to avg_cost → unrealized PnL = 0
    assert pos["unrealized_pnl"] == pytest.approx(0.0)
