"""Guardrails for proposal creation: dedup + daily cap (Redis-backed).

Covers api/services/agents/proposal_guardrails.py. Lives in tests/core so CI
runs it (tests/agents is local-only).
"""

import fakeredis.aioredis
import pytest

from api.config import settings
from api.constants import FieldName, ProposalType
from api.services.agents.proposal_guardrails import (
    proposal_dedup_key,
    register_proposal_creation,
)


def _proposal(content=None, ptype=ProposalType.PARAMETER_CHANGE):
    return {
        FieldName.PROPOSAL_TYPE: ptype,
        FieldName.CONTENT: content if content is not None else {"rule": "lower_rsi", "value": 25},
    }


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class TestProposalDedupKey:
    def test_same_type_and_content_yield_same_key(self):
        # Key order in the content dict must not change the fingerprint.
        a = _proposal({"rule": "x", "v": 1})
        b = _proposal({"v": 1, "rule": "x"})
        assert proposal_dedup_key(a) == proposal_dedup_key(b)

    def test_different_content_differs(self):
        assert proposal_dedup_key(_proposal({"v": 1})) != proposal_dedup_key(_proposal({"v": 2}))

    def test_different_type_differs(self):
        a = _proposal({"v": 1}, ProposalType.PARAMETER_CHANGE)
        b = _proposal({"v": 1}, ProposalType.PROMPT_EVOLUTION)
        assert proposal_dedup_key(a) != proposal_dedup_key(b)

    def test_unserializable_content_does_not_raise(self):
        assert proposal_dedup_key({FieldName.CONTENT: {1, 2, 3}})  # set is not JSON


class TestRegisterProposalCreation:
    async def test_allows_first_unique_proposal(self, redis):
        assert await register_proposal_creation(redis, _proposal()) is True

    async def test_rejects_duplicate_same_day(self, redis):
        proposal = _proposal()
        assert await register_proposal_creation(redis, proposal) is True
        assert await register_proposal_creation(redis, proposal) is False

    async def test_distinct_proposals_both_allowed(self, redis):
        assert await register_proposal_creation(redis, _proposal({"v": 1})) is True
        assert await register_proposal_creation(redis, _proposal({"v": 2})) is True

    async def test_enforces_daily_cap(self, redis, monkeypatch):
        monkeypatch.setattr(settings, "MAX_PROPOSALS_PER_DAY", 3)
        for i in range(3):
            assert await register_proposal_creation(redis, _proposal({"v": i})) is True
        assert await register_proposal_creation(redis, _proposal({"v": 99})) is False

    async def test_duplicates_do_not_consume_cap(self, redis, monkeypatch):
        monkeypatch.setattr(settings, "MAX_PROPOSALS_PER_DAY", 2)
        proposal = _proposal({"v": 1})
        assert await register_proposal_creation(redis, proposal) is True
        # Repeats are rejected as duplicates and must NOT spend cap budget...
        assert await register_proposal_creation(redis, proposal) is False
        assert await register_proposal_creation(redis, proposal) is False
        # ...so a second distinct proposal still fits under the cap of 2.
        assert await register_proposal_creation(redis, _proposal({"v": 2})) is True

    async def test_cap_zero_disables_guardrail(self, redis, monkeypatch):
        monkeypatch.setattr(settings, "MAX_PROPOSALS_PER_DAY", 0)
        proposal = _proposal()
        assert await register_proposal_creation(redis, proposal) is True
        assert await register_proposal_creation(redis, proposal) is True  # no dedup when off

    async def test_fails_open_when_redis_is_none(self):
        assert await register_proposal_creation(None, _proposal()) is True

    async def test_sets_ttl_so_counters_self_clean(self, redis, monkeypatch):
        monkeypatch.setattr(settings, "MAX_PROPOSALS_PER_DAY", 5)
        await register_proposal_creation(redis, _proposal())
        keys = await redis.keys("proposals:*")
        assert keys
        for key in keys:
            assert await redis.ttl(key) > 0
