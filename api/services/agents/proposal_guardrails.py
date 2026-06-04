"""Creation-time guardrails for strategy proposals.

The StrategyProposer can emit a proposal every time reflection produces a strong
hypothesis. Without limits that floods the review queue with (a) the same
candidate change repeated across reflection cycles and (b) an unbounded number
of proposals in a single day.

These guardrails enforce both limits at *creation* time. State lives in Redis,
date-keyed exactly like the LLM budget counters, so it:

- holds across the multiple worker processes that may run the proposer,
- survives DB-down ("memory") mode — Redis is always available, only Postgres
  is optional, and
- resets each day automatically as the ``{date}`` key rolls over (a TTL also
  self-cleans the keys).

Fails OPEN: if Redis is unreachable the proposal is allowed through. A flooding
guardrail must never be the reason a genuine proposal is silently dropped.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.constants import (
    PROPOSAL_GUARDRAIL_TTL_SECONDS,
    REDIS_KEY_PROPOSALS_DAILY_COUNT,
    REDIS_KEY_PROPOSALS_DEDUP,
    FieldName,
)
from api.observability import log_structured


def proposal_dedup_key(proposal: dict[str, Any]) -> str:
    """Return a stable fingerprint of a proposal's identity (type + content).

    Two proposals with the same ``proposal_type`` and ``content`` map to the
    same fingerprint, so a repeat within the day is recognised as a duplicate
    regardless of its trace_id / timestamp.
    """
    proposal_type = str(proposal.get(FieldName.PROPOSAL_TYPE, ""))
    content = proposal.get(FieldName.CONTENT, {})
    try:
        content_repr = json.dumps(content, sort_keys=True, default=str)
    except (TypeError, ValueError):
        content_repr = str(content)
    digest = hashlib.sha256(f"{proposal_type}|{content_repr}".encode()).hexdigest()
    return digest[:32]


async def register_proposal_creation(redis: Any, proposal: dict[str, Any]) -> bool:
    """Decide whether ``proposal`` may be created, recording it when it may.

    Returns ``True`` (and records the proposal against today's counters) when
    the proposal is allowed, or ``False`` when it should be skipped because it
    either:

    - duplicates a proposal already emitted today, or
    - would exceed ``settings.MAX_PROPOSALS_PER_DAY``.

    Set ``MAX_PROPOSALS_PER_DAY`` to ``0`` to disable the cap (dedup is bypassed
    too, since the whole guardrail is then off). Fails OPEN on any Redis error.
    """
    if redis is None:
        return True
    cap = int(settings.MAX_PROPOSALS_PER_DAY)
    if cap <= 0:
        return True  # guardrail disabled

    today = datetime.now(timezone.utc).date().isoformat()
    count_key = REDIS_KEY_PROPOSALS_DAILY_COUNT.format(date=today)
    dedup_key = REDIS_KEY_PROPOSALS_DEDUP.format(date=today)
    fingerprint = proposal_dedup_key(proposal)
    proposal_type = proposal.get(FieldName.PROPOSAL_TYPE)

    try:
        # Daily cap — reject once today's total has reached the limit. Checked
        # before SADD so duplicates that are also over the cap don't pollute the
        # dedup set.
        current = int(await redis.get(count_key) or 0)
        if current >= cap:
            log_structured(
                "info",
                "proposal_skipped_daily_cap",
                cap=cap,
                daily_count=current,
                proposal_type=proposal_type,
            )
            return False

        # Dedup — SADD returns 0 when the fingerprint was already present today.
        # Duplicates do NOT consume daily-cap budget.
        added = await redis.sadd(dedup_key, fingerprint)
        if not added:
            log_structured(
                "info",
                "proposal_skipped_duplicate",
                proposal_type=proposal_type,
            )
            return False

        new_count = await redis.incr(count_key)
        # Self-expire so the counters reset for the next day without a cron job.
        await redis.expire(count_key, PROPOSAL_GUARDRAIL_TTL_SECONDS)
        await redis.expire(dedup_key, PROPOSAL_GUARDRAIL_TTL_SECONDS)
        log_structured(
            "info",
            "proposal_created_within_guardrails",
            daily_count=new_count,
            cap=cap,
            proposal_type=proposal_type,
        )
        return True
    except Exception:
        log_structured("warning", "proposal_guardrail_check_failed", exc_info=True)
        return True  # fail open
