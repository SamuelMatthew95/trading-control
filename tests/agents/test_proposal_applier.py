"""Tests for ProposalApplier — closes the learning loop.

Each proposal type maps to a specific Redis control-plane key. These tests
verify the mapping is correct and that ExecutionEngine + ReasoningAgent
will see the values that ProposalApplier writes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import (
    AGENT_REASONING,
    LEARNING_CONTROL_TTL_SECONDS,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    SIGNAL_WEIGHT_REDUCTION_FACTOR,
    SIGNAL_WEIGHT_SCALE_MIN,
    TRADING_PAUSE_PROBATION_SECONDS,
    FieldName,
    ProposalType,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agents.proposal_applier import ProposalApplier

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal in-memory Redis substitute that captures set() calls."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = dict(initial or {})
        self._ttl: dict[str, int] = {}
        self._lists: dict[str, list[str]] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = str(value)
        if ex is not None:
            self._ttl[key] = ex
        self.set_calls.append((key, str(value), ex))
        return True

    # Minimal list ops so PromptStore (directive history) works in these tests.
    async def lpush(self, key: str, value: str) -> int:
        self._lists.setdefault(key, []).insert(0, str(value))
        return len(self._lists[key])

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        if key in self._lists:
            self._lists[key] = self._lists[key][start : end + 1]
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self._lists.get(key, [])
        return items[start : (end + 1) if end != -1 else None]


def _make_applier(redis: _FakeRedis) -> ProposalApplier:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return ProposalApplier(bus=bus, dlq=dlq, redis_client=redis)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_signal_weight_reduction_multiplies_scale(monkeypatch):
    """Grade C proposal multiplies the scale by SIGNAL_WEIGHT_REDUCTION_FACTOR."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis({REDIS_KEY_SIGNAL_WEIGHT_SCALE: "1.0"})
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.SIGNAL_WEIGHT_REDUCTION,
        FieldName.CONTENT: {FieldName.ACTION: "reduce_signal_weight"},
    }
    await applier.process("proposals", "1-0", proposal)

    new_scale = float(await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE))
    assert new_scale == pytest.approx(SIGNAL_WEIGHT_REDUCTION_FACTOR, rel=1e-6)


async def test_signal_weight_reduction_floors_at_minimum(monkeypatch):
    """Repeated reductions never drop below SIGNAL_WEIGHT_SCALE_MIN."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis({REDIS_KEY_SIGNAL_WEIGHT_SCALE: "0.06"})
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.SIGNAL_WEIGHT_REDUCTION,
        FieldName.CONTENT: {FieldName.ACTION: "reduce_signal_weight"},
    }
    await applier.process("proposals", "1-0", proposal)
    new_scale = float(await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE))
    assert new_scale == pytest.approx(SIGNAL_WEIGHT_SCALE_MIN, abs=1e-6)


async def test_agent_suspension_sets_redis_key(monkeypatch):
    """Grade D suspension writes learning:agent_suspended:{name} with TTL."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.AGENT_SUSPENSION,
        FieldName.CONTENT: {
            FieldName.ACTION: "suspend_from_live_stream",
            FieldName.AGENT_NAME: AGENT_REASONING,
        },
    }
    await applier.process("proposals", "1-0", proposal)

    key = REDIS_KEY_AGENT_SUSPENDED.format(name=AGENT_REASONING)
    # Mirrors the kill-switch contract — value is "1" while suspended.
    assert await redis.get(key) == "1"
    # Verify a TTL was supplied so the suspension auto-expires
    assert any(call[0] == key and call[2] is not None for call in redis.set_calls)


async def test_agent_retirement_pauses_trading(monkeypatch):
    """Grade F retirement sets learning:trading_paused = '1' with reason."""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.AGENT_RETIREMENT,
        FieldName.CONTENT: {
            FieldName.ACTION: "retire_immediately",
            FieldName.REASON: "Grade F: 12% score",
        },
    }
    await applier.process("proposals", "1-0", proposal)

    assert await redis.get(REDIS_KEY_TRADING_PAUSED) == "1"
    assert (await redis.get(REDIS_KEY_TRADING_PAUSED_REASON)) == "Grade F: 12% score"


async def test_retirement_is_bounded_probation_with_cautious_resume(monkeypatch):
    """In PAPER mode a Grade-F retirement pauses for a bounded probation window
    (auto-resume) and reduces the signal-weight scale so trading resumes
    cautiously — instead of a 25h hard stop that deadlocks the learning loop."""
    from api.config import settings

    monkeypatch.setattr(settings, "ALPACA_PAPER", True)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis({REDIS_KEY_SIGNAL_WEIGHT_SCALE: "1.0"})
    applier = _make_applier(redis)

    await applier.process(
        "proposals",
        "1-0",
        {
            FieldName.PROPOSAL_TYPE: ProposalType.AGENT_RETIREMENT,
            FieldName.CONTENT: {FieldName.ACTION: "retire_immediately", FieldName.REASON: "F"},
        },
    )

    # Pause TTL is the bounded probation window, not the ~25h control TTL.
    pause_set = next(c for c in redis.set_calls if c[0] == REDIS_KEY_TRADING_PAUSED)
    assert pause_set[2] == TRADING_PAUSE_PROBATION_SECONDS
    # Signal weight shrunk so post-probation trading is smaller.
    new_scale = float(await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE))
    assert new_scale == max(1.0 * SIGNAL_WEIGHT_REDUCTION_FACTOR, SIGNAL_WEIGHT_SCALE_MIN)


async def test_retirement_in_live_mode_is_full_halt_no_auto_resume(monkeypatch):
    """SAFETY: with real money (ALPACA_PAPER=False) a Grade-F retirement is a
    full long halt pending human review — never an auto-resume, never a quiet
    size reduction that masks the stop."""
    from api.config import settings

    monkeypatch.setattr(settings, "ALPACA_PAPER", False)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis({REDIS_KEY_SIGNAL_WEIGHT_SCALE: "1.0"})
    applier = _make_applier(redis)

    await applier.process(
        "proposals",
        "1-0",
        {
            FieldName.PROPOSAL_TYPE: ProposalType.AGENT_RETIREMENT,
            FieldName.CONTENT: {FieldName.ACTION: "retire_immediately", FieldName.REASON: "F"},
        },
    )

    pause_set = next(c for c in redis.set_calls if c[0] == REDIS_KEY_TRADING_PAUSED)
    assert pause_set[2] == LEARNING_CONTROL_TTL_SECONDS  # long halt, not probation
    # Weight is untouched — no cautious-resume path in live mode.
    assert await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE) == "1.0"


async def test_unknown_proposal_type_is_logged_not_applied(monkeypatch):
    """code_change / regime_adjustment need human DESIGN — no Redis writes, no PR.

    (PARAMETER_CHANGE is handled separately now: it emits a GitOps PR artifact —
    see test_parameter_change_emits_github_pr_artifact.)"""
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.CODE_CHANGE,
        FieldName.CONTENT: {FieldName.ACTION: "rewrite_signal_logic"},
    }
    await applier.process("proposals", "1-0", proposal)

    # No control-plane key should have been written
    assert await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE) is None
    assert await redis.get(REDIS_KEY_TRADING_PAUSED) is None


async def test_tool_governance_disables_flagged_tools(monkeypatch):
    """An approved TOOL_GOVERNANCE proposal disables the flagged tools in the
    registry, closing the dead-tool loop (previously dropped as unknown type)."""
    from api.services.tool_registry import (  # noqa: PLC0415
        ToolMetadata,
        ToolPhase,
        ToolRegistry,
        set_tool_registry,
    )

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())

    registry = ToolRegistry()
    registry.register(ToolMetadata(name="dead_tool", phase=ToolPhase.PERCEPTION, alpha_score=-0.3))
    registry.register(ToolMetadata(name="good_tool", phase=ToolPhase.PERCEPTION, alpha_score=0.5))
    set_tool_registry(registry)

    applier = _make_applier(_FakeRedis())
    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.TOOL_GOVERNANCE,
        FieldName.CONTENT: {
            FieldName.SUGGESTIONS: [
                {FieldName.TOOL: "dead_tool", FieldName.ACTION: "disable"},
                {FieldName.TOOL: "good_tool", FieldName.ACTION: "review"},  # advisory only
            ],
        },
    }
    await applier.process("proposals", "1-0", proposal)

    assert registry.get("dead_tool").enabled is False  # disabled
    assert registry.get("good_tool").enabled is True  # review is advisory, untouched


async def test_apply_writes_agent_log_with_applied_at(monkeypatch):
    """Each applied proposal generates an agent_logs row with applied_at."""
    write_log_mock = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log_mock)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.AGENT_RETIREMENT,
        FieldName.CONTENT: {
            FieldName.ACTION: "retire_immediately",
            FieldName.REASON: "test",
        },
        FieldName.TRACE_ID: "trace-xyz",
    }
    await applier.process("proposals", "1-0", proposal)

    assert write_log_mock.await_count == 1
    args, _ = write_log_mock.call_args
    trace_id, log_type, payload = args
    assert trace_id == "trace-xyz"
    assert payload[FieldName.APPLIED] is True
    assert FieldName.APPLIED_AT in payload


async def test_parameter_change_emits_github_pr_artifact(monkeypatch):
    """A PARAMETER_CHANGE proposal becomes a durable github_prs artifact instead of
    being dropped — the GitOps 'create artifact -> PR' path."""
    from api.constants import STREAM_GITHUB_PRS

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
        FieldName.CONTENT: {
            FieldName.PARAMETER: "SIGNAL_CONFIDENCE_MIN_GATE",
            FieldName.PREVIOUS_VALUE: 0.65,
            FieldName.NEW_VALUE: 0.50,
            FieldName.REASON: "too many momentum signals gated",
        },
    }
    await applier.process("proposals", "1-0", proposal)

    pr_calls = [c for c in applier.bus.publish.await_args_list if c.args[0] == STREAM_GITHUB_PRS]
    assert pr_calls, "expected a github_prs pr_request artifact"
    artifact = pr_calls[0].args[1]
    assert artifact[FieldName.TYPE] == "pr_request"
    assert artifact[FieldName.PARAMETER] == "SIGNAL_CONFIDENCE_MIN_GATE"
    assert artifact[FieldName.PREVIOUS_VALUE] == 0.65
    assert artifact[FieldName.PROPOSED_VALUE] == 0.50
    assert artifact[FieldName.PROPOSAL_TYPE] == ProposalType.PARAMETER_CHANGE
    # No live control-plane key was mutated — this is a PR artifact, not an apply.
    assert await redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE) is None


async def test_parameter_change_without_parameter_is_noop(monkeypatch):
    """A param proposal missing the parameter name emits no artifact (and no crash)."""
    from api.constants import STREAM_GITHUB_PRS

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    redis = _FakeRedis()
    applier = _make_applier(redis)

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
        FieldName.CONTENT: {FieldName.REASON: "x"},
    }
    await applier.process("proposals", "1-0", proposal)

    pr_calls = [c for c in applier.bus.publish.await_args_list if c.args[0] == STREAM_GITHUB_PRS]
    assert pr_calls == []


async def test_prompt_evolution_applied_to_store(monkeypatch):
    """An auto-apply PROMPT_EVOLUTION proposal promotes the directive into the store."""
    from api.config import settings
    from api.constants import REASONING_NODE
    from api.services.prompt_store import PromptStore, set_prompt_store

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr(settings, "PROMPT_EVOLUTION_AUTO_APPLY", True)

    store = PromptStore(_FakeRedis())
    set_prompt_store(store)
    try:
        applier = _make_applier(_FakeRedis())
        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.PROMPT_EVOLUTION,
            FieldName.CONTENT: {
                FieldName.NODE: REASONING_NODE,
                FieldName.TEXT: "Favor high-confluence longs; avoid news-spike entries.",
                FieldName.RATIONALE: "winning factor",
            },
        }
        await applier.process("proposals", "1-0", proposal)
        assert (
            await store.get_active_text(REASONING_NODE)
            == "Favor high-confluence longs; avoid news-spike entries."
        )
    finally:
        set_prompt_store(None)


async def test_prompt_evolution_skipped_when_manual_apply(monkeypatch):
    """With auto-apply off, the directive is NOT written (left for manual apply)."""
    from api.config import settings
    from api.constants import REASONING_NODE
    from api.services.prompt_store import PromptStore, set_prompt_store

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr(settings, "PROMPT_EVOLUTION_AUTO_APPLY", False)

    store = PromptStore(_FakeRedis())
    set_prompt_store(store)
    try:
        applier = _make_applier(_FakeRedis())
        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.PROMPT_EVOLUTION,
            FieldName.CONTENT: {FieldName.NODE: REASONING_NODE, FieldName.TEXT: "x"},
        }
        await applier.process("proposals", "1-0", proposal)
        assert await store.get_active_text(REASONING_NODE) is None
    finally:
        set_prompt_store(None)


async def test_code_change_proposal_files_issue(monkeypatch):
    """A CODE_CHANGE proposal is filed as a GitHub issue (dry-run no-op when
    GitOps unconfigured), never silently dropped, never editing code."""
    from api.constants import FieldName, ProposalType

    logged = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", logged)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())

    applier = _make_applier(_FakeRedis())
    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.CODE_CHANGE,
        FieldName.CONTENT: {FieldName.DESCRIPTION: "add an order-book imbalance tool"},
        FieldName.TRACE_ID: "t-issue",
    }
    await applier.process("proposals", "1-0", proposal)
    # It produced an applied record (issue filed / dry-run) rather than skipping.
    assert logged.await_count == 1
    payload = logged.await_args.args[2]
    assert payload[FieldName.PROPOSAL_TYPE] == ProposalType.CODE_CHANGE


async def test_new_agent_spawns_challenger_dynamically(monkeypatch):
    """A NEW_AGENT proposal with a KNOWN strategy spawns a challenger via the
    injected spawner (config, no deploy) — not a GitHub issue."""
    from unittest.mock import AsyncMock as _AsyncMock

    from api.constants import FieldName, ProposalType

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    # A known strategy is in the registry.
    monkeypatch.setattr(
        "api.services.agents.proposal_applier.STRATEGIES", {"strong_only": object()}
    )

    applier = _make_applier(_FakeRedis())
    spawner = _AsyncMock()
    spawner.spawn = _AsyncMock(
        return_value={FieldName.CHALLENGER_ID: "abc", FieldName.STATUS: "spawned"}
    )
    applier.spawner = spawner

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.NEW_AGENT,
        FieldName.CONTENT: {FieldName.CHALLENGER_CONFIG: {FieldName.STRATEGY: "strong_only"}},
        FieldName.TRACE_ID: "t-new",
    }
    await applier.process("proposals", "1-0", proposal)
    spawner.spawn.assert_awaited_once()


async def test_new_agent_unknown_strategy_files_issue(monkeypatch):
    """A NEW_AGENT for a strategy that needs code falls back to a GitHub issue."""
    from unittest.mock import AsyncMock as _AsyncMock

    from api.constants import FieldName, ProposalType

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {"existing": object()})

    applier = _make_applier(_FakeRedis())
    applier.spawner = _AsyncMock()
    applier.spawner.spawn = _AsyncMock()

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.NEW_AGENT,
        FieldName.CONTENT: {FieldName.CHALLENGER_CONFIG: {FieldName.STRATEGY: "brand_new_strat"}},
        FieldName.TRACE_ID: "t-new2",
    }
    await applier.process("proposals", "1-0", proposal)
    applier.spawner.spawn.assert_not_awaited()  # unknown strategy → issue, not spawn


# ---------------------------------------------------------------------------
# Challenger promotion — approval-gated; on approval does BOTH halves of the
# loop (bias the ReasoningAgent + spawn the winning strategy as a candidate).
# ---------------------------------------------------------------------------


async def _install_prompt_store():
    """Install a real Redis-backed PromptStore for directive assertions."""
    from api.services.prompt_store import PromptStore, set_prompt_store  # noqa: PLC0415

    store = PromptStore(_FakeRedis())
    set_prompt_store(store)
    return store


async def test_challenger_promotion_pending_without_approval(monkeypatch):
    """With auto-apply OFF, first publish (no APPROVED flag) applies nothing —
    the proposal stays pending until an operator approves. This is the manual
    gate restored by CHALLENGER_PROMOTION_AUTO_APPLY=false."""
    from unittest.mock import AsyncMock as _AsyncMock

    from api.constants import REASONING_NODE  # noqa: PLC0415
    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    write_log = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr(
        "api.services.agents.proposal_applier.STRATEGIES", {"mean_reversion": object()}
    )
    monkeypatch.setattr(
        "api.services.agents.proposal_applier.settings.CHALLENGER_PROMOTION_AUTO_APPLY", False
    )
    store = await _install_prompt_store()
    try:
        applier = _make_applier(_FakeRedis())
        applier.spawner = _AsyncMock()
        applier.spawner.spawn = _AsyncMock()

        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.REQUIRES_APPROVAL: True,
            FieldName.CONTENT: {
                FieldName.STRATEGY: "mean_reversion",
                FieldName.SHADOW_EDGE: 2121.0,
                FieldName.CONFIDENCE: 0.66,
            },
            FieldName.TRACE_ID: "t-promo",
        }
        await applier.process("proposals", "1-0", proposal)

        assert await store.get_active_text(REASONING_NODE) is None  # no directive written
        applier.spawner.spawn.assert_not_awaited()  # nothing spawned
        write_log.assert_not_awaited()  # nothing applied/logged
    finally:
        set_prompt_store(None)


async def test_challenger_promotion_approved_biases_and_spawns(monkeypatch):
    """An APPROVED promotion appends a durable directive advisory AND spawns the
    strategy as a live candidate — both halves the operator asked for. The
    directive lives in the (Redis-backed, versioned) PromptStore that the
    ReasoningAgent reads and the Prompt Evolution panel shows."""
    from unittest.mock import AsyncMock as _AsyncMock

    from api.constants import REASONING_NODE  # noqa: PLC0415
    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr(
        "api.services.agents.proposal_applier.STRATEGIES", {"mean_reversion": object()}
    )
    store = await _install_prompt_store()
    try:
        applier = _make_applier(_FakeRedis())
        spawner = _AsyncMock()
        spawner.spawn = _AsyncMock(
            return_value={FieldName.CHALLENGER_ID: "ch1", FieldName.STATUS: "spawned"}
        )
        applier.spawner = spawner

        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.APPROVED: True,
            FieldName.CONTENT: {
                FieldName.STRATEGY: "mean_reversion",
                FieldName.SHADOW_EDGE: 2121.0,
                FieldName.CONFIDENCE: 0.66,
                FieldName.CHALLENGER_CONFIG: {FieldName.STRATEGY: "mean_reversion"},
            },
            FieldName.TRACE_ID: "t-promo2",
        }
        await applier.process("proposals", "1-0", proposal)

        # (1) durable directive advisory mentions the promoted strategy
        directive = await store.get_active_text(REASONING_NODE)
        assert directive is not None and "mean_reversion" in directive
        # (2) the winning strategy spawned as a live candidate
        spawner.spawn.assert_awaited_once()
    finally:
        set_prompt_store(None)


async def test_challenger_promotion_approved_without_spawner_still_biases(monkeypatch):
    """With no spawner (or unknown strategy) the bias still applies — the advisory
    half never depends on the spawn half."""
    from api.constants import REASONING_NODE  # noqa: PLC0415
    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {})
    store = await _install_prompt_store()
    try:
        applier = _make_applier(_FakeRedis())  # spawner stays None

        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.APPROVED: True,
            FieldName.CONTENT: {FieldName.STRATEGY: "mean_reversion", FieldName.CONFIDENCE: 0.7},
            FieldName.TRACE_ID: "t-promo3",
        }
        await applier.process("proposals", "1-0", proposal)
        directive = await store.get_active_text(REASONING_NODE)
        assert directive is not None and "mean_reversion" in directive
    finally:
        set_prompt_store(None)


async def test_challenger_promotion_auto_applies_by_default(monkeypatch):
    """REGRESSION (operator ask: "I don't need to press approve"): with the
    default CHALLENGER_PROMOTION_AUTO_APPLY=True, an eligible promotion applies
    on FIRST publish — no APPROVED flag, no vote: the directive is biased and
    the candidate spawned, and the applied record is written."""
    from unittest.mock import AsyncMock as _AsyncMock

    from api.constants import REASONING_NODE  # noqa: PLC0415
    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    write_log = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr(
        "api.services.agents.proposal_applier.STRATEGIES", {"mean_reversion": object()}
    )
    store = await _install_prompt_store()
    try:
        applier = _make_applier(_FakeRedis())
        spawner = _AsyncMock()
        spawner.spawn = _AsyncMock(
            return_value={FieldName.CHALLENGER_ID: "ch-auto", FieldName.STATUS: "spawned"}
        )
        applier.spawner = spawner

        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.REQUIRES_APPROVAL: True,  # no APPROVED flag — first publish
            FieldName.CONTENT: {
                FieldName.STRATEGY: "mean_reversion",
                FieldName.SHADOW_EDGE: 1234.0,
                FieldName.CONFIDENCE: 0.7,
            },
            FieldName.TRACE_ID: "t-auto-promo",
        }
        await applier.process("proposals", "1-0", proposal)

        directive = await store.get_active_text(REASONING_NODE)
        assert directive is not None and "mean_reversion" in directive
        spawner.spawn.assert_awaited_once()
        write_log.assert_awaited_once()
    finally:
        set_prompt_store(None)


async def test_applied_proposal_pushes_dashboard_notification(monkeypatch):
    """REGRESSION (operator: "auto-applied and not shown anywhere"): every
    applied proposal must surface in the dashboard notification feed, so an
    application the operator never voted on is impossible to miss."""
    from unittest.mock import AsyncMock as _AsyncMock

    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {})
    notif_store = _AsyncMock()
    notif_store.push_notification = _AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.get_redis_store", lambda: notif_store)
    store = await _install_prompt_store()
    try:
        applier = _make_applier(_FakeRedis())
        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.APPROVED: True,
            FieldName.CONTENT: {FieldName.STRATEGY: "mean_reversion", FieldName.CONFIDENCE: 0.7},
            FieldName.TRACE_ID: "t-notif",
        }
        await applier.process("proposals", "1-0", proposal)

        notif_store.push_notification.assert_awaited_once()
        payload = notif_store.push_notification.await_args.args[0]
        assert payload[FieldName.NOTIFICATION_TYPE] == "proposal.applied"
        assert "mean_reversion" in payload[FieldName.MESSAGE]
        assert store is not None
    finally:
        set_prompt_store(None)


async def test_challenger_promotion_approved_always_leaves_a_trace(monkeypatch):
    """REGRESSION: an APPROVED promotion must write an applied record even when
    BOTH halves are skipped (no prompt store, no spawner). The old code returned
    None here, so the operator saw "Approved" and then… nothing — no log, no
    explanation. The record now states exactly what was skipped and why."""
    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    write_log = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {})
    set_prompt_store(None)  # no prompt store installed
    applier = _make_applier(_FakeRedis())  # spawner stays None

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
        FieldName.APPROVED: True,
        FieldName.CONTENT: {FieldName.STRATEGY: "mean_reversion", FieldName.CONFIDENCE: 0.7},
        FieldName.TRACE_ID: "t-promo4",
    }
    await applier.process("proposals", "1-0", proposal)

    write_log.assert_awaited_once()
    log_payload = write_log.await_args.args[2]
    message = log_payload[FieldName.MESSAGE]
    assert "directive skipped — no prompt store installed" in message
    assert "spawn skipped — challenger spawner unavailable" in message


async def test_challenger_promotion_trace_names_unknown_strategy(monkeypatch):
    """When the strategy is not registered, the applied record names it so the
    operator knows the spawn was skipped for a reason, not lost."""
    from api.constants import REASONING_NODE  # noqa: PLC0415
    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    write_log = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {})
    store = await _install_prompt_store()
    try:
        from unittest.mock import AsyncMock as _AsyncMock

        applier = _make_applier(_FakeRedis())
        applier.spawner = _AsyncMock()
        applier.spawner.spawn = _AsyncMock()

        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.APPROVED: True,
            FieldName.CONTENT: {FieldName.STRATEGY: "novel_strategy", FieldName.CONFIDENCE: 0.8},
            FieldName.TRACE_ID: "t-promo5",
        }
        await applier.process("proposals", "1-0", proposal)

        applier.spawner.spawn.assert_not_awaited()
        write_log.assert_awaited_once()
        message = write_log.await_args.args[2][FieldName.MESSAGE]
        assert "directive biased" in message
        assert "strategy 'novel_strategy' not in backtest.strategies" in message
        assert await store.get_active_text(REASONING_NODE) is not None
    finally:
        set_prompt_store(None)


async def test_challenger_promotion_reapproval_is_idempotent(monkeypatch):
    """The loop runs again and again — re-approving the same promotion must not
    keep stacking duplicate advisory lines or bumping the version forever."""
    from api.constants import REASONING_NODE  # noqa: PLC0415
    from api.services.prompt_store import set_prompt_store  # noqa: PLC0415

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {})
    store = await _install_prompt_store()
    try:
        applier = _make_applier(_FakeRedis())
        proposal = {
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.APPROVED: True,
            FieldName.CONTENT: {FieldName.STRATEGY: "mean_reversion", FieldName.CONFIDENCE: 0.7},
            FieldName.TRACE_ID: "t-promo4",
        }
        await applier.process("proposals", "1-0", proposal)
        first = await store.get_directive(REASONING_NODE)
        await applier.process("proposals", "1-1", proposal)  # same promotion again
        second = await store.get_directive(REASONING_NODE)

        assert first[FieldName.VERSION] == second[FieldName.VERSION]  # no re-bump
        # the advisory line was appended exactly once (no duplicate stacking)
        assert second[FieldName.TEXT].count("Promoted strategy 'mean_reversion'") == 1
    finally:
        set_prompt_store(None)


async def test_audit_log_row_is_terminal_not_pending(monkeypatch):
    """Regression (queue-spam bug): the applier's audit row must carry a
    terminal status and the applied summary as content. Without them, every
    proposals read path defaulted status to 'pending' and content to {},
    so each applied change reappeared in the review queue as a fresh
    evidence-less proposal with live Approve/Reject buttons."""
    from api.constants import ProposalStatus

    write_log_mock = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log_mock)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    applier = _make_applier(_FakeRedis())

    proposal = {
        FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
        FieldName.TRACE_ID: "trace-audit-1",
        FieldName.CONTENT: {
            FieldName.PARAMETER: "SIGNAL_CONFIDENCE_MIN_GATE",
            FieldName.PREVIOUS_VALUE: 0.65,
            FieldName.NEW_VALUE: 0.50,
            FieldName.REASON: "test",
        },
    }
    await applier.process("proposals", "1-0", proposal)

    assert write_log_mock.await_count == 1
    (_, _, payload), _ = write_log_mock.call_args
    assert payload[FieldName.STATUS] == ProposalStatus.APPLIED
    assert payload[FieldName.REQUIRES_APPROVAL] is False
    assert payload[FieldName.CONTENT]  # carries the applied summary, not {}
    assert payload[FieldName.MSG_ID]  # unique identity, not the shared trace


async def test_redelivered_proposal_applies_exactly_once(monkeypatch):
    """Regression: stream retries / DLQ replays redeliver the same proposal
    (same msg_id). Re-running the handler duplicated its side effects — a
    second PR artifact and a second audit row per redelivery."""
    write_log_mock = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log_mock)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    applier = _make_applier(_FakeRedis())

    proposal = {
        FieldName.MSG_ID: "msg-dup-1",
        FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
        FieldName.TRACE_ID: "trace-dup-1",
        FieldName.CONTENT: {
            FieldName.PARAMETER: "SIGNAL_CONFIDENCE_MIN_GATE",
            FieldName.PREVIOUS_VALUE: 0.65,
            FieldName.NEW_VALUE: 0.50,
            FieldName.REASON: "test",
        },
    }
    await applier.process("proposals", "1-0", proposal)
    await applier.process("proposals", "1-1", dict(proposal))  # redelivery

    assert write_log_mock.await_count == 1
    from api.constants import STREAM_GITHUB_PRS

    pr_calls = [c for c in applier.bus.publish.await_args_list if c.args[0] == STREAM_GITHUB_PRS]
    assert len(pr_calls) == 1


async def test_unsafe_parameter_change_emits_nothing(monkeypatch):
    """Safe-bounds gate (param_evolution contract): an off-allowlist or
    out-of-bounds PARAMETER_CHANGE emits no pr_request artifact, opens no PR,
    and writes no 'applied' audit row — the queue can never claim the loop
    acted on an unsafe change."""
    from api.constants import STREAM_GITHUB_PRS

    write_log_mock = AsyncMock()
    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", write_log_mock)
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    applier = _make_applier(_FakeRedis())

    for content in (
        {  # not on the auto-editable allowlist
            FieldName.PARAMETER: "REASONING_COOLDOWN_SECONDS",
            FieldName.PREVIOUS_VALUE: 60,
            FieldName.NEW_VALUE: 90,
        },
        {  # allowlisted but wildly out of bounds (500% risk per trade)
            FieldName.PARAMETER: "MAX_RISK_PER_TRADE_PCT",
            FieldName.PREVIOUS_VALUE: 0.02,
            FieldName.NEW_VALUE: 5.0,
        },
    ):
        await applier.process(
            "proposals",
            "1-0",
            {FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE, FieldName.CONTENT: content},
        )

    pr_calls = [c for c in applier.bus.publish.await_args_list if c.args[0] == STREAM_GITHUB_PRS]
    assert pr_calls == []
    write_log_mock.assert_not_awaited()


async def test_llm_call_delay_param_change_is_allowlisted(monkeypatch):
    """GradeAgent's rate-limit response (LLM_CALL_DELAY_MS) is a first-class
    tunable: in-bounds changes pass the gate and emit the durable artifact."""
    from api.constants import STREAM_GITHUB_PRS

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    applier = _make_applier(_FakeRedis())

    await applier.process(
        "proposals",
        "1-0",
        {
            FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
            FieldName.CONTENT: {
                FieldName.PARAMETER: "LLM_CALL_DELAY_MS",
                FieldName.PREVIOUS_VALUE: 200,
                FieldName.NEW_VALUE: 400,
                FieldName.REASON: "rate-limited calls detected",
            },
        },
    )

    pr_calls = [c for c in applier.bus.publish.await_args_list if c.args[0] == STREAM_GITHUB_PRS]
    assert len(pr_calls) == 1


async def test_promotion_advisory_replaces_stale_lines_for_same_strategy(monkeypatch):
    """Regression (directive bloat): advisories embed edge/win-rate numbers, so
    append-with-exact-dedup grew the live LLM prompt by one near-duplicate line
    per promotion cycle. A new promotion must REPLACE the strategy's previous
    advisory lines (self-healing an already-bloated directive) while keeping
    LLM-evolved guidance and other strategies' lines intact."""
    from api.constants import REASONING_NODE
    from api.services.prompt_store import set_prompt_store

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {})
    store = await _install_prompt_store()
    try:
        # A directive already bloated by the old append-only behavior.
        await store.set_directive(
            REASONING_NODE,
            "\n".join(
                [
                    "Favor confluence-confirmed entries.",  # LLM-evolved guidance
                    "Promoted strategy 'mean_reversion': favor mean_reversion-aligned setups (beat baseline by edge 7.4, shadow win-rate 0.77).",
                    "Promoted strategy 'mean_reversion': favor mean_reversion-aligned setups (beat baseline by edge 87.8, shadow win-rate 0.68).",
                    "Promoted strategy 'strong_only': favor strong_only-aligned setups (beat baseline by edge 890.7, shadow win-rate 0.28).",
                ]
            ),
            rationale="seed",
            source="test",
        )
        applier = _make_applier(_FakeRedis())
        await applier.process(
            "proposals",
            "1-0",
            {
                FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
                FieldName.APPROVED: True,
                FieldName.CONTENT: {
                    FieldName.STRATEGY: "mean_reversion",
                    FieldName.CONFIDENCE: 0.71,
                    FieldName.SHADOW_EDGE: 12.3,
                },
                FieldName.TRACE_ID: "t-promo-replace",
            },
        )
        text = (await store.get_directive(REASONING_NODE))[FieldName.TEXT]
        assert text.count("Promoted strategy 'mean_reversion'") == 1  # collapsed
        assert "edge 12.3" in text  # the NEW advisory won
        assert "Favor confluence-confirmed entries." in text  # evolved guidance kept
        assert text.count("Promoted strategy 'strong_only'") == 1  # other strategy kept
    finally:
        set_prompt_store(None)


async def test_repromotion_refreshes_advisory_without_version_bump(monkeypatch):
    """Regression (version-history wall): re-promoting the same strategy only
    refreshes its advisory's edge/win-rate numbers, so it must update the
    directive IN PLACE — same version, no new history entry — instead of
    minting a near-identical version per promotion cycle."""
    from api.constants import REASONING_NODE
    from api.services.prompt_store import set_prompt_store

    monkeypatch.setattr("api.services.agents.proposal_applier.write_agent_log", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.write_heartbeat", AsyncMock())
    monkeypatch.setattr("api.services.agents.proposal_applier.STRATEGIES", {})
    store = await _install_prompt_store()
    try:
        applier = _make_applier(_FakeRedis())

        def _proposal(edge: float) -> dict:
            return {
                FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
                FieldName.APPROVED: True,
                FieldName.CONTENT: {
                    FieldName.STRATEGY: "mean_reversion",
                    FieldName.CONFIDENCE: 0.71,
                    FieldName.SHADOW_EDGE: edge,
                },
                FieldName.TRACE_ID: f"t-promo-{edge}",
            }

        # First promotion creates the advisory → a real new version.
        await applier.process("proposals", "1-0", _proposal(10.0))
        first = await store.get_directive(REASONING_NODE)
        # Re-promotions with fresher numbers refresh in place.
        await applier.process("proposals", "2-0", _proposal(20.0))
        await applier.process("proposals", "3-0", _proposal(30.0))
        record = await store.get_directive(REASONING_NODE)

        assert "edge 30.0" in record[FieldName.TEXT]
        assert record[FieldName.VERSION] == first[FieldName.VERSION]  # no bump
        # In-place refreshes never push history entries — no near-identical wall.
        assert await store.list_history(REASONING_NODE) == []
    finally:
        set_prompt_store(None)
