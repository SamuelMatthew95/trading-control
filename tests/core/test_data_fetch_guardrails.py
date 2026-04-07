"""Guardrail tests for the full data-fetch pipeline.

These tests verify WHAT data is fetched, FROM WHERE (which table / Redis key),
and THAT the data reaches the API response in the expected shape.

Pipeline:
  PostgreSQL tables ──► MetricsAggregator.get_raw_snapshot()
                    ──► /dashboard/state (REST hydration)
                    ──► hydrateDashboard (frontend store)

Redis keys ──► agent:status:{AGENT_NAME} ──► /dashboard/state agent_statuses
           ──► alpha:ic_weights          ──► /dashboard/state ic_weights
           ──► prices:{symbol}           ──► /dashboard/state prices
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.constants import (
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_NOTIFICATION,
    AGENT_REASONING,
    AGENT_REFLECTION,
    AGENT_SIGNAL,
    AGENT_STRATEGY_PROPOSER,
    ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
)
from api.routes import dashboard_v2
from api.services.metrics_aggregator import MetricsAggregator

# ---------------------------------------------------------------------------
# Helpers — lightweight in-memory session / result fakes
# ---------------------------------------------------------------------------


class _Row:
    """Attribute-accessible row returned by fake execute()."""

    def __init__(self, **kwargs: Any):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, idx: int) -> Any:
        return list(self.__dict__.values())[idx]


class _IterableResult:
    """Fake SQLAlchemy result: supports direct iteration, .scalars(), .fetchall(), .all()."""

    def __init__(self, rows: list[Any]):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def all(self) -> list[Any]:
        return self._rows

    def fetchall(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _IterableResult:
        return self


class _FakeSession:
    """Fake async SQLAlchemy session that returns queued results in order."""

    def __init__(self, queued: list[list[Any]]):
        self._queued = list(queued)

    async def execute(self, *_args: Any, **_kwargs: Any) -> _IterableResult:
        if not self._queued:
            return _IterableResult([])
        return _IterableResult(self._queued.pop(0))


class _FakeAggregator:
    """Minimal stand-in for MetricsAggregator used in route tests."""

    def __init__(self, snapshot: dict[str, Any]):
        self._snapshot = snapshot

    async def get_raw_snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)


# ---------------------------------------------------------------------------
# MetricsAggregator.get_raw_snapshot — table-level guardrails
# ---------------------------------------------------------------------------


class TestRawSnapshotDataSources:
    """Verify that get_raw_snapshot() pulls data from the correct tables."""

    @pytest.mark.asyncio
    async def test_learning_events_come_from_agent_grades(self) -> None:
        """agent_grades rows must appear as learning_events."""
        ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        grade_row = [
            "trace-abc",  # trace_id
            "accuracy",  # grade_type
            0.85,  # score
            {"signal_type": "STRONG_MOMENTUM"},  # metrics
            ts,  # created_at
        ]
        # get_raw_snapshot calls execute() many times (orders, positions,
        # column introspection, agent_logs, agent_grades, proposals,
        # trade_lifecycle). We fill all queues with empty results except
        # agent_grades.
        session = _FakeSession(
            [
                [],  # orders (scalars().all())
                [],  # positions (scalars().all())
                [
                    _Row(column_name="id", udt_name="uuid"),
                    _Row(column_name="trace_id", udt_name="text"),
                    _Row(column_name="source", udt_name="text"),
                    _Row(column_name="created_at", udt_name="timestamptz"),
                ],  # column introspection
                [],  # agent_logs
                [grade_row],  # agent_grades  <-- the row we care about
                [],  # proposals
                [],  # trade_lifecycle
            ]
        )

        agg = MetricsAggregator(session)
        result = await agg.get_raw_snapshot()

        assert "learning_events" in result
        assert len(result["learning_events"]) == 1
        ev = result["learning_events"][0]
        assert ev["grade_type"] == "accuracy"
        assert ev["score"] == 0.85
        assert ev["score_pct"] == 85.0
        assert ev["metrics"] == {"signal_type": "STRONG_MOMENTUM"}

    @pytest.mark.asyncio
    async def test_proposals_come_from_agent_logs_with_log_type_proposal(self) -> None:
        """agent_logs rows where log_type='proposal' must appear as proposals."""
        ts = datetime(2025, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
        proposal_payload = {
            "proposal_type": "position_sizing",
            "content": "Reduce max position to 3%",
            "requires_approval": True,
            "confidence": 0.78,
            "status": "pending",
        }
        proposal_row = ["trace-prop", proposal_payload, ts]

        session = _FakeSession(
            [
                [],  # orders
                [],  # positions
                [
                    _Row(column_name="id", udt_name="uuid"),
                    _Row(column_name="trace_id", udt_name="text"),
                    _Row(column_name="source", udt_name="text"),
                    _Row(column_name="log_type", udt_name="text"),  # required for proposals guard
                    _Row(column_name="payload", udt_name="jsonb"),  # required for proposals guard
                    _Row(column_name="created_at", udt_name="timestamptz"),
                ],
                [],  # agent_logs (general)
                [],  # agent_grades
                [proposal_row],  # proposals from agent_logs WHERE log_type='proposal'
                [],  # trade_lifecycle
            ]
        )

        agg = MetricsAggregator(session)
        result = await agg.get_raw_snapshot()

        assert "proposals" in result
        assert len(result["proposals"]) == 1
        p = result["proposals"][0]
        assert p["proposal_type"] == "position_sizing"
        assert p["content"] == "Reduce max position to 3%"
        assert p["confidence"] == 0.78
        assert p["status"] == "pending"

    @pytest.mark.asyncio
    async def test_trade_feed_comes_from_trade_lifecycle(self) -> None:
        """trade_lifecycle rows must appear as trade_feed."""
        ts = datetime(2025, 1, 3, 0, 0, 0, tzinfo=timezone.utc)
        trade_row = [
            "trade-id-1",  # id
            "BTC/USD",  # symbol
            "buy",  # side
            0.05,  # qty
            43000.0,  # entry_price
            44000.0,  # exit_price
            50.0,  # pnl
            2.3,  # pnl_percent
            "A",  # grade
            0.9,  # grade_score
            "excellent",  # grade_label
            "filled",  # status
            ts,  # filled_at
            ts,  # graded_at
            "exec-trace",  # execution_trace_id
            "sig-trace",  # signal_trace_id
            "order-1",  # order_id
            ts,  # created_at
        ]

        # No log_type in columns → proposals guard skips execute(), no proposals slot needed
        session = _FakeSession(
            [
                [],  # orders
                [],  # positions
                [
                    _Row(column_name="id", udt_name="uuid"),
                    _Row(column_name="trace_id", udt_name="text"),
                    _Row(column_name="source", udt_name="text"),
                    _Row(column_name="created_at", udt_name="timestamptz"),
                ],
                [],  # agent_logs
                [],  # agent_grades
                # proposals: skipped (no log_type column) — no queue slot consumed
                [trade_row],  # trade_lifecycle  <-- the row we care about
            ]
        )

        agg = MetricsAggregator(session)
        result = await agg.get_raw_snapshot()

        assert "trade_feed" in result
        assert len(result["trade_feed"]) == 1
        t = result["trade_feed"][0]
        assert t["id"] == "trade-id-1"
        assert t["symbol"] == "BTC/USD"
        assert t["side"] == "buy"
        assert t["pnl"] == 50.0
        assert t["grade"] == "A"
        assert t["execution_trace_id"] == "exec-trace"
        assert t["signal_trace_id"] == "sig-trace"

    @pytest.mark.asyncio
    async def test_raw_snapshot_returns_required_keys(self) -> None:
        """get_raw_snapshot() must always return the keys the frontend expects."""
        session = _FakeSession(
            [
                [],
                [],
                [
                    _Row(column_name="id", udt_name="uuid"),
                    _Row(column_name="created_at", udt_name="timestamptz"),
                ],
                [],
                [],
                [],
                [],
            ]
        )
        agg = MetricsAggregator(session)
        result = await agg.get_raw_snapshot()

        required_keys = {
            "orders",
            "positions",
            "agent_logs",
            "learning_events",
            "proposals",
            "trade_feed",
            "signals",
            "risk_alerts",
            "timestamp",
        }
        assert required_keys.issubset(result.keys()), (
            f"Missing keys: {required_keys - result.keys()}"
        )

    @pytest.mark.asyncio
    async def test_raw_snapshot_falls_back_gracefully_when_db_explodes(self) -> None:
        """If all DB queries fail, get_raw_snapshot() must return empty-list fallback."""

        class _BrokenSession:
            async def execute(self, *a: Any, **kw: Any) -> None:
                raise RuntimeError("db offline")

            def scalars(self) -> _BrokenSession:
                return self

        agg = MetricsAggregator(_BrokenSession())  # type: ignore[arg-type]
        result = await agg.get_raw_snapshot()

        # Must never raise; must contain all keys as empty lists
        for key in (
            "orders",
            "positions",
            "agent_logs",
            "learning_events",
            "proposals",
            "trade_feed",
            "signals",
            "risk_alerts",
        ):
            assert result[key] == [], f"Expected empty list for {key!r}"

    @pytest.mark.asyncio
    async def test_proposals_with_stringified_json_payload(self) -> None:
        """Proposals stored as JSON strings must be decoded correctly."""
        ts = datetime(2025, 1, 4, 0, 0, 0, tzinfo=timezone.utc)
        stringified = json.dumps(
            {
                "proposal_type": "risk_limit",
                "content": "Lower daily drawdown cap",
                "status": "approved",
                "confidence": 0.91,
            }
        )
        proposal_row = ["trace-str", stringified, ts]

        session = _FakeSession(
            [
                [],
                [],
                [
                    _Row(column_name="id", udt_name="uuid"),
                    _Row(column_name="log_type", udt_name="text"),  # guard requires this
                    _Row(column_name="payload", udt_name="jsonb"),  # guard requires this
                    _Row(column_name="created_at", udt_name="timestamptz"),
                ],
                [],
                [],
                [proposal_row],
                [],
            ]
        )
        agg = MetricsAggregator(session)
        result = await agg.get_raw_snapshot()

        p = result["proposals"][0]
        assert p["proposal_type"] == "risk_limit"
        assert p["status"] == "approved"
        assert p["confidence"] == 0.91


# ---------------------------------------------------------------------------
# /dashboard/state — Redis key guardrails
# ---------------------------------------------------------------------------


class TestDashboardStateRedisKeys:
    """Verify that /dashboard/state reads the correct Redis keys."""

    @staticmethod
    def _make_redis(agent_statuses: dict[str, bytes | None] | None = None) -> AsyncMock:
        """Build a minimal fake Redis client for dashboard/state tests."""
        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None] * len(ALL_AGENT_NAMES))
        redis.get = AsyncMock(return_value=None)
        if agent_statuses is not None:
            ordered_values = [
                agent_statuses.get(REDIS_AGENT_STATUS_KEY.format(name=n)) for n in ALL_AGENT_NAMES
            ]
            redis.mget = AsyncMock(return_value=ordered_values)
        return redis

    @pytest.mark.asyncio
    async def test_agent_statuses_use_screaming_snake_case_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Redis must be queried with SCREAMING_SNAKE_CASE agent names, not PascalCase."""
        captured_keys: list[list[str]] = []

        async def fake_mget(keys: list[str]) -> list[None]:
            captured_keys.append(list(keys))
            return [None] * len(keys)

        redis = AsyncMock()
        redis.mget = fake_mget
        redis.get = AsyncMock(return_value=None)

        monkeypatch.setattr(dashboard_v2, "get_redis", AsyncMock(return_value=redis))

        snapshot = {
            "orders": [],
            "positions": [],
            "agent_logs": [],
            "learning_events": [],
            "proposals": [],
            "trade_feed": [],
            "signals": [],
            "risk_alerts": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        fake_session_ctx = MagicMock()
        fake_session_ctx.__aenter__ = AsyncMock(return_value=fake_session_ctx)
        fake_session_ctx.__aexit__ = AsyncMock(return_value=False)

        class _FakeMagg:
            def __init__(self, _session: Any):
                pass

            async def get_raw_snapshot(self) -> dict[str, Any]:
                return dict(snapshot)

        monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FakeMagg)
        monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: fake_session_ctx)

        await dashboard_v2.get_dashboard_state()

        assert captured_keys, "mget was never called"
        # The route calls mget twice: once for prices, once for agent statuses.
        # Find the call that contains agent:status: keys.
        agent_mget_call = next(
            (call for call in captured_keys if any(k.startswith("agent:status:") for k in call)),
            None,
        )
        assert agent_mget_call is not None, (
            f"No mget call contained 'agent:status:' keys — all mget calls were: {captured_keys}"
        )
        # Every key in the agent call must match the pattern
        for key in agent_mget_call:
            assert key.startswith("agent:status:"), f"Unexpected key format: {key!r}"
        # All expected agent keys must be present
        expected_keys = {REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES}
        assert set(agent_mget_call) == expected_keys

    @pytest.mark.asyncio
    async def test_agent_status_online_agents_parsed_correctly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Agents with heartbeat data in Redis must appear as ACTIVE."""
        heartbeat = json.dumps(
            {
                "status": "ACTIVE",
                "last_event": "STRONG_MOMENTUM BTC/USD +3.50%",
                "event_count": 42,
                "last_seen": 1700000000,
            }
        ).encode()

        # Only SIGNAL_AGENT has a heartbeat
        signal_key = REDIS_AGENT_STATUS_KEY.format(name=AGENT_SIGNAL)
        ordered_values = [
            heartbeat if REDIS_AGENT_STATUS_KEY.format(name=n) == signal_key else None
            for n in ALL_AGENT_NAMES
        ]

        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=ordered_values)
        redis.get = AsyncMock(return_value=None)
        monkeypatch.setattr(dashboard_v2, "get_redis", AsyncMock(return_value=redis))

        snapshot = {
            "orders": [],
            "positions": [],
            "agent_logs": [],
            "learning_events": [],
            "proposals": [],
            "trade_feed": [],
            "signals": [],
            "risk_alerts": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        class _FakeMagg:
            def __init__(self, _s: Any):
                pass

            async def get_raw_snapshot(self) -> dict[str, Any]:
                return dict(snapshot)

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = AsyncMock(return_value=fake_ctx)
        fake_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FakeMagg)
        monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: fake_ctx)

        result = await dashboard_v2.get_dashboard_state()

        statuses = {s["name"]: s for s in result["agent_statuses"]}
        assert statuses[AGENT_SIGNAL]["status"] == "ACTIVE"
        assert statuses[AGENT_SIGNAL]["event_count"] == 42

        # All other agents must be offline
        for name in ALL_AGENT_NAMES:
            if name != AGENT_SIGNAL:
                assert statuses[name]["status"] == "offline", (
                    f"{name} should be offline, got {statuses[name]['status']!r}"
                )

    @pytest.mark.asyncio
    async def test_agent_statuses_include_all_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """agent_statuses must contain an entry for every agent in ALL_AGENT_NAMES."""
        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None] * len(ALL_AGENT_NAMES))
        redis.get = AsyncMock(return_value=None)
        monkeypatch.setattr(dashboard_v2, "get_redis", AsyncMock(return_value=redis))

        snapshot = {
            "orders": [],
            "positions": [],
            "agent_logs": [],
            "learning_events": [],
            "proposals": [],
            "trade_feed": [],
            "signals": [],
            "risk_alerts": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        class _FakeMagg:
            def __init__(self, _s: Any):
                pass

            async def get_raw_snapshot(self) -> dict[str, Any]:
                return dict(snapshot)

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = AsyncMock(return_value=fake_ctx)
        fake_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FakeMagg)
        monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: fake_ctx)

        result = await dashboard_v2.get_dashboard_state()
        names_in_response = {s["name"] for s in result["agent_statuses"]}
        assert names_in_response == set(ALL_AGENT_NAMES)

    @pytest.mark.asyncio
    async def test_ic_weights_read_from_alpha_ic_weights_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IC weights must be read from 'alpha:ic_weights' Redis key."""
        captured_gets: list[str] = []

        async def fake_get(key: str) -> bytes | None:
            captured_gets.append(key)
            if key == "alpha:ic_weights":
                return json.dumps({"momentum": 0.4, "mean_reversion": 0.6}).encode()
            return None

        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None] * len(ALL_AGENT_NAMES))
        redis.get = fake_get
        monkeypatch.setattr(dashboard_v2, "get_redis", AsyncMock(return_value=redis))

        snapshot = {
            "orders": [],
            "positions": [],
            "agent_logs": [],
            "learning_events": [],
            "proposals": [],
            "trade_feed": [],
            "signals": [],
            "risk_alerts": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        class _FakeMagg:
            def __init__(self, _s: Any):
                pass

            async def get_raw_snapshot(self) -> dict[str, Any]:
                return dict(snapshot)

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = AsyncMock(return_value=fake_ctx)
        fake_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FakeMagg)
        monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: fake_ctx)

        result = await dashboard_v2.get_dashboard_state()

        assert "alpha:ic_weights" in captured_gets, "Expected get('alpha:ic_weights') to be called"
        assert result.get("ic_weights") == {"momentum": 0.4, "mean_reversion": 0.6}

    def test_redis_key_format_matches_agent_writes(self) -> None:
        """
        The keys the dashboard builds must exactly match what agents write.

        Agents write:  REDIS_AGENT_STATUS_KEY.format(name=AGENT_NAME)
        Dashboard reads: REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES
        These must be identical.
        """
        agent_write_keys = {
            REDIS_AGENT_STATUS_KEY.format(name=name)
            for name in [
                AGENT_SIGNAL,
                AGENT_REASONING,
                AGENT_EXECUTION,
                AGENT_GRADE,
                AGENT_IC_UPDATER,
                AGENT_REFLECTION,
                AGENT_STRATEGY_PROPOSER,
                AGENT_NOTIFICATION,
            ]
        }
        dashboard_read_keys = {REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES}
        assert agent_write_keys == dashboard_read_keys, (
            f"Key mismatch — agents write: {agent_write_keys - dashboard_read_keys}, "
            f"dashboard reads extra: {dashboard_read_keys - agent_write_keys}"
        )

    def test_no_pascal_case_agent_names_in_redis_keys(self) -> None:
        """Ensure no PascalCase names slip into Redis key generation (the original bug)."""
        pascal_names = {
            "SignalGenerator",
            "ReasoningAgent",
            "ExecutionEngine",
            "GradeAgent",
            "ICUpdater",
            "ReflectionAgent",
            "StrategyProposer",
            "NotificationAgent",
        }
        for name in ALL_AGENT_NAMES:
            assert name not in pascal_names, (
                f"Found PascalCase name {name!r} in ALL_AGENT_NAMES — "
                "this would cause dashboard to always show agents as offline"
            )
        # Also verify keys never contain PascalCase segment
        for name in ALL_AGENT_NAMES:
            key = REDIS_AGENT_STATUS_KEY.format(name=name)
            for pascal in pascal_names:
                assert pascal not in key, (
                    f"Redis key {key!r} contains PascalCase segment {pascal!r}"
                )


# ---------------------------------------------------------------------------
# Data-flow shape guardrails
# ---------------------------------------------------------------------------


class TestDashboardStateResponseShape:
    """Verify the response shape that the frontend hydrateDashboard expects."""

    @pytest.mark.asyncio
    async def test_response_contains_all_hydration_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The REST hydration response must include all keys used by the frontend."""
        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None] * len(ALL_AGENT_NAMES))
        redis.get = AsyncMock(return_value=None)
        monkeypatch.setattr(dashboard_v2, "get_redis", AsyncMock(return_value=redis))

        snapshot = {
            "orders": [{"order_id": "o1", "symbol": "AAPL"}],
            "positions": [{"symbol": "AAPL", "side": "long"}],
            "agent_logs": [{"id": "l1", "message": "ok"}],
            "learning_events": [{"id": "g1", "score": 0.8}],
            "proposals": [{"id": "p1", "proposal_type": "risk_limit"}],
            "trade_feed": [{"id": "t1", "symbol": "BTC/USD"}],
            "signals": [],
            "risk_alerts": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        class _FakeMagg:
            def __init__(self, _s: Any):
                pass

            async def get_raw_snapshot(self) -> dict[str, Any]:
                return dict(snapshot)

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = AsyncMock(return_value=fake_ctx)
        fake_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FakeMagg)
        monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: fake_ctx)

        result = await dashboard_v2.get_dashboard_state()

        frontend_required_keys = {
            "orders",
            "positions",
            "agent_logs",
            "learning_events",
            "proposals",
            "trade_feed",
            "agent_statuses",
            "timestamp",
        }
        missing = frontend_required_keys - result.keys()
        assert not missing, f"Response missing keys required by frontend: {missing}"

    @pytest.mark.asyncio
    async def test_orders_list_preserved_in_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """orders[] from get_raw_snapshot() must pass through unchanged."""
        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None] * len(ALL_AGENT_NAMES))
        redis.get = AsyncMock(return_value=None)
        monkeypatch.setattr(dashboard_v2, "get_redis", AsyncMock(return_value=redis))

        order_data = [{"order_id": "x1", "symbol": "TSLA", "side": "buy"}]
        snapshot = {
            "orders": order_data,
            "positions": [],
            "agent_logs": [],
            "learning_events": [],
            "proposals": [],
            "trade_feed": [],
            "signals": [],
            "risk_alerts": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        class _FakeMagg:
            def __init__(self, _s: Any):
                pass

            async def get_raw_snapshot(self) -> dict[str, Any]:
                return dict(snapshot)

        fake_ctx = MagicMock()
        fake_ctx.__aenter__ = AsyncMock(return_value=fake_ctx)
        fake_ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(dashboard_v2, "MetricsAggregator", _FakeMagg)
        monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", lambda: fake_ctx)

        result = await dashboard_v2.get_dashboard_state()
        assert result["orders"] == order_data
