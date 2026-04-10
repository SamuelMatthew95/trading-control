from __future__ import annotations

import pytest

from api.in_memory_store import InMemoryStore
from api.runtime_state import set_runtime_store
from api.services.agents import vector_helpers


class _ExplodingSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("db unavailable")


def _exploding_factory():
    return _ExplodingSession()


@pytest.mark.asyncio
async def test_search_vector_memory_uses_in_memory_when_db_fails(monkeypatch):
    monkeypatch.setattr(vector_helpers, "AsyncSessionFactory", _exploding_factory)
    store = InMemoryStore()
    store.add_vector_memory(
        {
            "id": "mem-1",
            "content": "AAPL long setup",
            "metadata": {"trace_id": "t-1"},
            "outcome": {"action": "buy", "confidence": 0.81},
        }
    )
    set_runtime_store(store)

    matches = await vector_helpers.search_vector_memory([0.1, 0.2, 0.3])

    assert len(matches) == 1
    assert matches[0]["id"] == "mem-1"
    assert matches[0]["content"] == "AAPL long setup"
