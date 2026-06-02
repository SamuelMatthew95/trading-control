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
from datetime import datetime, timezone
from typing import Any

from api.constants import (
    PROMPT_DIRECTIVE_HISTORY_CAP,
    REDIS_KEY_PROMPT_DIRECTIVE,
    REDIS_KEY_PROMPT_DIRECTIVE_HISTORY,
    FieldName,
)
from api.observability import log_structured


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
            return json.loads(raw)
        except (ValueError, TypeError):
            log_structured("warning", "prompt_directive_decode_failed", node=node, exc_info=True)
            return None

    async def get_active_text(self, node: str) -> str | None:
        """Just the directive text for prompt assembly — ``None`` when unset."""
        record = await self.get_directive(node)
        return (record or {}).get(FieldName.TEXT) or None

    async def set_directive(
        self, node: str, text: str, *, rationale: str = "", source: str = ""
    ) -> dict[str, Any]:
        """Promote a new directive for ``node``, versioning the prior one.

        The previous record (if any) is pushed onto a capped history list so the
        evolution is auditable and reversible. Returns the new active record.
        """
        prev = await self.get_directive(node)
        version = int((prev or {}).get(FieldName.VERSION, 0)) + 1
        record = {
            FieldName.NODE: node,
            FieldName.TEXT: text,
            FieldName.VERSION: version,
            FieldName.RATIONALE: rationale,
            FieldName.SOURCE: source,
            FieldName.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
        }
        history_key = REDIS_KEY_PROMPT_DIRECTIVE_HISTORY.format(node=node)
        try:
            if prev:
                await self.redis.lpush(history_key, json.dumps(prev))
                await self.redis.ltrim(history_key, 0, PROMPT_DIRECTIVE_HISTORY_CAP - 1)
            await self.redis.set(REDIS_KEY_PROMPT_DIRECTIVE.format(node=node), json.dumps(record))
        except Exception:
            log_structured("warning", "prompt_directive_write_failed", node=node, exc_info=True)
        log_structured(
            "info", "prompt_directive_updated", node=node, version=version, source=source
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
