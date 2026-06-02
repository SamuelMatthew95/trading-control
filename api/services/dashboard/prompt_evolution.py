"""Dashboard payload for the self-evolving reasoning prompt.

Surfaces the live adaptive directive (the learned guidance that sits beneath the
immutable constitution), its version + rationale, and the full evolution history
so an operator can SEE how the reasoning prompt has changed over time and why.
Read-only; degrades to an empty/disabled view when the prompt store is absent.
"""

from __future__ import annotations

from typing import Any

from api.config import settings
from api.constants import REASONING_NODE, FieldName
from api.services.prompt_store import get_prompt_store


async def get_prompt_evolution_payload(node: str = REASONING_NODE) -> dict[str, Any]:
    """Active directive + version history + loop config for ``node``."""
    store = get_prompt_store()
    active: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []
    if store is not None:
        active = await store.get_directive(node)
        history = await store.list_history(node)
    return {
        FieldName.NODE: node,
        FieldName.ACTIVE: active,
        FieldName.HISTORY: history,
        FieldName.VERSION: int((active or {}).get(FieldName.VERSION, 0)),
        FieldName.ENABLED: settings.PROMPT_EVOLUTION_ENABLED,
        "auto_apply": settings.PROMPT_EVOLUTION_AUTO_APPLY,
    }
