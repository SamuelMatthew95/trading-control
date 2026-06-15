"""ChallengerStore — the durable (Redis) per-challenger shadow track record.

Proves the record survives the way Redis does (persists, doesn't reset), that
graduation is independent of the per-close performance write (so neither clobbers
the other), and that reads degrade to ``None`` rather than fabricating a record.
This is the piece that stops a challenger's evidence evaporating on every restart.
"""

from __future__ import annotations

import pytest

from api.constants import CHALLENGER_PERF_PNL_CAP, FieldName
from api.services.challenger_store import ChallengerStore

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    """Minimal hash store supporting the ``hset(mapping=...)`` / ``hgetall`` ops."""

    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}

    async def hset(self, key, mapping=None, **kwargs) -> int:
        d = self.h.setdefault(key, {})
        for k, v in (mapping or {}).items():
            d[str(k)] = str(v)
        return len(mapping or {})

    async def hgetall(self, key) -> dict[str, str]:
        return dict(self.h.get(key, {}))


async def test_save_and_load_round_trip():
    store = ChallengerStore(_FakeRedis())
    await store.save_performance(
        "strong_only",
        own_pnls=[1.0, -2.0, 3.0],
        baseline_pnls=[0.5],
        proposal_emitted=True,
    )
    rec = await store.load("strong_only")
    assert rec is not None
    assert rec[FieldName.PNLS] == [1.0, -2.0, 3.0]
    assert rec[FieldName.BASELINE_PNLS] == [0.5]
    assert rec[FieldName.PROPOSAL_EMITTED] is True
    assert rec[FieldName.GRADUATED] is False
    assert rec[FieldName.GRADUATED_AT] is None
    assert rec[FieldName.UPDATED_AT] is not None


async def test_missing_record_is_none():
    store = ChallengerStore(_FakeRedis())
    assert await store.load("never_seen") is None


async def test_graduation_is_independent_of_performance_writes():
    """mark_graduated and save_performance write disjoint fields, so a per-close
    performance write never clears the graduation stamp (and vice versa)."""
    store = ChallengerStore(_FakeRedis())
    await store.save_performance(
        "mean_reversion", own_pnls=[1.0], baseline_pnls=[], proposal_emitted=True
    )
    await store.mark_graduated("mean_reversion")
    rec = await store.load("mean_reversion")
    assert rec is not None
    assert rec[FieldName.GRADUATED] is True
    assert rec[FieldName.GRADUATED_AT] is not None
    # Performance + latch survived the graduation write.
    assert rec[FieldName.PNLS] == [1.0]
    assert rec[FieldName.PROPOSAL_EMITTED] is True

    # A later per-close write must NOT wipe graduation.
    await store.save_performance(
        "mean_reversion", own_pnls=[1.0, 2.0], baseline_pnls=[], proposal_emitted=True
    )
    rec2 = await store.load("mean_reversion")
    assert rec2 is not None
    assert rec2[FieldName.GRADUATED] is True
    assert rec2[FieldName.PNLS] == [1.0, 2.0]


async def test_pnls_are_capped_keeping_the_most_recent():
    store = ChallengerStore(_FakeRedis())
    big = [float(i) for i in range(CHALLENGER_PERF_PNL_CAP + 5)]
    await store.save_performance(
        "strong_only", own_pnls=big, baseline_pnls=[], proposal_emitted=False
    )
    rec = await store.load("strong_only")
    assert rec is not None
    assert len(rec[FieldName.PNLS]) == CHALLENGER_PERF_PNL_CAP
    # The TAIL (most recent) is kept — the last element is preserved.
    assert rec[FieldName.PNLS][-1] == big[-1]


async def test_empty_strategy_is_a_safe_noop():
    store = ChallengerStore(_FakeRedis())
    await store.save_performance("", own_pnls=[1.0], baseline_pnls=[], proposal_emitted=True)
    await store.mark_graduated("")
    assert await store.load("") is None
