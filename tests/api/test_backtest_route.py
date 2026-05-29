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
    # Active (signal-producing) strategies rank first by return; inert
    # "NO SIGNALS" strategies sort last so a 0-trade 0.00% never outranks one
    # that actually traded.
    active_returns = [r[FieldName.RETURN_PCT] for r in rows if r[FieldName.TRADE_COUNT] > 0]
    assert active_returns == sorted(active_returns, reverse=True)
    first_inert = next((i for i, r in enumerate(rows) if r[FieldName.TRADE_COUNT] == 0), len(rows))
    assert all(rows[i][FieldName.TRADE_COUNT] > 0 for i in range(first_inert))
    # Every row carries the metrics the UI renders, including the signal count.
    for r in rows:
        assert FieldName.RETURN_PCT in r
        assert FieldName.TRADE_COUNT in r
        assert FieldName.SIGNALS in r
        assert FieldName.SHARPE_RATIO in r
        assert FieldName.WIN_RATE in r

    # Challenger verdict (best candidate vs baseline) is folded into /compare.
    assert data[FieldName.CANDIDATE] is not None
    assert data[FieldName.BASELINE] == "baseline_momentum"
    assert isinstance(data[FieldName.IS_DIFFERENT], bool)
    assert isinstance(data[FieldName.BEATS_BASELINE], bool)
    assert data[FieldName.DECISION] in ("promote", "reject", "insufficient_data")
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
async def test_compare_force_bypasses_cache(client):
    """The on-demand Run-now button passes force=true to recompute, never cached."""
    first = (await client.get("/backtest/compare?bars=430")).json()
    forced = (await client.get("/backtest/compare?bars=430&force=true")).json()
    assert first[FieldName.CACHED] is False
    assert forced[FieldName.CACHED] is False  # force always recomputes


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
    # Baseline is seeded live; candidates run in shadow (a ChallengerAgent each).
    assert by_name["baseline_momentum"][FieldName.STATUS] == "live"
    assert by_name["strong_only"][FieldName.STATUS] == "shadow"
    assert by_name["confirmed_trend"][FieldName.STATUS] == "shadow"


@pytest.mark.asyncio
async def test_distribution_endpoint_returns_per_timeframe_stats(client):
    resp = await client.get("/backtest/distribution?bars=400")
    assert resp.status_code == 200
    data = resp.json()

    assert data[FieldName.MODE] == "distribution"
    assert data[FieldName.SOURCE] == "synthetic"  # no Alpaca network in CI
    assert data[FieldName.BARS] == 400

    blocks = data[FieldName.TIMEFRAMES]
    assert isinstance(blocks, list) and blocks
    for b in blocks:
        assert {"p50", "p95", "p99"} <= set(b["abs_pct"])
        for t in b["thresholds"]:
            assert 0.0 <= t["percentile"] <= 100.0
            assert 0.0 <= t["hit_rate"] <= 1.0
    # Coarser timeframes accumulate bigger moves than the 1-bar view.
    by_tf = {b["timeframe_bars"]: b for b in blocks}
    assert by_tf[max(by_tf)]["abs_pct"]["p99"] >= by_tf[1]["abs_pct"]["p99"]
