"""Tests for RiskGuardian — position-level and portfolio-level risk enforcement."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.constants import (
    DAILY_LOSS_LIMIT_PCT,
    DEFAULT_PAPER_CASH,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_PAPER_POSITION,
    REDIS_KEY_PRICES,
    REDIS_KEY_RISK_PEAK_PNL,
    STALE_POSITION_MAX_AGE_SECONDS,
    STOP_LOSS_PCT,
    STREAM_DECISIONS,
    STREAM_RISK_ALERTS,
    TAKE_PROFIT_PCT,
    TRAILING_STOP_ARM_PCT,
    TRAILING_STOP_GIVEBACK_FRAC,
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


async def _seed_price(redis, symbol: str, price: float) -> None:
    await redis.set(REDIS_KEY_PRICES.format(symbol=symbol), json.dumps({"price": price}))


async def _seed_paper_position(
    redis,
    symbol: str,
    side: str = "long",
    qty: float = 1.0,
    entry_price: float = 50_000.0,
    opened_at: str | None = None,
) -> None:
    await redis.set(
        REDIS_KEY_PAPER_POSITION.format(symbol=symbol),
        json.dumps(
            {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "current_price": entry_price,
                "opened_at": opened_at,
            }
        ),
    )


def _decisions(bus) -> list[dict]:
    return [c.args[1] for c in bus.publish.call_args_list if c.args[0] == STREAM_DECISIONS]


async def test_circuit_breaker_trips_on_severe_drawdown():
    """A drawdown past the breaker threshold flips the kill switch (fail-closed)."""
    from api.services.strategy_registry import StrategyRegistry, set_strategy_registry

    set_strategy_registry(StrategyRegistry())
    redis = _make_redis()
    guardian = RiskGuardian(_make_bus(), redis)

    async def _severe() -> float:
        return 0.99

    guardian._portfolio_drawdown_pct = _severe
    await guardian._check_circuit_breaker()
    redis.set.assert_any_call(REDIS_KEY_KILL_SWITCH, "1")


async def test_circuit_breaker_quiet_when_healthy():
    """No kill-switch write when drawdown is within limits."""
    from api.services.strategy_registry import StrategyRegistry, set_strategy_registry

    set_strategy_registry(StrategyRegistry())
    redis = _make_redis()
    guardian = RiskGuardian(_make_bus(), redis)

    async def _flat() -> float:
        return 0.0

    guardian._portfolio_drawdown_pct = _flat
    await guardian._check_circuit_breaker()
    assert all(c.args[0] != REDIS_KEY_KILL_SWITCH for c in redis.set.call_args_list)


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


@contextmanager
def _db_path(session):
    """Pin the guardian to the Postgres path.

    The conftest autouse fixture defaults db_available to False, which would
    route _check_positions / _check_daily_loss to the PaperBroker Redis scan —
    these tests exercise the DB source explicitly.
    """
    with (
        patch("api.services.agents.risk_guardian.is_db_available", return_value=True),
        patch(
            "api.services.agents.risk_guardian.AsyncSessionFactory", _FakeSessionFactory(session)
        ),
    ):
        yield


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

    with _db_path(session):
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

    with _db_path(session):
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

    with _db_path(session):
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

    with _db_path(session):
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
    current_price = avg_cost * 1.02  # +2% — within bounds, below the trailing arm

    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=current_price)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with _db_path(session):
        await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_no_positions_no_action():
    """Empty positions table must result in zero publishes."""
    session = _FakeSession(positions=[])
    redis = _make_redis()
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with _db_path(session):
        await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_no_price_in_redis_skips_position():
    """If current price is not in Redis, the position is skipped (no action taken)."""
    positions = [_make_position()]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=None)  # no price available
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with _db_path(session):
        await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_zero_avg_cost_skips_position():
    """Position with avg_cost=0 must be skipped (prevents division-by-zero)."""
    positions = [_make_position(avg_cost=0.0)]
    session = _FakeSession(positions=positions)
    redis = _make_redis(price=50_000.0)
    bus = _make_bus()
    guardian = RiskGuardian(bus, redis)

    with _db_path(session):
        await guardian._check_positions()

    bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Trailing-stop ratchet
# ---------------------------------------------------------------------------


async def test_trailing_stop_closes_after_giveback(fake_redis):
    """A winner that arms the ratchet then retraces past the giveback floor is
    closed at a profit instead of riding back down to the -5% hard stop."""
    avg_cost = 50_000.0
    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    with _db_path(session):
        # Cycle 1: +5% — peak recorded, armed, but above the floor → no close.
        await _seed_price(fake_redis, "BTC/USD", avg_cost * 1.05)
        await guardian._check_positions()
        bus.publish.assert_not_called()

        # Cycle 2: +2% — below floor 5% * (1 - giveback 0.4) = 3% → close.
        await _seed_price(fake_redis, "BTC/USD", avg_cost * 1.02)
        await guardian._check_positions()

    decisions = _decisions(bus)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "sell"
    assert "trailing_stop" in decisions[0]["primary_edge"]
    # Peak state cleared after the close so a re-entry starts fresh.
    assert await fake_redis.get(REDIS_KEY_RISK_PEAK_PNL.format(symbol="BTC/USD")) is None


async def test_trailing_stop_not_armed_below_threshold(fake_redis):
    """Peak below TRAILING_STOP_ARM_PCT must never trigger a trailing close,
    even on a full retrace — the hard stop-loss owns that region."""
    avg_cost = 50_000.0
    peak_pct = TRAILING_STOP_ARM_PCT - 0.005  # never arms
    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    with _db_path(session):
        await _seed_price(fake_redis, "BTC/USD", avg_cost * (1 + peak_pct))
        await guardian._check_positions()
        await _seed_price(fake_redis, "BTC/USD", avg_cost * 1.001)
        await guardian._check_positions()

    bus.publish.assert_not_called()
    # Peak survives for future cycles.
    state = json.loads(await fake_redis.get(REDIS_KEY_RISK_PEAK_PNL.format(symbol="BTC/USD")))
    assert state["peak_pnl_pct"] == pytest.approx(peak_pct)


async def test_trailing_stop_holds_above_floor(fake_redis):
    """Armed ratchet with PnL still above the giveback floor must hold the position."""
    avg_cost = 50_000.0
    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    peak = 0.05
    floor = peak * (1 - TRAILING_STOP_GIVEBACK_FRAC)
    with _db_path(session):
        await _seed_price(fake_redis, "BTC/USD", avg_cost * (1 + peak))
        await guardian._check_positions()
        await _seed_price(fake_redis, "BTC/USD", avg_cost * (1 + floor + 0.005))
        await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_trailing_stop_resets_on_basis_change(fake_redis):
    """A stale peak recorded against a different avg_cost (prior position or an
    add) must NOT trail the new position — the ratchet resets to the new basis."""
    avg_cost = 50_000.0
    await fake_redis.set(
        REDIS_KEY_RISK_PEAK_PNL.format(symbol="BTC/USD"),
        json.dumps({"peak_pnl_pct": 0.08, "avg_cost": 40_000.0}),
    )
    positions = [_make_position(avg_cost=avg_cost)]
    session = _FakeSession(positions=positions)
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    with _db_path(session):
        await _seed_price(fake_redis, "BTC/USD", avg_cost * 1.02)
        await guardian._check_positions()

    bus.publish.assert_not_called()  # stale 8% peak would have fired at +2%
    state = json.loads(await fake_redis.get(REDIS_KEY_RISK_PEAK_PNL.format(symbol="BTC/USD")))
    assert state["avg_cost"] == pytest.approx(avg_cost)
    assert state["peak_pnl_pct"] == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# Memory mode — PaperBroker Redis positions (no Postgres)
# ---------------------------------------------------------------------------


async def test_memory_mode_stop_loss_closes_paper_position(fake_redis):
    """Regression: in memory mode positions exist ONLY in the PaperBroker's
    paper:positions:{symbol} Redis keys. The guardian used to scan only
    Postgres and silently skip — no stop-loss or take-profit EVER fired in a
    no-DB deployment. The scan must find the Redis position and close it."""
    avg_cost = 50_000.0
    await _seed_paper_position(fake_redis, "BTC/USD", side="long", qty=0.5, entry_price=avg_cost)
    await _seed_price(fake_redis, "BTC/USD", avg_cost * (1 - STOP_LOSS_PCT - 0.01))
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    await guardian._check_positions()  # db_available is False via conftest

    decisions = _decisions(bus)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "sell"
    assert decisions[0]["symbol"] == "BTC/USD"
    assert decisions[0]["qty"] == pytest.approx(0.5)
    assert "stop_loss" in decisions[0]["primary_edge"]


async def test_memory_mode_short_position_normalized(fake_redis):
    """Paper shorts store signed (negative) qty — the scan must normalize to
    unsigned qty + side so the close decision buys back the right amount."""
    avg_cost = 3_000.0
    await _seed_paper_position(fake_redis, "ETH/USD", side="short", qty=-2.0, entry_price=avg_cost)
    await _seed_price(fake_redis, "ETH/USD", avg_cost * (1 + STOP_LOSS_PCT + 0.01))
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    await guardian._check_positions()

    decisions = _decisions(bus)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "buy"
    assert decisions[0]["qty"] == pytest.approx(2.0)


async def test_memory_mode_skips_flat_and_garbage_keys(fake_redis):
    """Flat positions and unparseable payloads must be skipped silently."""
    await _seed_paper_position(fake_redis, "SOL/USD", side="flat", qty=0.0, entry_price=0.0)
    await fake_redis.set(REDIS_KEY_PAPER_POSITION.format(symbol="AAPL"), "{not json")
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    await guardian._check_positions()

    bus.publish.assert_not_called()


async def test_memory_mode_stale_position_reaped(fake_redis):
    """A position older than STALE_POSITION_MAX_AGE_SECONDS with PnL inside the
    dead band is going nowhere — it must be closed to free the capital."""
    avg_cost = 50_000.0
    opened = datetime.now(timezone.utc) - timedelta(seconds=STALE_POSITION_MAX_AGE_SECONDS + 600)
    await _seed_paper_position(
        fake_redis,
        "BTC/USD",
        side="long",
        qty=0.5,
        entry_price=avg_cost,
        opened_at=opened.isoformat(),
    )
    await _seed_price(fake_redis, "BTC/USD", avg_cost * 1.002)  # +0.2% — dead band
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    await guardian._check_positions()

    decisions = _decisions(bus)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "sell"
    assert "stale_position" in decisions[0]["primary_edge"]


async def test_memory_mode_stale_reaper_spares_young_and_working_positions(fake_redis):
    """The reaper must NOT close (a) a young position inside the dead band, or
    (b) an old position whose PnL is outside the band (it is doing something —
    the trailing stop / hard bounds own it)."""
    avg_cost = 50_000.0
    young = datetime.now(timezone.utc) - timedelta(seconds=600)
    old = datetime.now(timezone.utc) - timedelta(seconds=STALE_POSITION_MAX_AGE_SECONDS + 600)
    await _seed_paper_position(
        fake_redis, "BTC/USD", qty=0.5, entry_price=avg_cost, opened_at=young.isoformat()
    )
    await _seed_price(fake_redis, "BTC/USD", avg_cost * 1.002)  # in band but young
    await _seed_paper_position(
        fake_redis, "ETH/USD", qty=1.0, entry_price=3_000.0, opened_at=old.isoformat()
    )
    await _seed_price(fake_redis, "ETH/USD", 3_000.0 * 1.02)  # old but +2% — working
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

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

    with _db_path(session):
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

    with _db_path(session):
        await guardian._check_daily_loss()

    redis.set.assert_not_called()
    bus.publish.assert_not_called()


class _StubRedisStore:
    def __init__(self, trades: list[dict]):
        self._trades = trades

    async def list_closed_trades(self, limit: int = 100) -> list[dict]:
        return self._trades


async def test_memory_mode_daily_loss_uses_closed_trades_mirror(fake_redis):
    """Regression: the daily-loss limit read only Postgres trade_performance,
    so it never enforced in memory mode. It must sum TODAY's closes from the
    Redis closed-trades mirror and trip the kill switch on breach."""
    threshold = -(DEFAULT_PAPER_CASH * DAILY_LOSS_LIMIT_PCT)
    today = datetime.now(timezone.utc).isoformat()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    trades = [
        {"pnl": threshold - 1.0, "filled_at": today},
        {"pnl": -9_999.0, "filled_at": yesterday},  # not today — must be excluded
    ]
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    with patch(
        "api.services.agents.risk_guardian.get_redis_store",
        return_value=_StubRedisStore(trades),
    ):
        await guardian._check_daily_loss()

    assert await fake_redis.get(REDIS_KEY_KILL_SWITCH) == "1"
    published_streams = [call.args[0] for call in bus.publish.call_args_list]
    assert STREAM_RISK_ALERTS in published_streams


async def test_memory_mode_daily_loss_ignores_prior_days(fake_redis):
    """Big losses on PRIOR days must not trip today's limit."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    trades = [{"pnl": -50_000.0, "filled_at": yesterday}]
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    with patch(
        "api.services.agents.risk_guardian.get_redis_store",
        return_value=_StubRedisStore(trades),
    ):
        await guardian._check_daily_loss()

    assert await fake_redis.get(REDIS_KEY_KILL_SWITCH) is None
    bus.publish.assert_not_called()


async def test_memory_mode_daily_loss_no_store_no_action(fake_redis):
    """No RedisStore singleton installed → no readable PnL source → no action."""
    bus = _make_bus()
    guardian = RiskGuardian(bus, fake_redis)

    with patch("api.services.agents.risk_guardian.get_redis_store", return_value=None):
        await guardian._check_daily_loss()

    assert await fake_redis.get(REDIS_KEY_KILL_SWITCH) is None
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

    with _db_path(session):
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
