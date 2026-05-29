"""Learning-loop control plane + applied/pending split surface in memory mode.

These lock the contract the agents-dashboard "Learning Loop" panel depends on:
  * ``control_plane`` carries trading_paused / signal_weight_scale / suspended_agents
  * ``recent_proposals`` distinguishes applied vs pending even in memory mode

Regression for: ``_in_memory_proposals`` used to drop the ProposalApplier's
``applied`` / ``applied_at`` fields, so memory-mode ``recent_proposals`` always
read back ``applied=False`` — the dashboard would mislabel every applied action
as "pending" on the (memory-mode) live deployment.
"""

import pytest

from api.constants import (
    AGENT_PROPOSAL_APPLIER,
    AGENT_REASONING,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    FieldName,
    LogType,
    ProposalType,
)
from api.services.agents.db_helpers import write_agent_log
from api.services.dashboard import learning as learning_module
from api.services.dashboard.learning import get_learning_loop_payload


class _FakeRedis:
    """Minimal async Redis stub returning preset key values."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def get(self, key: str):
        return self._mapping.get(key)


@pytest.mark.asyncio
async def test_recent_proposals_carry_applied_flag_in_memory_mode():
    # conftest resets to memory mode (is_db_available() == False) with an empty store.
    await write_agent_log(
        "trace-applied",
        LogType.PROPOSAL,
        {
            FieldName.SOURCE: AGENT_PROPOSAL_APPLIER,
            FieldName.PROPOSAL_TYPE: ProposalType.SIGNAL_WEIGHT_REDUCTION,
            FieldName.ACTION: "reduce_signal_weight",
            FieldName.APPLIED: True,
            FieldName.APPLIED_AT: "2026-05-29T12:00:00+00:00",
            FieldName.APPLIED_BY: AGENT_PROPOSAL_APPLIER,
            FieldName.MESSAGE: "signal_weight_scale 1.0000 -> 0.7000",
            FieldName.TRACE_ID: "trace-applied",
        },
    )

    payload = await get_learning_loop_payload()
    recent = payload[FieldName.RECENT_PROPOSALS]
    applied = [p for p in recent if p[FieldName.APPLIED]]

    assert applied, "applied proposal must surface with applied=True in memory mode"
    assert applied[0][FieldName.APPLIED_AT] == "2026-05-29T12:00:00+00:00"
    assert applied[0][FieldName.APPLIED_BY] == AGENT_PROPOSAL_APPLIER
    assert "0.7000" in (applied[0][FieldName.MESSAGE] or "")


@pytest.mark.asyncio
async def test_unapplied_proposal_reads_back_as_pending():
    await write_agent_log(
        "trace-pending",
        LogType.PROPOSAL,
        {
            FieldName.SOURCE: "strategy_proposer",
            FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
            FieldName.ACTION: "adjust_threshold",
            FieldName.TRACE_ID: "trace-pending",
        },
    )

    payload = await get_learning_loop_payload()
    recent = payload[FieldName.RECENT_PROPOSALS]
    match = [p for p in recent if p.get(FieldName.TRACE_ID) == "trace-pending"]

    assert match, "the pending proposal should still appear in recent_proposals"
    assert match[0][FieldName.APPLIED] is False
    assert match[0][FieldName.APPLIED_AT] is None


@pytest.mark.asyncio
async def test_control_plane_exposes_redis_state(monkeypatch):
    mapping = {
        REDIS_KEY_TRADING_PAUSED: "1",
        REDIS_KEY_TRADING_PAUSED_REASON: "grade F retirement proposal",
        REDIS_KEY_SIGNAL_WEIGHT_SCALE: "0.49",
        REDIS_KEY_AGENT_SUSPENDED.format(name=AGENT_REASONING): "1799999999.0",
    }

    async def _fake_get_redis():
        return _FakeRedis(mapping)

    monkeypatch.setattr(learning_module, "get_redis", _fake_get_redis)

    payload = await get_learning_loop_payload()
    cp = payload[FieldName.CONTROL_PLANE]

    assert cp[FieldName.TRADING_PAUSED] is True
    assert cp[FieldName.TRADING_PAUSED_REASON] == "grade F retirement proposal"
    assert cp[FieldName.SIGNAL_WEIGHT_SCALE] == 0.49
    suspended_names = [s["agent_name"] for s in cp[FieldName.SUSPENDED_AGENTS]]
    assert AGENT_REASONING in suspended_names


@pytest.mark.asyncio
async def test_control_plane_defaults_when_keys_absent(monkeypatch):
    async def _fake_get_redis():
        return _FakeRedis({})

    monkeypatch.setattr(learning_module, "get_redis", _fake_get_redis)

    payload = await get_learning_loop_payload()
    cp = payload[FieldName.CONTROL_PLANE]

    assert cp[FieldName.TRADING_PAUSED] is False
    assert cp[FieldName.SIGNAL_WEIGHT_SCALE] == 1.0
    assert cp[FieldName.SUSPENDED_AGENTS] == []
