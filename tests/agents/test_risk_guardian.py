"""Tests for RiskGuardian — position-level and portfolio-level risk enforcement."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.constants import (
    DAILY_LOSS_LIMIT_PCT,
    DEFAULT_PAPER_CASH,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_PRICES,
    STOP_LOSS_PCT,
    STREAM_DECISIONS,
    STREAM_RISK_ALERTS,
    TAKE_PROFIT_PCT,
)
from api.events.bus import EventBus
from api.services.agents.risk_guardian import RiskGuardian

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(price: float | None = 50_000.0, daily_pnl: float = 0.0) -> AsyncMock:
    redis = AsyncMock()

    async def _get(key):
        if key == REDIS_KEY_PRICES.format(symbol="BTC/USD") and price is not None:
            return json.dumps({"price": price}).encode()
        return None

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(return_value=True)
    return redis


def _make_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_position(
    symbol: str = "BTC/USD",
    side: str = "long",
    qty: float = 1.0,
    avg_cost: float = 50_000.0,
    strategy_id: str = "strat-1",
) -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "avg_cost": avg_cost,
        "strategy_id": strategy_id,
    }


class _FakeSession:
    def __init__(self, positions=None, daily_pnl=0.0):
        self._positions = positions or []
        self._daily_pnl = daily_pnl

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        if "FROM positions" in sql:
            result.mappings.return_value.all.return_value = self._positions
        else:
            # trade_performance daily pnl query
            result.scalar.return_value = self._daily_pnl
        return result


class _FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# Stop-loss tests
# ---------------------------------------------------------------------------


async def test_long_stop_loss_publishes_sell():
    """Long position at -6% (> STOP_LOSS_PCT) must publish a sell to STREAM_DECISIONS."""
    avg_cost = 50_000.0
    current_price = avg_cost * (1 - STOP_LOSS_PCT - 0.01)  # just beyond threshold

    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=current_price)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    published_streams = [call.args[0] for call in bus.publish.call_args_list]
    assert STREAM_DECISIONS in published_streams
    decision = next(c.args[1] for c in bus.publish.call_args_list if c.args[0] == STREAM_DECISIONS)
    assert decision["action"] == "sell"
    assert decision["symbol"] == "BTC/USD"
    assert decision["signal_confidence"] == 1.0
    assert decision["reasoning_score"] == 1.0
    assert "stop_loss" in decision["primary_edge"]


async def test_short_stop_loss_publishes_buy():
    """Short position where price rises > STOP_LOSS_PCT above entry must publish buy."""
    avg_cost = 50_000.0
    current_price = avg_cost * (1 + STOP_LOSS_PCT + 0.01)  # adverse move for short

    positions = [_make_position(side="short", avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=current_price)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    published_streams = [call.args[0] for call in bus.publish.call_args_list]
    assert STREAM_DECISIONS in published_streams
    decision = next(c.args[1] for c in bus.publish.call_args_list if c.args[0] == STREAM_DECISIONS)
    assert decision["action"] == "buy"
    assert "stop_loss" in decision["primary_edge"]


# ---------------------------------------------------------------------------
# Take-profit tests
# ---------------------------------------------------------------------------


async def test_long_take_profit_publishes_sell():
    """Long position at +11% (> TAKE_PROFIT_PCT) must trigger a sell."""
    avg_cost = 50_000.0
    current_price = avg_cost * (1 + TAKE_PROFIT_PCT + 0.01)

    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=current_price)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    published_streams = [call.args[0] for call in bus.publish.call_args_list]
    assert STREAM_DECISIONS in published_streams
    decision = next(c.args[1] for c in bus.publish.call_args_list if c.args[0] == STREAM_DECISIONS)
    assert decision["action"] == "sell"
    assert "take_profit" in decision["primary_edge"]


async def test_short_take_profit_publishes_buy():
    """Short position where price falls > TAKE_PROFIT_PCT below entry must trigger buy."""
    avg_cost = 50_000.0
    current_price = avg_cost * (1 - TAKE_PROFIT_PCT - 0.01)

    positions = [_make_position(side="short", avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=current_price)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    published_streams = [call.args[0] for call in bus.publish.call_args_list]
    assert STREAM_DECISIONS in published_streams
    decision = next(c.args[1] for c in bus.publish.call_args_list if c.args[0] == STREAM_DECISIONS)
    assert decision["action"] == "buy"
    assert "take_profit" in decision["primary_edge"]


# ---------------------------------------------------------------------------
# No-op tests
# ---------------------------------------------------------------------------


async def test_position_within_bounds_no_close():
    """Position within stop-loss AND take-profit bounds must NOT publish anything."""
    avg_cost = 50_000.0
    current_price = avg_cost * 1.02  # +2% — within bounds

    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=current_price)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_no_positions_no_action():
    """Empty positions table must result in zero publishes."""
    session = _FakeSession(positions=[])
    redis = _make_redis()
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_no_price_in_redis_skips_position():
    """If current price is not in Redis, the position is skipped (no action taken)."""
    positions = [_make_position()]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=None)  # no price available
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_zero_avg_cost_skips_position():
    """Position with avg_cost=0 must be skipped (prevents division-by-zero)."""
    positions = [_make_position(avg_cost=0.0)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=50_000.0)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Daily loss limit
# ---------------------------------------------------------------------------


async def test_daily_loss_activates_kill_switch():
    """If today's PnL < -(portfolio * DAILY_LOSS_LIMIT_PCT) the kill switch must be set."""
    threshold = -(DEFAULT_PAPER_CASH * DAILY_LOSS_LIMIT_PCT)
    daily_pnl = threshold - 1.0  # just over the limit

    session = _FakeSession(daily_pnl=daily_pnl)
    redis = _make_redis()
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_daily_loss()

    # Kill switch must be set in Redis
    set_calls = [call.args for call in redis.set.call_args_list]
    set_keys = [args[0] for args in set_calls]
    assert REDIS_KEY_KILL_SWITCH in set_keys

    # STREAM_RISK_ALERTS must be published
    published_streams = [call.args[0] for call in bus.publish.call_args_list]
    assert STREAM_RISK_ALERTS in published_streams
    alert = next(c.args[1] for c in bus.publish.call_args_list if c.args[0] == STREAM_RISK_ALERTS)
    assert alert["kill_switch_activated"] is True
    assert alert["type"] == "daily_loss_limit_breached"


async def test_daily_loss_within_limit_no_kill_switch():
    """Daily PnL above the limit must NOT activate the kill switch."""
    threshold = -(DEFAULT_PAPER_CASH * DAILY_LOSS_LIMIT_PCT)
    daily_pnl = threshold + 1.0  # still within acceptable range

    session = _FakeSession(daily_pnl=daily_pnl)
    redis = _make_redis()
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_daily_loss()

    redis.set.assert_not_called()
    bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Max scores flow through to ExecutionEngine gate
# ---------------------------------------------------------------------------


async def test_auto_close_decision_clears_execution_gate():
    """Auto-close decisions must carry scores that guarantee the execution gate passes."""
    avg_cost = 50_000.0
    current_price = avg_cost * (1 - STOP_LOSS_PCT - 0.01)

    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=current_price)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with patch(
        "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
    ):
        await guardian._check_positions()

    decision = next(c.args[1] for c in bus.publish.call_args_list if c.args[0] == STREAM_DECISIONS)
    sc = decision["signal_confidence"]
    rs = decision["reasoning_score"]
    # Weighted score: sc*0.5 + rs*0.3 + 0.5*0.2 = 0.9 >= EXECUTION_DECISION_THRESHOLD (0.55)
    from api.constants import EXECUTION_DECISION_THRESHOLD

    final_score = sc * 0.50 + rs * 0.30 + 0.5 * 0.20
    assert final_score >= EXECUTION_DECISION_THRESHOLD, (
        f"Auto-close score {final_score} must clear gate {EXECUTION_DECISION_THRESHOLD}"
    )
