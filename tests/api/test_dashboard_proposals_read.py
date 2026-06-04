"""The dashboard proposals read path in memory mode.

Proves a proposal the StrategyProposer persists is actually returned by the
endpoint payload — in the shape the frontend store/ProposalsSection render —
so the UI "sees" proposals even with Postgres down. Also covers the approve
round-trip (operator approves → next read reflects it) and the empty case.
"""

from __future__ import annotations

import pytest

from api.constants import FieldName, OrderStatus, ProposalStatus, ProposalType
from api.services.agents.db_helpers import persist_proposal
from api.services.dashboard.learning import (
    get_learning_proposals_payload,
    update_proposal_status_payload,
)

pytestmark = pytest.mark.asyncio


def _proposal(trace_id: str) -> dict:
    return {
        FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
        FieldName.CONTENT: {FieldName.DESCRIPTION: "raise RSI entry threshold"},
        FieldName.CONFIDENCE: 0.9,
        FieldName.REFLECTION_TRACE_ID: trace_id,
        FieldName.REQUIRES_APPROVAL: True,
    }


async def test_memory_mode_proposal_is_returned_in_frontend_shape():
    """A proposal persisted in memory mode comes back through the endpoint payload."""
    await persist_proposal(_proposal("refl-xyz"))

    payload = await get_learning_proposals_payload(limit=50)

    assert payload["source"] == "in_memory"
    proposals = payload[FieldName.PROPOSALS]
    assert len(proposals) == 1
    proposal = proposals[0]
    # Exactly the fields the frontend store / ProposalsSection consume:
    assert proposal[FieldName.ID] == "refl-xyz"  # stable id the approve/reject PATCH targets
    assert proposal["proposal_type"] == ProposalType.PARAMETER_CHANGE
    assert proposal["confidence"] == 0.9
    assert proposal["status"] == OrderStatus.PENDING


async def test_memory_mode_approve_is_visible_on_next_read():
    """Approving a proposal updates the store so the next UI read shows it approved."""
    await persist_proposal(_proposal("refl-approve"))

    result = await update_proposal_status_payload("refl-approve", ProposalStatus.APPROVED)
    assert result["status"] == ProposalStatus.APPROVED

    payload = await get_learning_proposals_payload(limit=50)
    assert payload[FieldName.PROPOSALS][0]["status"] == ProposalStatus.APPROVED


async def test_empty_store_returns_empty_list_not_error():
    """No proposals → empty list (the UI shows its empty state, never an error)."""
    payload = await get_learning_proposals_payload(limit=50)
    assert payload[FieldName.PROPOSALS] == []
    assert payload[FieldName.TOTAL] == 0
