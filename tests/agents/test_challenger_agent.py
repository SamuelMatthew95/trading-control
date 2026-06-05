"""Regression tests for ChallengerAgent.

These cover the AttributeError that previously surfaced when a challenger ran
its first ``_grade()`` cycle: ``self._instance_id`` was referenced in the grade
and retirement payloads but never assigned in ``__init__``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import (
    STREAM_AGENT_GRADES,
    STREAM_EXECUTIONS,
    STREAM_MARKET_EVENTS,
    STREAM_PROPOSALS,
    STREAM_TRADE_PERFORMANCE,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.pipeline_agents import ChallengerAgent


def _tick(price: float, symbol: str = "BTC/USD") -> dict:
    """A market_events message: the tick is wrapped in a JSON ``payload`` string,
    exactly as PricePoller publishes it (and SignalGenerator parses it)."""
    import json

    return {"payload": json.dumps({"symbol": symbol, "price": price})}


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_dlq():
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


@pytest.mark.asyncio
async def test_challenger_registers_in_lifecycle(mock_bus, mock_dlq):
    """A running challenger with a strategy config appears in the registry at SHADOW."""
    from api.constants import StrategyStatus
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    agent = ChallengerAgent(
        mock_bus,
        mock_dlq,
        challenger_config={"strategy": "strong_only", "grade_every": 100},
        max_fills=100,
    )
    await agent.process(STREAM_EXECUTIONS, "1-0", {})

    registry = get_strategy_registry()
    match = [v for v in registry.versions() if v.config.get("strategy") == "strong_only"]
    assert len(match) == 1
    assert registry.status(match[0].version_id) == StrategyStatus.SHADOW


@pytest.mark.asyncio
async def test_challenger_without_strategy_does_not_register(mock_bus, mock_dlq):
    """A challenger with no strategy in its config registers nothing."""
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    agent = ChallengerAgent(mock_bus, mock_dlq, max_fills=100)
    await agent.process(STREAM_EXECUTIONS, "1-0", {})
    assert get_strategy_registry().versions() == []


def test_challenger_assigns_instance_id_in_init(mock_bus, mock_dlq):
    """instance_id must be set so grade/retire payloads can reference it."""
    agent = ChallengerAgent(mock_bus, mock_dlq, max_fills=5)
    assert agent._instance_id is not None
    assert agent._instance_id == agent._challenger_id


@pytest.mark.asyncio
async def test_grade_publishes_payload_with_instance_id(mock_bus, mock_dlq):
    """_grade() previously raised AttributeError on self._instance_id."""
    agent = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"grade_every": 1}, max_fills=100)
    # Seed enough fills to trigger _grade() exactly once.
    await agent.process("trade_performance", "1-0", {"pnl": 1.5})

    # _grade() runs because fills=1 % grade_every=1 == 0
    publish_calls = mock_bus.publish.await_args_list
    assert publish_calls, "expected at least one publish from _grade()"
    stream, payload = publish_calls[0].args
    assert stream == STREAM_AGENT_GRADES
    # instance_id is nested in the metrics block alongside challenger_id.
    assert payload["metrics"]["instance_id"] == agent._challenger_id


@pytest.mark.asyncio
async def test_retire_summary_includes_instance_id(mock_bus, mock_dlq):
    """_retire_with_summary() also references self._instance_id."""
    agent = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"grade_every": 100}, max_fills=1)
    # Force stop() to be a no-op so we can inspect publish calls.
    agent.stop = AsyncMock()  # type: ignore[method-assign]

    await agent.process("trade_performance", "1-0", {"pnl": 0.5})

    proposal_calls = [
        call for call in mock_bus.publish.await_args_list if call.args[0] == STREAM_PROPOSALS
    ]
    assert proposal_calls, "expected challenger to publish a retirement proposal"
    payload = proposal_calls[0].args[1]
    assert payload["instance_id"] == agent._challenger_id


def test_eager_shadow_registration_is_idempotent(mock_bus, mock_dlq):
    """Two challengers for the same strategy register exactly one SHADOW entry."""
    from api.constants import StrategyStatus
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    a = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"strategy": "strong_only"})
    b = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"strategy": "strong_only"})
    a._ensure_lifecycle_registered()
    b._ensure_lifecycle_registered()  # must not double-register

    reg = get_strategy_registry()
    matches = [v for v in reg.versions() if v.config.get("strategy") == "strong_only"]
    assert len(matches) == 1
    assert reg.status(matches[0].version_id) == StrategyStatus.SHADOW


@pytest.mark.asyncio
async def test_start_registers_shadow_eagerly(mock_bus, mock_dlq, monkeypatch):
    """start() registers the strategy at SHADOW before any fill arrives, so an
    auto-spawned shadow challenger shows on the lifecycle panel immediately."""
    from api.constants import StrategyStatus
    from api.services.strategy_registry import (
        StrategyRegistry,
        get_strategy_registry,
        set_strategy_registry,
    )

    set_strategy_registry(StrategyRegistry())
    agent = ChallengerAgent(mock_bus, mock_dlq, challenger_config={"strategy": "confirmed_trend"})
    # Neutralize the base-class stream/consumer setup — assert only eager registration.
    monkeypatch.setattr(type(agent).__bases__[0], "start", AsyncMock())
    await agent.start()

    reg = get_strategy_registry()
    match = [v for v in reg.versions() if v.config.get("strategy") == "confirmed_trend"]
    assert len(match) == 1
    assert reg.status(match[0].version_id) == StrategyStatus.SHADOW


# ---------------------------------------------------------------------------
# Shadow trading — the challenger actually RUNS its strategy on live signals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_challenger_runs_its_strategy_as_shadow_trades(mock_bus, mock_dlq):
    """A challenger with a strategy config actually executes it on live signals —
    the config is no longer decorative."""
    agent = ChallengerAgent(
        mock_bus, mock_dlq, challenger_config={"strategy": "baseline_momentum"}, max_fills=10_000
    )
    assert agent._shadow is not None and agent._baseline_shadow is not None
    price = 100.0
    for _ in range(40):
        price *= 1.001
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))
    for _ in range(12):
        price *= 1.03
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))
    for _ in range(12):
        price *= 0.97
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))
    assert agent._shadow.metrics.trades >= 1  # the strategy genuinely traded


@pytest.mark.asyncio
async def test_no_strategy_challenger_ignores_signals(mock_bus, mock_dlq):
    """No strategy configured → no shadow engine; signals are a safe no-op."""
    agent = ChallengerAgent(mock_bus, mock_dlq, max_fills=100)
    assert agent._shadow is None
    await agent.process(STREAM_MARKET_EVENTS, "s", _tick(100.0))  # no crash
    assert agent._shadow is None


@pytest.mark.asyncio
async def test_shadow_observes_unfiltered_market_events_payload(mock_bus, mock_dlq):
    """REGRESSION (PR #275 review P2): the challenger feeds off the UNFILTERED
    market_events stream (every tick), parsing the wrapped JSON ``payload`` — not the
    throttled signals stream. A malformed/empty payload is a safe no-op."""
    agent = ChallengerAgent(
        mock_bus, mock_dlq, challenger_config={"strategy": "baseline_momentum"}, max_fills=10_000
    )
    # Two distinct prices via the wrapped payload → the engine records history for the
    # symbol (proving the JSON envelope is parsed like SignalGenerator does).
    await agent.process(STREAM_MARKET_EVENTS, "s", _tick(100.0))
    await agent.process(STREAM_MARKET_EVENTS, "s", _tick(101.0))
    assert "BTC/USD" in agent._shadow._history
    assert list(agent._shadow._history["BTC/USD"])[-1] == 101.0
    # Malformed payloads must not crash.
    await agent.process(STREAM_MARKET_EVENTS, "s", {"payload": "not json"})
    await agent.process(STREAM_MARKET_EVENTS, "s", {})


@pytest.mark.asyncio
async def test_grade_carries_shadow_evidence(mock_bus, mock_dlq):
    """The grade payload carries the real own-vs-baseline shadow comparison so the
    dashboard can show what the challenger's strategy actually did on live data."""
    agent = ChallengerAgent(
        mock_bus,
        mock_dlq,
        challenger_config={"strategy": "mean_reversion", "grade_every": 1},
        max_fills=10_000,
    )
    price = 100.0
    for _ in range(40):
        price *= 1.001
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))
    for _ in range(12):
        price *= 1.03
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))
    # trade_performance is the grade-cadence clock; one event triggers _grade().
    await agent.process(STREAM_TRADE_PERFORMANCE, "1", {"pnl": 1.0})

    grade_calls = [c for c in mock_bus.publish.await_args_list if c.args[0] == STREAM_AGENT_GRADES]
    assert grade_calls, "expected a challenger grade to be published"
    metrics = grade_calls[-1].args[1]["metrics"]
    assert "shadow_trades" in metrics
    assert "shadow_win_rate" in metrics
    assert "shadow_pnl" in metrics
    assert "beats_baseline_shadow" in metrics  # baseline engine present for A/B


@pytest.mark.asyncio
async def test_shadow_winner_emits_promotion_proposal_once(mock_bus, mock_dlq):
    """A challenger beating baseline on enough SHADOW trades emits a single
    human-approvable promotion proposal — no live fills required — and latches."""
    from api.constants import CHALLENGER_MIN_SHADOW_TRADES

    agent = ChallengerAgent(
        mock_bus, mock_dlq, challenger_config={"strategy": "mean_reversion"}, max_fills=10_000
    )
    # Force a winning shadow verdict deterministically (independent of price path).
    agent._shadow = MagicMock()
    agent._shadow.metrics.trades = CHALLENGER_MIN_SHADOW_TRADES + 5
    agent._baseline_shadow = MagicMock()
    agent._shadow_summary = lambda: {
        "shadow_trades": CHALLENGER_MIN_SHADOW_TRADES + 5,
        "shadow_win_rate": 0.66,
        "shadow_pnl": 120.0,
        "baseline_shadow_pnl": 20.0,
        "beats_baseline_shadow": True,
    }
    agent._backtest_verdict = lambda: ""

    await agent._maybe_propose_shadow_promotion()
    props = [c for c in mock_bus.publish.await_args_list if c.args[0] == STREAM_PROPOSALS]
    assert len(props) == 1
    payload = props[0].args[1]
    assert payload["proposal_type"] == "challenger_promotion"
    assert payload["requires_approval"] is True
    assert payload["content"]["shadow_edge"] == pytest.approx(100.0)
    assert payload["beats_baseline_shadow"] is True  # shadow report fields carried through

    # Latched — a second pass must not publish again.
    await agent._maybe_propose_shadow_promotion()
    props = [c for c in mock_bus.publish.await_args_list if c.args[0] == STREAM_PROPOSALS]
    assert len(props) == 1


@pytest.mark.asyncio
async def test_no_promotion_proposal_below_trade_threshold(mock_bus, mock_dlq):
    """Below CHALLENGER_MIN_SHADOW_TRADES no proposal fires, even if winning."""
    from api.constants import CHALLENGER_MIN_SHADOW_TRADES

    agent = ChallengerAgent(
        mock_bus, mock_dlq, challenger_config={"strategy": "mean_reversion"}, max_fills=10_000
    )
    agent._shadow = MagicMock()
    agent._shadow.metrics.trades = CHALLENGER_MIN_SHADOW_TRADES - 1
    agent._baseline_shadow = MagicMock()
    agent._shadow_summary = lambda: {"beats_baseline_shadow": True}

    await agent._maybe_propose_shadow_promotion()
    assert not [c for c in mock_bus.publish.await_args_list if c.args[0] == STREAM_PROPOSALS]


@pytest.mark.asyncio
async def test_no_promotion_proposal_when_not_beating_baseline(mock_bus, mock_dlq):
    """A challenger that does NOT beat baseline emits no promotion proposal."""
    from api.constants import CHALLENGER_MIN_SHADOW_TRADES

    agent = ChallengerAgent(
        mock_bus, mock_dlq, challenger_config={"strategy": "mean_reversion"}, max_fills=10_000
    )
    agent._shadow = MagicMock()
    agent._shadow.metrics.trades = CHALLENGER_MIN_SHADOW_TRADES + 5
    agent._baseline_shadow = MagicMock()
    agent._shadow_summary = lambda: {
        "shadow_trades": CHALLENGER_MIN_SHADOW_TRADES + 5,
        "beats_baseline_shadow": False,
    }

    await agent._maybe_propose_shadow_promotion()
    assert not [c for c in mock_bus.publish.await_args_list if c.args[0] == STREAM_PROPOSALS]


# ---------------------------------------------------------------------------
# activity_snapshot — full, connected visibility for the dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_snapshot_reports_liveness_threshold_and_flow(mock_bus, mock_dlq):
    """The dashboard snapshot proves the challenger is ALIVE and shows the
    promotion threshold + the live trade FLOW — not three frozen numbers."""
    from api.constants import CHALLENGER_MIN_SHADOW_TRADES, FieldName

    agent = ChallengerAgent(
        mock_bus, mock_dlq, challenger_config={"strategy": "baseline_momentum"}, max_fills=10_000
    )
    price = 100.0
    for _ in range(40):
        price *= 1.001
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))
    for _ in range(12):
        price *= 1.03
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))
    for _ in range(12):
        price *= 0.97
        await agent.process(STREAM_MARKET_EVENTS, "s", _tick(price))

    snap = agent.activity_snapshot()
    # Promotion threshold is exposed so the UI can show "N/25 to eligibility".
    assert snap["min_shadow_trades"] == CHALLENGER_MIN_SHADOW_TRADES
    # Liveness: it observed every tick we fed it.
    assert snap["ticks_observed"] == 64
    assert snap["last_tick_at"] is not None
    assert "open_shadow_positions" in snap
    # The strategy genuinely traded → flow + last-trade timestamp are populated.
    assert agent._shadow.metrics.trades >= 1
    assert snap["last_shadow_trade_at"] is not None
    assert len(snap["recent_shadow_trades"]) >= 1
    trade = snap["recent_shadow_trades"][0]
    assert FieldName.SYMBOL in trade
    assert FieldName.DIRECTION in trade
    assert FieldName.PNL in trade


@pytest.mark.asyncio
async def test_activity_snapshot_threshold_present_before_any_trade(mock_bus, mock_dlq):
    """Even before a single shadow trade closes, the snapshot carries the
    threshold and a tick count, so a warming-up challenger reads as alive."""
    from api.constants import CHALLENGER_MIN_SHADOW_TRADES

    agent = ChallengerAgent(
        mock_bus, mock_dlq, challenger_config={"strategy": "baseline_momentum"}, max_fills=10_000
    )
    await agent.process(STREAM_MARKET_EVENTS, "s", _tick(100.0))
    snap = agent.activity_snapshot()
    assert snap["min_shadow_trades"] == CHALLENGER_MIN_SHADOW_TRADES
    assert snap["ticks_observed"] == 1
    assert snap["last_tick_at"] is not None
    assert snap["recent_shadow_trades"] == []
