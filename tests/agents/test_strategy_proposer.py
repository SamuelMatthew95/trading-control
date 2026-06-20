"""Tests for StrategyProposer — hypothesis filtering and proposal publishing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import StrategyProposer

# Async tests run via pyproject.toml `asyncio_mode = auto`; no global asyncio mark
# here so the sync `_build_proposal` unit tests below aren't mis-marked.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.consume = AsyncMock(return_value=[])
    bus.acknowledge = AsyncMock()
    return bus


@pytest.fixture
def mock_dlq():
    dlq = MagicMock(spec=DLQManager)
    dlq.push = AsyncMock()
    return dlq


@pytest.fixture
def agent_state():
    return AgentStateRegistry()


@pytest.fixture
def strategy_proposer(mock_bus, mock_dlq, agent_state):
    return StrategyProposer(mock_bus, mock_dlq, agent_state=agent_state)


# ---------------------------------------------------------------------------
# Confidence filtering
# ---------------------------------------------------------------------------


async def test_filters_low_confidence_hypotheses(strategy_proposer, mock_bus):
    """Hypotheses below HYPOTHESIS_MIN_CONFIDENCE (default 0.7) must be ignored."""
    reflection_data = {
        "trace_id": "trace-001",
        "hypotheses": [
            {"description": "weak hypothesis", "confidence": 0.3, "type": "parameter"},
            {"description": "another weak", "confidence": 0.5, "type": "rule"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    # Nothing should be published to proposals or notifications
    for call in mock_bus.publish.call_args_list:
        stream = call[0][0]
        assert stream not in ("proposals", "notifications", "github_prs"), (
            f"Expected no publish but got publish to '{stream}' for low-confidence hypotheses"
        )


async def test_empty_hypotheses_publishes_nothing(strategy_proposer, mock_bus):
    """An empty hypotheses list must produce zero publishes."""
    reflection_data = {
        "trace_id": "trace-empty",
        "hypotheses": [],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    assert mock_bus.publish.call_count == 0


# ---------------------------------------------------------------------------
# Parameter change proposals
# ---------------------------------------------------------------------------


async def test_publishes_parameter_change_proposal(strategy_proposer, mock_bus):
    """A high-confidence 'parameter' hypothesis publishes to the proposals stream."""
    reflection_data = {
        "trace_id": "trace-param",
        "hypotheses": [
            {"description": "increase signal threshold", "confidence": 0.8, "type": "parameter"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    assert len(proposals_calls) == 1

    proposal = proposals_calls[0][0][1]
    assert proposal["proposal_type"] == "parameter_change"
    assert proposal["requires_approval"] is True
    assert proposal["content"]["implementation"] == "db_update"


# ---------------------------------------------------------------------------
# Rule change proposals
# ---------------------------------------------------------------------------


async def test_publishes_rule_change_proposal(strategy_proposer, mock_bus):
    """A high-confidence 'rule' hypothesis publishes to proposals AND github_prs."""
    reflection_data = {
        "trace_id": "trace-rule",
        "hypotheses": [
            {"description": "change entry rule", "confidence": 0.85, "type": "rule"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    github_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "github_prs"]

    assert len(proposals_calls) == 1
    assert len(github_calls) == 1

    proposal = proposals_calls[0][0][1]
    assert proposal["proposal_type"] == "code_change"
    assert proposal["content"]["implementation"] == "github_pr"


# ---------------------------------------------------------------------------
# Regime adjustment proposals
# ---------------------------------------------------------------------------


async def test_publishes_regime_adjustment_proposal(strategy_proposer, mock_bus):
    """A high-confidence 'regime' hypothesis produces a proposal_type='regime_adjustment'."""
    reflection_data = {
        "trace_id": "trace-regime",
        "regime_edge": {"current_regime": "risk_off", "recommendation": "reduce exposure"},
        "hypotheses": [
            {"description": "switch to defensive mode", "confidence": 0.8, "type": "regime"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    assert len(proposals_calls) == 1

    proposal = proposals_calls[0][0][1]
    assert proposal["proposal_type"] == "regime_adjustment"
    # regime_context should be populated from reflection regime_edge
    assert proposal["content"]["regime_context"]["current_regime"] == "risk_off"


# ---------------------------------------------------------------------------
# Parameter-shaped hypotheses must NOT recur as REGIME_ADJUSTMENT issues
# (regression for issue #334 — the same generic "signal confidence too low"
# proposal re-filed a fresh GitHub issue every day because a `signal_confidence`
# hypothesis was mis-routed to REGIME_ADJUSTMENT instead of the auto-applyable
# PARAMETER_CHANGE path. See api/services/param_evolution.HYPOTHESIS_PARAM_MAP.)
# ---------------------------------------------------------------------------


async def test_signal_confidence_hypothesis_routes_to_parameter_change(strategy_proposer, mock_bus):
    """A 'signal_confidence' hypothesis is a parameter-tuning request, not a
    code/feature one — it must route to parameter_change, never the recurring
    regime_adjustment GitHub issue (issue #334)."""
    reflection_data = {
        "trace_id": "trace-334",
        "hypotheses": [
            {
                "description": "The model's signal confidence is too low, "
                "resulting in suboptimal trade execution.",
                "confidence": 0.8,
                "type": "signal_confidence",
            },
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    assert len(proposals_calls) == 1
    proposal = proposals_calls[0][0][1]
    assert proposal["proposal_type"] == "parameter_change"
    assert proposal["content"]["implementation"] == "db_update"
    # No GitHub issue path: parameter_change never publishes to github_prs.
    github_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "github_prs"]
    assert len(github_calls) == 0


async def test_signal_confidence_with_value_emits_concrete_param_change(
    strategy_proposer, mock_bus
):
    """When the hypothesis carries an in-bounds value, the mapped parameter is
    stamped concretely so the applier can open a real config PR."""
    reflection_data = {
        "trace_id": "trace-334b",
        "hypotheses": [
            {
                "description": "signal confidence floor too low",
                "confidence": 0.85,
                "type": "signal_confidence",
                "proposed_value": 0.55,
            },
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposal = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"][0][0][1]
    content = proposal["content"]
    assert proposal["proposal_type"] == "parameter_change"
    assert content["parameter"] == "SIGNAL_CONFIDENCE_MIN_GATE"
    assert content["new_value"] == 0.55


async def test_near_miss_confidence_alias_routes_to_parameter_change(strategy_proposer, mock_bus):
    """A near-miss confidence category ('low_confidence') the LLM might emit must
    also reach PARAMETER_CHANGE, not reopen the recurring REGIME_ADJUSTMENT issue
    (issue #334 hardening — the loop is not normalized upstream)."""
    reflection_data = {
        "trace_id": "trace-334-alias",
        "regime_edge": {"current_regime": "losing"},
        "hypotheses": [
            {
                "description": "signal confidence is too low for good execution",
                "confidence": 0.8,
                "type": "low_confidence",
            },
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposal = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"][0][0][1]
    assert proposal["proposal_type"] == "parameter_change"
    github_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "github_prs"]
    assert len(github_calls) == 0


async def test_regime_hypothesis_still_files_human_issue(strategy_proposer, mock_bus):
    """A genuinely strategic 'regime' hypothesis (not a tunable parameter) must
    still route to regime_adjustment so it reaches a human — the routing fix
    must not swallow real design proposals."""
    reflection_data = {
        "trace_id": "trace-regime2",
        "regime_edge": {"current_regime": "losing"},
        "hypotheses": [
            {
                "description": "rotate to a mean-reversion strategy",
                "confidence": 0.8,
                "type": "regime",
            },
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposal = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"][0][0][1]
    assert proposal["proposal_type"] == "regime_adjustment"


# ---------------------------------------------------------------------------
# Notification per proposal
# ---------------------------------------------------------------------------


async def test_notification_published_per_proposal(strategy_proposer, mock_bus):
    """Each strong hypothesis that produces a proposal also publishes one notification."""
    reflection_data = {
        "trace_id": "trace-multi",
        "hypotheses": [
            {"description": "hypothesis one", "confidence": 0.75, "type": "parameter"},
            {"description": "hypothesis two", "confidence": 0.80, "type": "regime"},
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposals_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"]
    notifications_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "notifications"]

    assert len(proposals_calls) == 2
    assert len(notifications_calls) == 2


async def test_emits_prompt_evolution_proposal(strategy_proposer, mock_bus, monkeypatch):
    """StrategyProposer asks the LLM to draft a directive and publishes it as a
    PROMPT_EVOLUTION proposal — the LLM suggesting its own prompt."""
    from api.config import settings
    from api.constants import STREAM_PROPOSALS, FieldName, ProposalType

    monkeypatch.setattr(settings, "PROMPT_EVOLUTION_ENABLED", True)
    monkeypatch.setattr("api.services.agents.strategy_proposer.persist_proposal", AsyncMock())
    monkeypatch.setattr(
        "api.services.llm_router.call_llm_with_system",
        AsyncMock(
            return_value=(
                '{"directive": "Favor high-confluence longs.", "rationale": "wins"}',
                10,
                0.0,
            )
        ),
    )
    reflection = {
        "trace_id": "t-evo",
        "winning_factors": ["confluence"],
        "losing_factors": ["news_spike"],
        "summary": "ok",
    }
    await strategy_proposer._emit_prompt_evolution_proposal(reflection, "2026-01-01T00:00:00Z")

    pubs = [
        c.args for c in mock_bus.publish.call_args_list if c.args and c.args[0] == STREAM_PROPOSALS
    ]
    assert pubs, "expected a PROMPT_EVOLUTION proposal to be published"
    proposal = pubs[0][1]
    assert proposal[FieldName.PROPOSAL_TYPE] == ProposalType.PROMPT_EVOLUTION
    assert proposal[FieldName.CONTENT][FieldName.TEXT] == "Favor high-confluence longs."


async def test_prompt_evolution_disabled_emits_nothing(strategy_proposer, mock_bus, monkeypatch):
    from api.config import settings
    from api.constants import STREAM_PROPOSALS

    monkeypatch.setattr(settings, "PROMPT_EVOLUTION_ENABLED", False)
    await strategy_proposer._emit_prompt_evolution_proposal(
        {"trace_id": "t"}, "2026-01-01T00:00:00Z"
    )
    pubs = [
        c.args for c in mock_bus.publish.call_args_list if c.args and c.args[0] == STREAM_PROPOSALS
    ]
    assert not pubs


# ---------------------------------------------------------------------------
# Concrete, bounds-valid parameter changes → real config PR (helpful link)
# ---------------------------------------------------------------------------


def test_concrete_param_hypothesis_becomes_applicable_change(strategy_proposer):
    """A parameter hypothesis that names an allowlisted param + in-bounds value
    carries parameter/new_value/previous_value so the applier can open a PR."""
    hypothesis = {
        "description": "tighten stop loss to cut losers",
        "confidence": 0.85,
        "type": "parameter",
        "parameter": "STOP_LOSS_PCT",
        "proposed_value": 0.04,  # in-bounds (0.01, 0.15) AND != current default
    }
    proposal = strategy_proposer._build_proposal(
        hypothesis, {"trace_id": "t1"}, "2026-01-01T00:00:00Z"
    )
    content = proposal["content"]
    assert proposal["proposal_type"] == "parameter_change"
    assert content["parameter"] == "STOP_LOSS_PCT"
    assert content["new_value"] == 0.04
    assert "previous_value" in content  # current value stamped from the allowlist
    assert "PR" in content["note"]


def test_noop_param_change_degrades_to_review_item(strategy_proposer):
    """Proposing the value the parameter already has is a no-op — must NOT become
    a concrete change / open a PR for nothing."""
    from api import constants

    current = float(constants.STOP_LOSS_PCT)
    hypothesis = {
        "description": "keep stop the same",
        "confidence": 0.9,
        "type": "parameter",
        "parameter": "STOP_LOSS_PCT",
        "proposed_value": current,
    }
    proposal = strategy_proposer._build_proposal(
        hypothesis, {"trace_id": "t-noop"}, "2026-01-01T00:00:00Z"
    )
    assert "parameter" not in proposal["content"]


def test_vague_param_hypothesis_degrades_to_review_item(strategy_proposer):
    """A parameter hypothesis with no concrete param stays description-only —
    the applier safely no-ops it instead of opening a bogus PR."""
    hypothesis = {"description": "do better on entries", "confidence": 0.8, "type": "parameter"}
    proposal = strategy_proposer._build_proposal(
        hypothesis, {"trace_id": "t2"}, "2026-01-01T00:00:00Z"
    )
    assert "parameter" not in proposal["content"]
    assert proposal["proposal_type"] == "parameter_change"


def test_out_of_bounds_param_hypothesis_is_not_promoted(strategy_proposer):
    """An out-of-bounds value is rejected → not promoted to a concrete change."""
    hypothesis = {
        "description": "set an unsafe stop",
        "confidence": 0.9,
        "type": "parameter",
        "parameter": "STOP_LOSS_PCT",
        "proposed_value": 0.99,  # outside (0.01, 0.15)
    }
    proposal = strategy_proposer._build_proposal(
        hypothesis, {"trace_id": "t3"}, "2026-01-01T00:00:00Z"
    )
    assert "parameter" not in proposal["content"]


def test_tunable_parameters_helper_exposes_current_and_bounds():
    from api.services.param_evolution import PARAM_BOUNDS, tunable_parameters

    tp = tunable_parameters()
    assert tp, "expected at least one resolvable tunable parameter"
    for name, meta in tp.items():
        assert name in PARAM_BOUNDS
        assert set(meta) == {"current", "min", "max"}
        assert isinstance(meta["current"], float)
        assert meta["min"] <= meta["max"]


# ---------------------------------------------------------------------------
# Claude-Code-ready briefs + honest evidence tiering (issue #341 fix)
# ---------------------------------------------------------------------------


async def test_design_proposal_carries_brief_and_evidence(strategy_proposer, mock_bus):
    """A design/issue proposal (regime/code/new_agent) carries a full brief +
    evidence block on its content so the GitHub issue is actionable."""
    reflection_data = {
        "trace_id": "trace-brief",
        "trades_analyzed": 30,
        "win_rate": 0.45,
        "regime_edge": {"current_regime": "risk_off"},
        "hypotheses": [
            {
                "description": "rotate to a mean-reversion strategy in risk-off",
                "confidence": 0.85,
                "type": "regime",
            },
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposal = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"][0][0][1]
    content = proposal["content"]
    assert "brief" in content
    assert "evidence" in content
    assert content["evidence"]["sample_size"] == 30
    assert "Ready-to-paste Claude Code prompt" in content["brief"]


async def test_preliminary_design_proposal_brief_is_a_watch_item(strategy_proposer, mock_bus):
    """A regime/model proposal off a tiny sample (the #341 shape) is framed as a
    WATCH ITEM in the brief, not a confident go-ahead — it is still surfaced, never
    blocked, but honestly tiered."""
    reflection_data = {
        "trace_id": "trace-prelim",
        "trades_analyzed": 1,
        "regime_edge": {"current_regime": "risk_off"},
        "hypotheses": [
            {
                "description": "disable the model in the risk-off regime",
                "confidence": 0.8,
                "type": "regime",
            },
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposal = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"][0][0][1]
    brief = proposal["content"]["brief"]
    assert "WATCH ITEM" in brief
    assert "Preliminary" in brief


async def test_parameter_proposal_stays_lean_without_a_brief(strategy_proposer, mock_bus):
    """Parameter proposals route to a config PR / control plane, not a GitHub issue,
    so they stay lean — no brief is attached (and the dedup fingerprint stays stable)."""
    reflection_data = {
        "trace_id": "trace-param-lean",
        "trades_analyzed": 30,
        "hypotheses": [
            {
                "description": "increase the signal threshold",
                "confidence": 0.8,
                "type": "parameter",
            },
        ],
    }
    await strategy_proposer.process("reflection_outputs", "id-1", reflection_data)

    proposal = [c for c in mock_bus.publish.call_args_list if c[0][0] == "proposals"][0][0][1]
    assert proposal["proposal_type"] == "parameter_change"
    assert "brief" not in proposal["content"]
