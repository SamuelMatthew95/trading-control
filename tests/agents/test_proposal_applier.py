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
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    SIGNAL_WEIGHT_REDUCTION_FACTOR,
    SIGNAL_WEIGHT_SCALE_MIN,
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
    """On first publish (no APPROVED flag) nothing is applied — it stays pending.

    This is what makes "a human approves, never the system" true: the applier
    leaves the proposal in the queue rather than auto-promoting."""
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
