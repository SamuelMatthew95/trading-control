"""Tests for the self-evolving prompt store."""

from __future__ import annotations

import json

import pytest

from api.constants import FieldName
from api.services.prompt_store import (
    PromptStore,
    get_prompt_store,
    set_prompt_store,
)


class _FakeRedis:
    """Minimal async Redis stub: string GET/SET + list LPUSH/LTRIM/LRANGE."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, **_):
        self.kv[key] = value

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start : end + 1] if end >= 0 else items[start:]


@pytest.fixture(autouse=True)
def _reset_singleton():
    set_prompt_store(None)
    yield
    set_prompt_store(None)


async def test_get_active_text_none_when_unset():
    store = PromptStore(_FakeRedis())
    assert await store.get_active_text("reasoning_node") is None


async def test_set_directive_versions_and_reads_back():
    store = PromptStore(_FakeRedis())
    rec1 = await store.set_directive("reasoning_node", "Prefer high-confluence longs.", source="x")
    assert rec1[FieldName.VERSION] == 1
    assert await store.get_active_text("reasoning_node") == "Prefer high-confluence longs."

    rec2 = await store.set_directive(
        "reasoning_node", "Avoid news-spike entries.", rationale="losing factor", source="y"
    )
    assert rec2[FieldName.VERSION] == 2
    assert await store.get_active_text("reasoning_node") == "Avoid news-spike entries."


async def test_history_keeps_prior_versions_newest_first():
    store = PromptStore(_FakeRedis())
    await store.set_directive("reasoning_node", "v1")
    await store.set_directive("reasoning_node", "v2")
    await store.set_directive("reasoning_node", "v3")
    history = await store.list_history("reasoning_node")
    # Active is v3; history holds the two prior versions, newest first.
    texts = [h[FieldName.TEXT] for h in history]
    assert texts == ["v2", "v1"]


async def test_corrupt_payload_degrades_to_none():
    redis = _FakeRedis()
    redis.kv["prompt:directive:reasoning_node"] = "{not json"
    store = PromptStore(redis)
    assert await store.get_directive("reasoning_node") is None


async def test_singleton_install_and_clear():
    assert get_prompt_store() is None
    store = PromptStore(_FakeRedis())
    set_prompt_store(store)
    assert get_prompt_store() is store


async def test_directive_record_is_json_serialisable():
    store = PromptStore(_FakeRedis())
    rec = await store.set_directive("reasoning_node", "guidance", rationale="why", source="src")
    # Must round-trip cleanly (it is persisted as JSON in Redis).
    assert json.loads(json.dumps(rec))[FieldName.NODE] == "reasoning_node"
