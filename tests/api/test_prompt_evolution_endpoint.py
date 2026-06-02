"""Tests for the /dashboard/prompt-evolution payload."""

from __future__ import annotations

import pytest

from api.constants import REASONING_NODE, FieldName
from api.services.dashboard.prompt_evolution import get_prompt_evolution_payload
from api.services.prompt_store import PromptStore, set_prompt_store


class _FakeRedis:
    def __init__(self):
        self.kv = {}
        self.lists = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, **_):
        self.kv[k] = v

    async def lpush(self, k, v):
        self.lists.setdefault(k, []).insert(0, v)

    async def ltrim(self, k, s, e):
        self.lists[k] = self.lists.get(k, [])[s : e + 1]

    async def lrange(self, k, s, e):
        return self.lists.get(k, [])[s : e + 1]


@pytest.fixture(autouse=True)
def _reset():
    set_prompt_store(None)
    yield
    set_prompt_store(None)


async def test_payload_empty_when_no_store():
    payload = await get_prompt_evolution_payload()
    assert payload[FieldName.NODE] == REASONING_NODE
    assert payload[FieldName.ACTIVE] is None
    assert payload[FieldName.HISTORY] == []
    assert payload[FieldName.VERSION] == 0
    assert "auto_apply" in payload


async def test_payload_reflects_active_directive_and_history():
    store = PromptStore(_FakeRedis())
    set_prompt_store(store)
    await store.set_directive(REASONING_NODE, "v1 guidance")
    await store.set_directive(REASONING_NODE, "v2 guidance", rationale="sharper")

    payload = await get_prompt_evolution_payload()
    assert payload[FieldName.ACTIVE][FieldName.TEXT] == "v2 guidance"
    assert payload[FieldName.VERSION] == 2
    assert [h[FieldName.TEXT] for h in payload[FieldName.HISTORY]] == ["v1 guidance"]
    assert payload[FieldName.ENABLED] in (True, False)
