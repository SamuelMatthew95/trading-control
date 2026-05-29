"""Tests for the /backtest API route.

In CI there is no Alpaca network access, so the endpoint falls back to
deterministic synthetic data — these tests assert that contract and the
response shape the dashboard panel depends on.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName
from api.main import app


@pytest_asyncio.fixture
async def client():
    # base_url must be http://localhost (TrustedHostMiddleware rejects http://test).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest.mark.asyncio
async def test_compare_returns_strategy_table(client):
    resp = await client.get("/backtest/compare?bars=400")
    assert resp.status_code == 200
    data = resp.json()

    assert data[FieldName.SOURCE] == "synthetic"  # no Alpaca network in CI
    assert data[FieldName.MODE] == "analysis"
    assert data[FieldName.BARS] == 400
    assert isinstance(data[FieldName.SUMMARY], str) and data[FieldName.SUMMARY]

    rows = data[FieldName.STRATEGIES]
    assert len(rows) == 4
    names = {r[FieldName.NAME] for r in rows}
    assert "baseline_momentum" in names
    # Pre-sorted best-return-first.
    returns = [r[FieldName.RETURN_PCT] for r in rows]
    assert returns == sorted(returns, reverse=True)
    # Every row carries the metrics the UI renders.
    for r in rows:
        assert FieldName.RETURN_PCT in r
        assert FieldName.TRADE_COUNT in r
        assert FieldName.SHARPE_RATIO in r
        assert FieldName.WIN_RATE in r

    # Challenger verdict (best candidate vs baseline) is folded into /compare.
    assert data[FieldName.CANDIDATE] is not None
    assert data[FieldName.BASELINE] == "baseline_momentum"
    assert isinstance(data[FieldName.IS_DIFFERENT], bool)
    assert isinstance(data[FieldName.BEATS_BASELINE], bool)
    assert data[FieldName.DECISION] in ("promote", "reject")
    assert isinstance(data[FieldName.REASON], str) and data[FieldName.REASON]


@pytest.mark.asyncio
async def test_compare_rejects_out_of_range_bars(client):
    resp = await client.get("/backtest/compare?bars=10")  # below ge=50
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compare_is_cached_on_second_call(client):
    # Distinct bars value so this test owns its cache key regardless of order.
    first = (await client.get("/backtest/compare?bars=420")).json()
    second = (await client.get("/backtest/compare?bars=420")).json()
    assert first[FieldName.CACHED] is False
    assert second[FieldName.CACHED] is True
    # Same inputs => identical table, served from cache rather than recomputed.
    assert first[FieldName.STRATEGIES] == second[FieldName.STRATEGIES]


@pytest.mark.asyncio
async def test_strategies_lists_lifecycle_states(client):
    from api.services.strategy_registry import StrategyRegistry, set_strategy_registry

    set_strategy_registry(StrategyRegistry())  # isolate from other tests
    resp = await client.get("/backtest/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert data[FieldName.MODE] == "registry"
    assert FieldName.CIRCUIT_BREAKER_ACTIVE in data
    by_name = {r[FieldName.NAME]: r for r in data[FieldName.STRATEGIES]}
    # Baseline is seeded live; candidates are seeded as backtested (not promoted).
    assert by_name["baseline_momentum"][FieldName.STATUS] == "live"
    assert by_name["strong_only"][FieldName.STATUS] == "backtested"
