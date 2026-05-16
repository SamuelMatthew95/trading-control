import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from api.constants import FieldName, LogType, OrderStatus, ProposalStatus
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.services.dashboard.utils import _as_dict, _timestamp_to_iso


def _in_memory_proposals(limit: int = 20) -> list[dict[str, Any]]:
    """Return proposal events from the runtime store without opening a DB session."""
    safe_limit = max(1, min(limit, 200))
    proposals: list[dict[str, Any]] = []
    for event in get_runtime_store().get_events(limit=200):
        if event.get(FieldName.LOG_TYPE) != LogType.PROPOSAL:
            continue
        payload = _as_dict(event.get(FieldName.PAYLOAD))
        trace_id = (
            event.get(FieldName.TRACE_ID)
            or payload.get(FieldName.TRACE_ID)
            or payload.get(FieldName.REFLECTION_TRACE_ID)
            or payload.get(FieldName.MSG_ID)
        )
        proposal_id = str(trace_id or len(proposals) + 1)
        timestamp = _timestamp_to_iso(
            event.get(FieldName.CREATED_AT)
            or event.get(FieldName.TIMESTAMP)
            or payload.get(FieldName.TIMESTAMP)
        )
        proposals.append(
            {
                FieldName.ID: proposal_id,
                "symbol": payload.get(FieldName.SYMBOL),
                "action": payload.get(FieldName.ACTION),
                "grade_score": payload.get(FieldName.GRADE_SCORE),
                "bias": payload.get(FieldName.BIAS),
                FieldName.BUYS: payload.get(FieldName.BUYS),
                FieldName.SELLS: payload.get(FieldName.SELLS),
                "strategy_name": payload.get(FieldName.STRATEGY_NAME),
                "trace_id": trace_id,
                "created_at": timestamp,
                "source": "in_memory",
                "status": payload.get(FieldName.STATUS, OrderStatus.PENDING),
                "proposal_type": payload.get(FieldName.PROPOSAL_TYPE, "parameter_change"),
                "content": payload.get(FieldName.CONTENT, {}),
                "requires_approval": payload.get(FieldName.REQUIRES_APPROVAL, True),
                "confidence": payload.get(FieldName.CONFIDENCE),
                "reflection_trace_id": payload.get(FieldName.REFLECTION_TRACE_ID),
                "timestamp": timestamp,
            }
        )
        if len(proposals) >= safe_limit:
            break
    return proposals


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


async def approve_proposal_db(proposal_id: str) -> dict[str, Any]:
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


async def reject_proposal_db(proposal_id: str) -> dict[str, Any]:
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


async def get_learning_proposals_payload(limit: int) -> dict[str, Any]:
    """Get recent strategy proposals from agent_logs."""
    if not is_db_available():
        proposals = _in_memory_proposals(limit=limit)
        return {
            FieldName.PROPOSALS: proposals,
            FieldName.TOTAL: len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = :log_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"log_type": LogType.PROPOSAL, FieldName.LIMIT: limit},
            )
            rows = result.all()
        proposals = []
        for row in rows:
            payload = _as_dict(row[1])
            proposals.append(
                {
                    FieldName.ID: row[0],
                    "proposal_type": payload.get(FieldName.PROPOSAL_TYPE, "parameter_change"),
                    "content": payload.get(FieldName.CONTENT, {}),
                    "requires_approval": payload.get(FieldName.REQUIRES_APPROVAL, True),
                    "confidence": payload.get(FieldName.CONFIDENCE),
                    "reflection_trace_id": payload.get(FieldName.REFLECTION_TRACE_ID),
                    "status": payload.get(FieldName.STATUS, OrderStatus.PENDING),
                    "timestamp": row[2].isoformat() if row[2] else None,
                }
            )

        # Backward compatibility: some deployments store proposals in events only.
        if not proposals:
            try:
                async with AsyncSessionFactory() as session:
                    fallback_result = await session.execute(
                        text("""
                            SELECT
                                e.id,
                                COALESCE(
                                    to_jsonb(e)->'data',
                                    to_jsonb(e)->'payload',
                                    '{}'::jsonb
                                ) AS payload,
                                e.created_at
                            FROM events e
                            WHERE event_type = 'strategy.proposal'
                            ORDER BY created_at DESC
                            LIMIT :limit
                        """),
                        {FieldName.LIMIT: limit},
                    )
                    for row in fallback_result.all():
                        data = _as_dict(row[1])
                        proposals.append(
                            {
                                FieldName.ID: str(row[0]),
                                "proposal_type": data.get(
                                    FieldName.PROPOSAL_TYPE, "strategy_proposal"
                                ),
                                "content": data,
                                "requires_approval": True,
                                "confidence": data.get(FieldName.CONFIDENCE),
                                "reflection_trace_id": data.get(FieldName.TRACE_ID),
                                "status": data.get(FieldName.STATUS, OrderStatus.PENDING),
                                "timestamp": row[2].isoformat() if row[2] else None,
                            }
                        )
            except Exception:
                log_structured(
                    "warning",
                    "learning proposals events fallback unavailable",
                    exc_info=True,
                )
        return {
            FieldName.PROPOSALS: proposals,
            FieldName.TOTAL: len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "proposals fetch failed", exc_info=True)
        return {
            FieldName.PROPOSALS: [],
            FieldName.TOTAL: 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def update_proposal_status_db(trace_id: str, status: str) -> dict[str, Any]:
    """Persist proposal approval or rejection back to agent_logs payload."""
    if not is_db_available():
        if not _update_in_memory_proposal_status(trace_id, status):
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    UPDATE agent_logs
                    SET payload = (payload::jsonb || jsonb_build_object('status', :status::text))::text
                    WHERE trace_id = :trace_id AND log_type = :log_type
                    RETURNING trace_id
                """),
                {"trace_id": trace_id, "status": status, "log_type": LogType.PROPOSAL},
            )
            updated = result.fetchone()
            await session.commit()
        if updated is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal_status_update_failed", trace_id=trace_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
