"""Self-evolving prompt store — the runtime-mutable layer of the Prompt-OS.

The reasoning prompt is layered: an **immutable constitution** (safety laws,
never changes) plus an **adaptive directive** — a short, learned block of
trading guidance that the system improves over time. This module is the home of
that adaptive directive.

Flow (closing the self-improving loop):

    reflection (LLM) → StrategyProposer asks the LLM to draft a better directive
    → PROMPT_EVOLUTION proposal → ProposalApplier calls ``set_directive`` here
    → the next ReasoningAgent decision reads ``get_active_text`` and assembles it
      beneath the constitution → trades → grades → reflection → …

Storage is Redis (Category 2 computed configuration): the active directive per
node plus a capped history for audit and rollback. Every read is best-effort —
a missing directive or a Redis hiccup degrades to ``None`` so the agent simply
runs on the constitution alone, never crashing a decision.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from api.constants import (
    PROMPT_DIRECTIVE_HISTORY_CAP,
    REDIS_KEY_PROMPT_DIRECTIVE,
    REDIS_KEY_PROMPT_DIRECTIVE_HISTORY,
    FieldName,
)
from api.observability import log_structured

# Matches the challenger-promotion advisory line ProposalApplier writes
# (``_bias_directive_toward``): "Promoted strategy '<name>': …". Kept in sync
# with that writer — it is the contract that lets reads self-heal duplicates.
_PROMOTION_ADVISORY_RE = re.compile(r"^Promoted strategy '(?P<strategy>[^']+)':")


def dedupe_promotion_advisories(text: str) -> str:
    """Collapse stacked promotion-advisory lines to ONE per strategy (keep newest).

    Directives written before the replace-not-append fix accumulated a near-
    duplicate "Promoted strategy 'X': …" line per promotion cycle (same words,
    different edge/win-rate numbers). Self-healing on read means the live LLM
    prompt and the Prompt Evolution panel never show the stacked wall, even
    when Redis still holds a pre-fix record.
    """
    lines = text.splitlines()
    newest_by_strategy: dict[str, int] = {}
    for i, line in enumerate(lines):
        match = _PROMOTION_ADVISORY_RE.match(line.strip())
        if match:
            newest_by_strategy[match.group("strategy")] = i
    keep = set(newest_by_strategy.values())
    cleaned = [
        line
        for i, line in enumerate(lines)
        if i in keep or not _PROMOTION_ADVISORY_RE.match(line.strip())
    ]
    return "\n".join(cleaned)


class PromptStore:
    """Redis-backed store of the evolvable per-node adaptive directive."""

    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def get_directive(self, node: str) -> dict[str, Any] | None:
        """The full active directive record for ``node`` (text + version + meta)."""
        try:
            raw = await self.redis.get(REDIS_KEY_PROMPT_DIRECTIVE.format(node=node))
        except Exception:
            log_structured("warning", "prompt_directive_read_failed", node=node, exc_info=True)
            return None
        if not raw:
            return None
        try:
            record = json.loads(raw)
        except (ValueError, TypeError):
            log_structured("warning", "prompt_directive_decode_failed", node=node, exc_info=True)
            return None
        if isinstance(record, dict) and isinstance(record.get(FieldName.TEXT), str):
            record[FieldName.TEXT] = dedupe_promotion_advisories(record[FieldName.TEXT])
        return record

    async def get_active_text(self, node: str) -> str | None:
        """Just the directive text for prompt assembly — ``None`` when unset."""
        record = await self.get_directive(node)
        return (record or {}).get(FieldName.TEXT) or None

    async def set_directive(
        self,
        node: str,
        text: str,
        *,
        rationale: str = "",
        source: str = "",
        bump_version: bool = True,
    ) -> dict[str, Any]:
        """Promote a new directive for ``node``, versioning the prior one.

        The previous record (if any) is pushed onto a capped history list so the
        evolution is auditable and reversible. Returns the new active record.

        Two guards keep the version history MEANINGFUL instead of a wall of
        near-identical entries:

        * Writing text identical to the active directive is a no-op — the
          current record is returned unchanged, no version burned, nothing
          pushed to history.
        * ``bump_version=False`` updates the active text **in place** (same
          version, no history entry). Used when only embedded numbers refresh
          — e.g. a re-promotion of an already-promoted strategy updating its
          edge/win-rate advisory — so history only records substantive changes.
        """
        prev = await self.get_directive(node)
        prev_text = str((prev or {}).get(FieldName.TEXT) or "")
        if prev is not None and text.strip() == prev_text.strip():
            return prev  # identical — never burn a version on a no-op write
        in_place = prev is not None and not bump_version
        version = int((prev or {}).get(FieldName.VERSION, 0)) + (0 if in_place else 1)
        record = {
            FieldName.NODE: node,
            FieldName.TEXT: text,
            FieldName.VERSION: max(version, 1),
            FieldName.RATIONALE: rationale,
            FieldName.SOURCE: source,
            FieldName.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
        }
        history_key = REDIS_KEY_PROMPT_DIRECTIVE_HISTORY.format(node=node)
        try:
            if prev and not in_place:
                await self.redis.lpush(history_key, json.dumps(prev))
                await self.redis.ltrim(history_key, 0, PROMPT_DIRECTIVE_HISTORY_CAP - 1)
            await self.redis.set(REDIS_KEY_PROMPT_DIRECTIVE.format(node=node), json.dumps(record))
        except Exception:
            log_structured("warning", "prompt_directive_write_failed", node=node, exc_info=True)
        log_structured(
            "info",
            "prompt_directive_updated",
            node=node,
            version=record[FieldName.VERSION],
            source=source,
            in_place=in_place,
        )
        return record

    async def list_history(
        self, node: str, limit: int = PROMPT_DIRECTIVE_HISTORY_CAP
    ) -> list[dict]:
        """Prior directive versions for ``node``, newest first."""
        try:
            items = await self.redis.lrange(
                REDIS_KEY_PROMPT_DIRECTIVE_HISTORY.format(node=node), 0, limit - 1
            )
        except Exception:
            log_structured("warning", "prompt_directive_history_failed", node=node, exc_info=True)
            return []
        history: list[dict] = []
        for raw in items or []:
            try:
                history.append(json.loads(raw))
            except (ValueError, TypeError):
                continue
        return history


_prompt_store: PromptStore | None = None


def set_prompt_store(store: PromptStore | None) -> None:
    """Install (or clear) the process-wide prompt store. Called at startup."""
    global _prompt_store
    _prompt_store = store


def get_prompt_store() -> PromptStore | None:
    """Return the process-wide prompt store, or ``None`` before it is installed.

    Callers MUST treat ``None`` as "no adaptive directive" and degrade to the
    constitution-only prompt — never raise.
    """
    return _prompt_store
