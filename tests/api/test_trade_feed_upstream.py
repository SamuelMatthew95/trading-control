"""Tests for the upstream_activity field in the /dashboard/trade-feed endpoint.

When the trade feed is empty (no executed trades in DB), the response must include
an ``upstream_activity`` dict showing pipeline context: signal/decision stream lengths
and the execution engine's last known heartbeat status.
"""
from __future__ import annotations

import json

import pytest

from api.constants import (
    AGENT_EXECUTION,
    REDIS_AGENT_STATUS_KEY,
    STREAM_DECISIONS,
    STREAM_SIGNALS,
    FieldName,
)
from api.in_memory_store import InMemoryStore
from api.routes import dashboard_v2
from api.runtime_state import set_db_available, set_runtime_store


# ---------------------------------------------------------------------------
# Session / DB helpers (mirrors patterns from test_dashboard_v2_resilience.py)
# ---------------------------------------------------------------------------


class _ScalarResult:
    """Result that supports .scalar() — used for COUNT(*) queries."""

    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def all(self):
        return []


class _MultiScalarSession:
    """Session that returns a sequence of scalar values for successive execute() calls."""

    def __init__(self, scalar_values):
        self._values = list(scalar_values)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        if not self._values:
            raise AssertionError("No queued scalar value left for execute()")
        return _ScalarResult(self._values.pop(0))


class _MultiScalarFactory:
    """Factory that returns sessions pre-loaded with scalar results per call."""

    def __init__(self, sessions_scalars):
        # sessions_scalars: list of lists, one inner list per session context
        self._sessions_scalars = list(sessions_scalars)

    def __call__(self):
        if not self._sessions_scalars:
            raise AssertionError("No queued session left for AsyncSessionFactory()")
        return _MultiScalarSession(self._sessions_scalars.pop(0))


class _EmptyRowsSession:
    """Session that always returns empty rows for .all() queries."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        return _EmptyAllResult()


class _EmptyAllResult:
    def all(self):
        return []

    def scalar(self):
        return 0


class _SequencedFactory:
    """Factory that returns sessions from a sequence, each yielding one of:
    - _EmptyAllResult (for main trade_lifecycle / orders queries), or
    - _ScalarResult-emitting session (for the diagnostic COUNT queries).
    """

    def __init__(self, sessions):
        self._sessions = list(sessions)

    def __call__(self):
        if not self._sessions:
            raise AssertionError("No queued session left")
        return self._sessions.pop(0)


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Configurable fake Redis for testing the upstream_activity block."""

    def __init__(self, xlen_map=None, get_map=None):
        # xlen_map: stream_name -> int
        self._xlen_map = xlen_map or {}
        # get_map: key_name -> bytes/str (or None)
        self._get_map = get_map or {}

    async def xlen(self, stream):
        return self._xlen_map.get(stream, 0)

    async def get(self, key):
        return self._get_map.get(key, None)

    async def keys(self, pattern="*"):
        return []


def _enable_db(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "is_db_available", lambda: True)


def _make_empty_db_factory():
    """Return a factory that serves two empty-row sessions (lifecycle + orders)
    then one diagnostic session (order_count=0, lifecycle_count=0)."""
    return _SequencedFactory(
        [
            _EmptyAllSession(),  # trade_lifecycle query → []
            _EmptyAllSession(),  # orders fallback → []
            _MultiScalarSession([0, 0]),  # diag: order_count=0, lifecycle_count=0
        ]
    )


class _EmptyAllSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        return _EmptyAllResult()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trade_feed_empty_includes_upstream_activity_key(monkeypatch):
    """Empty trade feed response must contain an ``upstream_activity`` key."""
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _make_empty_db_factory())

    fake_redis = _FakeRedis()

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)

    payload = await dashboard_v2.get_trade_feed()

    assert payload["count"] == 0
    assert payload["trades"] == []
    assert "upstream_activity" in payload


@pytest.mark.asyncio
async def test_trade_feed_upstream_has_required_fields(monkeypatch):
    """upstream_activity must expose signal_events and decisions_evaluated."""
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _make_empty_db_factory())

    fake_redis = _FakeRedis()

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)

    payload = await dashboard_v2.get_trade_feed()

    upstream = payload["upstream_activity"]
    assert "signal_events" in upstream
    assert "decisions_evaluated" in upstream


@pytest.mark.asyncio
async def test_trade_feed_upstream_shows_stream_lengths(monkeypatch):
    """upstream_activity must reflect the actual stream lengths from Redis."""
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _make_empty_db_factory())

    fake_redis = _FakeRedis(
        xlen_map={
            STREAM_SIGNALS: 5,
            STREAM_DECISIONS: 3,
        }
    )

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)

    payload = await dashboard_v2.get_trade_feed()

    upstream = payload["upstream_activity"]
    assert upstream["signal_events"] == 5
    assert upstream["decisions_evaluated"] == 3


@pytest.mark.asyncio
async def test_trade_feed_upstream_shows_ee_status(monkeypatch):
    """When the execution engine heartbeat is present, ee_last_status must be populated."""
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _make_empty_db_factory())

    ee_heartbeat = json.dumps(
        {
            FieldName.LAST_EVENT: "agent:processing",
            FieldName.EVENT_COUNT: 7,
        }
    ).encode()
    ee_key = REDIS_AGENT_STATUS_KEY.format(name=AGENT_EXECUTION)

    fake_redis = _FakeRedis(get_map={ee_key: ee_heartbeat})

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)

    payload = await dashboard_v2.get_trade_feed()

    upstream = payload["upstream_activity"]
    assert upstream["ee_last_status"] is not None
    assert upstream["ee_last_status"] != ""
    # The value must reflect what the heartbeat reported
    assert "processing" in upstream["ee_last_status"]


@pytest.mark.asyncio
async def test_trade_feed_upstream_ee_status_none_when_no_heartbeat(monkeypatch):
    """When the EE heartbeat key is absent in Redis, ee_last_status should be None."""
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _make_empty_db_factory())

    fake_redis = _FakeRedis()  # no keys set

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)

    payload = await dashboard_v2.get_trade_feed()

    assert payload["upstream_activity"]["ee_last_status"] is None


@pytest.mark.asyncio
async def test_trade_feed_upstream_defaults_to_zero_when_redis_fails(monkeypatch):
    """If Redis is unavailable the upstream_activity block must still be present
    with safe defaults (zeros / None) rather than crashing the endpoint."""
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _make_empty_db_factory())

    async def _failing_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(dashboard_v2, "get_redis", _failing_redis)

    payload = await dashboard_v2.get_trade_feed()

    assert payload["count"] == 0
    upstream = payload["upstream_activity"]
    assert upstream["signal_events"] == 0
    assert upstream["decisions_evaluated"] == 0
    assert upstream["ee_last_status"] is None


@pytest.mark.asyncio
async def test_trade_feed_upstream_not_present_when_trades_exist(monkeypatch):
    """upstream_activity must NOT appear in the response when there are actual trades
    — it is diagnostic metadata for the empty-state only."""
    _enable_db(monkeypatch)

    # Serve one trade_lifecycle row so the endpoint returns a non-empty payload
    class _OneTradeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, *_args, **_kwargs):
            return _TradeResult()

    class _TradeResult:
        def all(self):
            # (id, symbol, side, qty, entry_price, exit_price, pnl, pnl_pct,
            #  order_id, exec_trace, sig_trace, grade, grade_score, grade_label,
            #  status, filled_at, graded_at, reflected_at, created_at, session_id)
            from datetime import datetime, timezone

            ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
            return [
                (
                    "trade-1",
                    "BTC/USD",
                    "buy",
                    0.1,
                    50000.0,
                    None,
                    None,
                    None,
                    "ord-1",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "filled",
                    ts,
                    None,
                    None,
                    ts,
                    None,
                )
            ]

    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: _OneTradeSession())

    payload = await dashboard_v2.get_trade_feed()

    assert payload["count"] == 1
    assert "upstream_activity" not in payload


@pytest.mark.asyncio
async def test_trade_feed_empty_reason_present_alongside_upstream_activity(monkeypatch):
    """empty_reason must be included in the same response as upstream_activity."""
    _enable_db(monkeypatch)
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _make_empty_db_factory())

    fake_redis = _FakeRedis()

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)

    payload = await dashboard_v2.get_trade_feed()

    assert "empty_reason" in payload
    assert payload["empty_reason"]  # non-empty string
    assert "upstream_activity" in payload
