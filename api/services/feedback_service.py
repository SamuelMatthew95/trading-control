"""In-memory feedback / reinforcement service.

A lightweight, dependency-free implementation backing ``api/routes/feedback.py``.
The full reinforcement pipeline (vector memory writes, supervisor passes,
few-shot promotion) is not yet implemented as a durable subsystem; until it is,
this service keeps the feedback endpoints importable, registered, and
responsive — it stores staged annotations, negative/positive memories, feedback
jobs and insights in process memory so the routes never 500.

State is intentionally ephemeral: it is a UI/contract stub, not a record of
truth. When the durable pipeline lands, swap this class for the DB-backed one
and the route surface stays unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from api.constants import FieldName

# Status field is part of the feedback record contract but is not a FieldName
# payload key (no FieldName.FEEDBACK_STATUS member); kept as a local constant.
_FEEDBACK_STATUS = "feedback_status"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class _Record:
    """Generic feedback record with a dict-like ``model_dump``."""

    id: str
    payload: dict[str, Any] = field(default_factory=dict)
    feedback_status: str = "staged"
    store_type: str = "annotation"
    created_at: str = field(default_factory=_now_iso)

    def model_dump(self) -> dict[str, Any]:
        return {
            FieldName.ID: self.id,
            _FEEDBACK_STATUS: self.feedback_status,
            FieldName.STORE_TYPE: self.store_type,
            FieldName.CREATED_AT: self.created_at,
            FieldName.PAYLOAD: self.payload,
        }


class FeedbackService:
    """Process-memory feedback store. All methods are safe and never raise."""

    def __init__(self) -> None:
        self._annotations: list[_Record] = []
        self._memories: list[_Record] = []
        self._jobs: dict[str, _Record] = {}
        self._insights: list[_Record] = []

    # -- annotations / memories ------------------------------------------------
    async def stage_annotation(self, payload: dict[str, Any]) -> _Record:
        record = _Record(id=_new_id(), payload=dict(payload), feedback_status="staged")
        self._annotations.append(record)
        return record

    async def create_negative_memory(self, payload: dict[str, Any]) -> _Record:
        record = _Record(
            id=_new_id(),
            payload=dict(payload),
            feedback_status="stored",
            store_type=str(payload.get(FieldName.STORE_TYPE, "negative-memory")),
        )
        self._memories.append(record)
        return record

    async def create_positive_memory(self, payload: dict[str, Any]) -> _Record:
        merged = {**payload, FieldName.STORE_TYPE: "few-shot"}
        record = await self.create_negative_memory(merged)
        record.store_type = "few-shot"
        return record

    # -- feedback jobs ---------------------------------------------------------
    async def create_feedback_job(self, run_id: str) -> _Record:
        record = _Record(
            id=_new_id(),
            payload={FieldName.RUN_ID: run_id},
            feedback_status="queued",
            store_type="job",
        )
        self._jobs[record.id] = record
        return record

    async def run_feedback_job(self, job_id: str, request: Any | None = None) -> _Record | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.feedback_status = "completed"
        return job

    async def get_feedback_job(self, job_id: str) -> _Record | None:
        return self._jobs.get(job_id)

    # -- insights / supervisor -------------------------------------------------
    async def run_supervisor_pass(self, lookback_runs: int = 50) -> list[_Record]:
        return list(self._insights[-lookback_runs:])

    async def list_insights(self, limit: int = 50) -> list[_Record]:
        return list(self._insights[-limit:])

    async def propose_runs(self) -> list[_Record]:
        # No durable proposal source yet — return the staged annotations as the
        # candidate set so the UI has a consistent, non-erroring shape.
        return list(self._annotations[-50:])
