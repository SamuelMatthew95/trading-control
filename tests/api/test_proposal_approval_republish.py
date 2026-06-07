"""Approval actually does something — the bridge from "Approve" to application.

A ``challenger_promotion`` is approval-gated: the ProposalApplier skips it on
first publish, so an operator's approval must re-emit it to STREAM_PROPOSALS
with ``APPROVED=True`` for the applier to act. These tests cover that bridge in
memory mode (the deployed default), including that non-gated proposals and
rejections never republish.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.constants import (
    STREAM_PROPOSALS,
    FieldName,
    ProposalStatus,
    ProposalType,
)
from api.services.agents.db_helpers import persist_proposal
from api.services.dashboard import proposals as proposals_module
from api.services.dashboard.learning import update_proposal_status_payload

pytestmark = pytest.mark.asyncio


def _challenger_proposal(trace_id: str) -> dict:
    return {
        FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
        FieldName.REQUIRES_APPROVAL: True,
        FieldName.CONFIG: {FieldName.STRATEGY: "mean_reversion"},
        FieldName.CONTENT: {
            FieldName.STRATEGY: "mean_reversion",
            FieldName.SHADOW_EDGE: 2121.0,
            FieldName.CONFIDENCE: 0.66,
        },
        FieldName.TRACE_ID: trace_id,
    }


def _capture_bus(monkeypatch) -> list:
    """Patch the republish path's EventBus/get_redis; return the publish log."""
    published: list[tuple[str, dict]] = []

    class _FakeBus:
        def __init__(self, _redis):
            pass

        async def publish(self, stream, event, maxlen=None):
            published.append((stream, event))
            return "1-0"

    monkeypatch.setattr(proposals_module, "EventBus", _FakeBus)
    monkeypatch.setattr(proposals_module, "get_redis", AsyncMock(return_value=object()))
    return published


async def test_approving_challenger_promotion_republishes_for_application(monkeypatch):
    """Approve → re-emit to STREAM_PROPOSALS with APPROVED=True and spawn config folded in."""
    published = _capture_bus(monkeypatch)
    await persist_proposal(_challenger_proposal("promo-1"))

    result = await update_proposal_status_payload("promo-1", ProposalStatus.APPROVED)
    assert result["status"] == ProposalStatus.APPROVED

    assert published, "approval should republish the proposal to STREAM_PROPOSALS"
    stream, event = published[0]
    assert stream == STREAM_PROPOSALS
    assert event[FieldName.APPROVED] is True
    # The applier handler only receives `content`, so the spawn config must be
    # folded in from the proposal's top-level `config`.
    config = event[FieldName.CONTENT][FieldName.CHALLENGER_CONFIG]
    assert config[FieldName.STRATEGY] == "mean_reversion"


async def test_rejecting_challenger_promotion_does_not_republish(monkeypatch):
    """A rejection flips status but never re-emits for application."""
    published = _capture_bus(monkeypatch)
    await persist_proposal(_challenger_proposal("promo-2"))

    await update_proposal_status_payload("promo-2", ProposalStatus.REJECTED)
    assert published == []


async def test_approving_non_gated_proposal_does_not_republish(monkeypatch):
    """Parameter changes apply on consume — approval must not re-emit them."""
    published = _capture_bus(monkeypatch)
    await persist_proposal(
        {
            FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
            FieldName.CONTENT: {FieldName.DESCRIPTION: "raise RSI threshold"},
            FieldName.TRACE_ID: "param-1",
        }
    )

    await update_proposal_status_payload("param-1", ProposalStatus.APPROVED)
    assert published == []
