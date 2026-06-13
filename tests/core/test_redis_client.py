"""Redis client pool construction — guards the "Too many connections" fix.

The shared async pool must be a BlockingConnectionPool so a request burst WAITS
for a freed connection (up to REDIS_POOL_TIMEOUT_SECONDS) instead of the plain
ConnectionPool's immediate ConnectionError("Too many connections"). The cap must
stay at REDIS_MAX_CONNECTIONS so the Redis plan's client limit is never exceeded.
"""

from __future__ import annotations

import fakeredis
from redis.asyncio import BlockingConnectionPool

import api.redis_client as redis_client_module
from api.config import settings
from api.constants import MAX_CONCURRENT_CHALLENGERS, FieldName
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.redis_client import _build_pool, redis_pool_stats
from api.services.agent_state import AgentStateRegistry
from api.services.agents.pipeline_agents import ChallengerAgent
from api.services.execution.brokers.paper import PaperBroker
from api.startup import _build_agents


def test_build_pool_returns_blocking_pool():
    pool = _build_pool("redis://localhost:6379/0")
    assert isinstance(pool, BlockingConnectionPool), (
        "pool must block (wait) on exhaustion rather than raising 'Too many connections'"
    )


def test_build_pool_respects_max_connections_cap():
    pool = _build_pool("redis://localhost:6379/0")
    assert pool.max_connections == settings.REDIS_MAX_CONNECTIONS


def test_build_pool_sets_wait_timeout():
    pool = _build_pool("redis://localhost:6379/0")
    assert pool.timeout == settings.REDIS_POOL_TIMEOUT_SECONDS
    assert pool.timeout > 0  # a finite wait, not infinite block


# Peak request/response demand the pool must absorb ON TOP of the always-on
# blocking loops: a dashboard refresh fires ~8-10 REST endpoints concurrently,
# plus coinciding per-agent heartbeats, price-poller GETs, RiskGuardian /
# gauge-poller scans, kill-switch / order-lock / control-plane reads, DLQ ops.
_REQUEST_BURST_HEADROOM = 15


def _boot_fleet() -> list:
    """Construct the real boot fleet exactly as the lifespan does (no I/O)."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    bus = EventBus(redis)
    dlq = DLQManager(redis, bus)
    return _build_agents(bus, dlq, redis, AgentStateRegistry(), PaperBroker(redis))


def test_max_connections_covers_worst_case_always_on_consumers():
    """Pool cap must exceed the WORST-CASE always-on blocking-reader count.

    Every agent in the fleet runs one always-on loop that holds a pooled
    connection ~continuously (XREADGROUP BLOCK 100ms, then immediately
    re-acquire). The EventPipeline broadcast consumer and the WebSocket
    broadcaster xread loop add one each. ChallengerSpawner can ADD challengers
    at runtime (approved NEW_AGENT proposals / the dashboard spawn route) up to
    MAX_CONCURRENT_CHALLENGERS, so the worst case is the boot fleet plus the
    remaining spawn capacity — derived here from the same code paths the
    lifespan runs, so adding an agent, a strategy, or raising the challenger
    cap automatically tightens this assertion.

    At a cap of 20 the 14-loop fleet left ~6 connections for ALL
    request/response traffic; a dashboard refresh starved callers past
    REDIS_POOL_TIMEOUT_SECONDS and BlockingConnectionPool.get_connection raised
    ConnectionError("No connection available."), wedging the dashboard. If this
    test fails after you grow the fleet: raise REDIS_MAX_CONNECTIONS and check
    the Redis plan's client limit — never shrink the headroom.
    """
    agents = _boot_fleet()
    challengers_at_boot = sum(isinstance(a, ChallengerAgent) for a in agents)
    runtime_spawnable = max(0, MAX_CONCURRENT_CHALLENGERS - challengers_at_boot)
    # +2: EventPipeline broadcast consumer + WebSocket broadcaster xread loop.
    worst_case_always_on = len(agents) + runtime_spawnable + 2

    assert settings.REDIS_MAX_CONNECTIONS >= worst_case_always_on + _REQUEST_BURST_HEADROOM, (
        f"REDIS_MAX_CONNECTIONS={settings.REDIS_MAX_CONNECTIONS} cannot cover "
        f"{worst_case_always_on} worst-case always-on blocking consumers "
        f"({len(agents)} boot agents + {runtime_spawnable} spawnable challengers "
        f"+ pipeline + broadcaster) plus {_REQUEST_BURST_HEADROOM} request-burst "
        f"headroom — raise the cap (and verify the Redis plan's client limit)"
    )


def test_redis_pool_stats_none_before_pool_exists(monkeypatch):
    monkeypatch.setattr(redis_client_module, "_redis_pool", None)
    assert redis_pool_stats() is None


def test_redis_pool_stats_reports_fresh_pool(monkeypatch):
    pool = _build_pool("redis://localhost:6379/0")
    monkeypatch.setattr(redis_client_module, "_redis_pool", pool)
    stats = redis_pool_stats()
    assert stats == {
        FieldName.MAX_CONNECTIONS: settings.REDIS_MAX_CONNECTIONS,
        FieldName.IN_USE_CONNECTIONS: 0,
        FieldName.IDLE_CONNECTIONS: 0,
        FieldName.SATURATED: False,
    }


def test_redis_pool_stats_depends_on_real_redis_py_internals():
    """Pin the redis-py private attrs redis_pool_stats() reads.

    redis_pool_stats() degrades to zeros when these attrs are missing rather
    than raising — so a redis-py upgrade that renames _in_use_connections /
    _available_connections would silently blind the /health saturation signal.
    This assertion turns that silent regression into a test failure. (Verified
    present on redis-py 5.2.x, the floor we upgraded to off the leaky 5.0.1.)
    """
    pool = _build_pool("redis://localhost:6379/0")
    assert hasattr(pool, "_in_use_connections")
    assert hasattr(pool, "_available_connections")
    assert hasattr(pool, "max_connections")
