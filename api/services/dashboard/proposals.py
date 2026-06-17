import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from api.constants import (
    APPROVAL_GATED_PROPOSAL_TYPES,
    STREAM_PROPOSALS,
    FieldName,
    LogType,
    OrderStatus,
    ProposalStatus,
)
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available
from api.services.dashboard.utils import _as_dict


def _in_memory_proposals(limit: int = 20) -> list[dict[str, Any]]:
    """Return proposal events from the runtime store without opening a DB session.

    Delegates to ``InMemoryStore.normalized_proposals`` — the single source of
    truth for the memory-mode proposal shape — so this endpoint, the
    /dashboard/state snapshot, and the WebSocket snapshot can never drift.
    """
    return get_runtime_store().normalized_proposals(limit=limit)


def _set_payload_status(record: dict[str, Any], status: str) -> None:
    payload = _as_dict(record.get(FieldName.PAYLOAD))
    payload[FieldName.STATUS] = status
    record[FieldName.PAYLOAD] = payload


def _proposal_matches(record: dict[str, Any], proposal_id: str) -> bool:
    payload = _as_dict(record.get(FieldName.PAYLOAD))
    candidates = {
        record.get(FieldName.ID),
        record.get(FieldName.TRACE_ID),
        record.get(FieldName.MSG_ID),
        payload.get(FieldName.TRACE_ID),
        payload.get(FieldName.REFLECTION_TRACE_ID),
        payload.get(FieldName.MSG_ID),
    }
    return proposal_id in {str(candidate) for candidate in candidates if candidate is not None}


def _update_in_memory_proposal_status(proposal_id: str, status: str) -> bool:
    store = get_runtime_store()
    updated = False
    for collection in (store.event_history, store.agent_logs):
        for record in collection:
            if record.get(FieldName.LOG_TYPE) == LogType.PROPOSAL and _proposal_matches(
                record, proposal_id
            ):
                _set_payload_status(record, status)
                updated = True
    return updated


def _get_in_memory_proposal_payload(proposal_id: str) -> dict[str, Any] | None:
    """The stored proposal body for *proposal_id* (proposal_type/content/config)."""
    store = get_runtime_store()
    for collection in (store.event_history, store.agent_logs):
        for record in collection:
            if record.get(FieldName.LOG_TYPE) == LogType.PROPOSAL and _proposal_matches(
                record, proposal_id
            ):
                return _as_dict(record.get(FieldName.PAYLOAD))
    return None


async def republish_approved_proposal(payload: dict[str, Any] | None) -> bool:
    """Re-emit an approved, approval-gated proposal to STREAM_PROPOSALS.

    The ProposalApplier deliberately skips approval-gated proposals (e.g.
    ``challenger_promotion``) on first publish; this re-emits them with
    ``APPROVED=True`` so the applier acts on operator approval — the bridge that
    makes "Approve" actually do something. Best-effort: a non-gated proposal, a
    missing payload, or a Redis hiccup is a quiet no-op (the status flip already
    persisted). Returns True only when a republish was sent.
    """
    if not payload:
        return False
    if payload.get(FieldName.PROPOSAL_TYPE) not in APPROVAL_GATED_PROPOSAL_TYPES:
        return False
    republished = dict(payload)
    republished[FieldName.APPROVED] = True
    # The applier's handler only receives `content`, but challenger proposals
    # carry the spawn config at top-level `config` — fold it in so a promotion
    # can spawn the live candidate.
    content = dict(_as_dict(republished.get(FieldName.CONTENT)))
    if not content.get(FieldName.CHALLENGER_CONFIG):
        content[FieldName.CHALLENGER_CONFIG] = republished.get(FieldName.CONFIG) or {}
    republished[FieldName.CONTENT] = content
    try:
        redis = await get_redis()
        await EventBus(redis).publish(STREAM_PROPOSALS, republished)
        return True
    except Exception:
        log_structured("warning", "approval_republish_failed", exc_info=True)
        return False


async def list_proposals_payload() -> dict[str, Any]:
    """Get recent strategy proposals.

    Prefer events-based proposals when available, but degrade gracefully on
    older schemas where the events table/columns do not exist.
    """
    if not is_db_available():
        return {
            FieldName.PROPOSALS: _in_memory_proposals(limit=20),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        proposals = []

        # Primary source for newer schemas.
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT
                            e.id,
                            COALESCE(
                                to_jsonb(e)->'data',
                                to_jsonb(e)->'payload',
                                '{}'::jsonb
                            ) AS payload,
                            e.created_at,
                            e.source
                        FROM events e
                        WHERE event_type = 'strategy.proposal'
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                )
                rows = result.all()
                for row in rows:
                    raw = row[1]
                    data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                    proposals.append(
                        {
                            FieldName.ID: str(row[0]),
                            "symbol": data.get(FieldName.SYMBOL),
                            "action": data.get(FieldName.ACTION),
                            "grade_score": data.get(FieldName.GRADE_SCORE),
                            "bias": data.get(FieldName.BIAS),
                            FieldName.BUYS: data.get(FieldName.BUYS),
                            FieldName.SELLS: data.get(FieldName.SELLS),
                            "strategy_name": data.get(FieldName.STRATEGY_NAME),
                            "trace_id": data.get(FieldName.TRACE_ID),
                            "created_at": row[2].isoformat() if row[2] else None,
                            "source": row[3],
                            "status": data.get(FieldName.STATUS, OrderStatus.PENDING),
                        }
                    )
        except Exception:
            # Compatibility fallback for deployments without events table.
            log_structured("warning", "proposals events query unavailable", exc_info=True)

        if not proposals:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT trace_id, payload, created_at
                        FROM agent_logs
                        WHERE log_type = :log_type
                        ORDER BY created_at DESC
                        LIMIT 20
                    """),
                    {"log_type": LogType.PROPOSAL},
                )
                for row in result.all():
                    payload = _as_dict(row[1])
                    proposals.append(
                        {
                            FieldName.ID: str(row[0]),
                            "symbol": payload.get(FieldName.SYMBOL),
                            "action": payload.get(FieldName.ACTION),
                            "grade_score": payload.get(FieldName.GRADE_SCORE),
                            "bias": payload.get(FieldName.BIAS),
                            FieldName.BUYS: payload.get(FieldName.BUYS),
                            FieldName.SELLS: payload.get(FieldName.SELLS),
                            "strategy_name": payload.get(FieldName.STRATEGY_NAME),
                            "trace_id": row[0],
                            "created_at": row[2].isoformat() if row[2] else None,
                            "source": "agent_logs",
                            "status": payload.get(FieldName.STATUS, OrderStatus.PENDING),
                        }
                    )
        return {
            FieldName.PROPOSALS: proposals,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "proposals fetch failed", exc_info=True)
        return {
            FieldName.PROPOSALS: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def approve_proposal_payload(proposal_id: str) -> dict[str, Any]:
    """Mark a strategy proposal as approved."""
    if not is_db_available():
        if not _update_in_memory_proposal_status(proposal_id, ProposalStatus.APPROVED):
            raise HTTPException(status_code=404, detail="Proposal not found") from None
        return {"status": ProposalStatus.APPROVED, FieldName.ID: proposal_id, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "SELECT id, data FROM events "
                        "WHERE id = :id AND event_type = 'strategy.proposal'"
                    ),
                    {FieldName.ID: proposal_id},
                )
                row = result.first()
                if not row:
                    raise HTTPException(status_code=404, detail="Proposal not found") from None
                raw = row[1]
                data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                data[FieldName.STATUS] = "approved"
                await session.execute(
                    text("UPDATE events SET data = :data WHERE id = :id"),
                    {"data": json.dumps(data), FieldName.ID: proposal_id},
                )
        return {"status": "approved", FieldName.ID: proposal_id}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal approve failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


async def reject_proposal_payload(proposal_id: str) -> dict[str, Any]:
    """Mark a strategy proposal as rejected."""
    if not is_db_available():
        if not _update_in_memory_proposal_status(proposal_id, ProposalStatus.REJECTED):
            raise HTTPException(status_code=404, detail="Proposal not found") from None
        return {"status": ProposalStatus.REJECTED, FieldName.ID: proposal_id, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "SELECT id, data FROM events "
                        "WHERE id = :id AND event_type = 'strategy.proposal'"
                    ),
                    {FieldName.ID: proposal_id},
                )
                row = result.first()
                if not row:
                    raise HTTPException(status_code=404, detail="Proposal not found") from None
                raw = row[1]
                data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                data[FieldName.STATUS] = "rejected"
                await session.execute(
                    text("UPDATE events SET data = :data WHERE id = :id"),
                    {"data": json.dumps(data), FieldName.ID: proposal_id},
                )
        return {"status": "rejected", FieldName.ID: proposal_id}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal reject failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# NOTE: get_learning_proposals_payload / update_proposal_status_payload live in
# api/services/dashboard/learning.py — the routed implementations carry the
# approve→republish bridge and the events-table fallback. The near-verbatim
# copies that used to sit here were dead code waiting to be imported by
# mistake (silently regressing approval), so they were removed.
