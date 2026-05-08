"""Tests for /learning/* endpoints — covers memory path, grade_history fallback, and DB path."""

from __future__ import annotations

import time
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName
from api.in_memory_store import InMemoryStore
from api.main import app
from api.routes import learning as learning_module
from api.routes.learning import _grade_from_score, _grade_record_to_trade, _mem_grades_as_trades
from api.runtime_state import set_db_available, set_runtime_store


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_grade_from_score_boundaries():
    assert _grade_from_score(0.95) == "A"
    assert _grade_from_score(0.90) == "A"
    assert _grade_from_score(0.89) == "B"
    assert _grade_from_score(0.75) == "B"
    assert _grade_from_score(0.74) == "C"
    assert _grade_from_score(0.60) == "C"
    assert _grade_from_score(0.59) == "D"
    assert _grade_from_score(0.40) == "D"
    assert _grade_from_score(0.39) == "F"
    assert _grade_from_score(0.0) == "F"


def test_grade_record_to_trade_shape():
    trade = _grade_record_to_trade(score=0.80, trade_id="abc-123", created_at=None)
    assert trade[FieldName.TRADE_EVAL_ID] == "abc-123"
    assert trade[FieldName.OVERALL_SCORE] == 0.80
    assert trade[FieldName.GRADE] == "B"
    assert trade[FieldName.MISTAKES] == []
    assert trade[FieldName.STRENGTHS] == []
    assert trade["created_at"] is None
    # Optional fields are null
    assert trade[FieldName.SYMBOL] is None
    assert trade[FieldName.PNL] is None


def test_grade_record_to_trade_none_score():
    trade = _grade_record_to_trade(score=None, trade_id="x", created_at=None)
    assert trade[FieldName.OVERALL_SCORE] is None
    assert trade[FieldName.GRADE] is None


def test_mem_grades_as_trades_empty_store():
    store = InMemoryStore()
    trades, total = _mem_grades_as_trades(store, limit=10, offset=0)
    assert trades == []
    assert total == 0


def test_mem_grades_as_trades_uses_grade_history():
    store = InMemoryStore()
    store.add_grade({"trace_id": "t1", "score": 0.85, "timestamp": time.time()})
    store.add_grade({"trace_id": "t2", "score": 0.50, "timestamp": time.time()})

    trades, total = _mem_grades_as_trades(store, limit=10, offset=0)
    assert total == 2
    assert len(trades) == 2
    # Most recent first (get_grades returns reversed)
    assert trades[0][FieldName.TRADE_EVAL_ID] == "t2"
    assert trades[1][FieldName.TRADE_EVAL_ID] == "t1"


def test_mem_grades_as_trades_pagination():
    store = InMemoryStore()
    for i in range(5):
        store.add_grade({"trace_id": f"t{i}", "score": 0.7, "timestamp": time.time()})

    trades, total = _mem_grades_as_trades(store, limit=2, offset=2)
    assert total == 5
    assert len(trades) == 2


def test_mem_grades_as_trades_score_pct_fallback():
    store = InMemoryStore()
    # score_pct field (0-100 range) with no score field
    store.add_grade({"trace_id": "t1", "score_pct": 75, "timestamp": time.time()})

    trades, total = _mem_grades_as_trades(store, limit=10, offset=0)
    assert total == 1
    assert trades[0][FieldName.OVERALL_SCORE] == pytest.approx(0.75, rel=1e-3)


# ---------------------------------------------------------------------------
# GET /learning/trades — memory path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_db_down_with_trade_evaluations(client):
    store = InMemoryStore()
    store.add_trade_evaluation(
        {
            FieldName.TRADE_EVAL_ID: "eval-1",
            FieldName.OVERALL_SCORE: 0.9,
            FieldName.GRADE: "A",
            "created_at": time.time(),
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    assert data["total"] == 1
    assert data["trades"][0][FieldName.TRADE_EVAL_ID] == "eval-1"


@pytest.mark.asyncio
async def test_list_trades_db_down_grade_history_when_no_evals(client):
    store = InMemoryStore()
    # DB is down. GradeAgent ran and wrote to grade_history. No trade_evaluations yet.
    store.add_grade({"trace_id": "grade-1", "score": 0.80, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    assert data["total"] == 1
    assert data["trades"][0][FieldName.TRADE_EVAL_ID] == "grade-1"
    assert data["trades"][0][FieldName.GRADE] == "B"


@pytest.mark.asyncio
async def test_list_trades_db_down_empty_store(client):
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trades"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_trades_db_down_pagination(client):
    store = InMemoryStore()
    for i in range(5):
        store.add_grade({"trace_id": f"g{i}", "score": 0.7, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades?limit=2&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) == 2
    assert data["total"] == 5


# ---------------------------------------------------------------------------
# GET /learning/metrics — memory path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_db_down_with_trade_evaluations(client):
    store = InMemoryStore()
    store.add_trade_evaluation(
        {
            FieldName.PNL: 100.0,
            FieldName.PNL_PERCENT: 2.0,
            FieldName.OVERALL_SCORE: 0.85,
            FieldName.GRADE: "B",
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    assert "avg_score" in data


@pytest.mark.asyncio
async def test_metrics_db_down_grade_history_when_no_evals(client):
    store = InMemoryStore()
    store.add_grade({"trace_id": "g1", "score": 0.80, "timestamp": time.time()})
    store.add_grade({"trace_id": "g2", "score": 0.60, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    # Metrics should be computed from the 2 grade records
    assert "avg_score" in data


@pytest.mark.asyncio
async def test_metrics_db_down_empty_store(client):
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"


# ---------------------------------------------------------------------------
# GET /learning/pipeline-status — memory path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_status_db_down_with_trade_evaluations(client):
    store = InMemoryStore()
    store.add_trade_evaluation({"created_at": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/pipeline-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    assert data["stages"]["scoring"]["status"] == "active"
    assert data["stages"]["scoring"]["jobs_processed"] == 1


@pytest.mark.asyncio
async def test_pipeline_status_db_down_grade_history_when_no_evals(client):
    store = InMemoryStore()
    # DB is down. GradeAgent ran (grade_history has data). No trade_evaluations yet.
    store.add_grade({"trace_id": "g1", "score": 0.7, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/pipeline-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stages"]["scoring"]["status"] == "active"
    assert data["stages"]["scoring"]["jobs_processed"] == 1


@pytest.mark.asyncio
async def test_pipeline_status_db_down_all_idle_when_empty(client):
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/pipeline-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stages"]["scoring"]["status"] == "idle"
    assert data["stages"]["reflection"]["status"] == "idle"
    assert data["stages"]["strategy_proposer"]["status"] == "idle"


# ---------------------------------------------------------------------------
# GET /learning/reflections and /learning/strategies — memory path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflections_db_down_empty(client):
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/reflections")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reflections"] == []
    assert data["mode"] == "memory"


@pytest.mark.asyncio
async def test_reflections_db_down_with_data(client):
    store = InMemoryStore()
    store.add_reflection(
        {
            FieldName.PATTERNS: ["momentum works in trending markets"],
            FieldName.WIN_RATE: 0.65,
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/reflections")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["reflections"]) == 1
    assert data["reflections"][0][FieldName.WIN_RATE] == 0.65


@pytest.mark.asyncio
async def test_strategies_db_down_empty(client):
    store = InMemoryStore()
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategies"] == []
    assert data["mode"] == "memory"


@pytest.mark.asyncio
async def test_strategies_db_down_with_data(client):
    store = InMemoryStore()
    store.add_strategy(
        {
            FieldName.STATUS: "proposed",
            FieldName.EXPECTED_IMPROVEMENT: 0.05,
            "description": "Use RSI divergence",
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["strategies"]) == 1
    assert data["strategies"][0][FieldName.STATUS] == "proposed"


# ---------------------------------------------------------------------------
# DB path — mocked session
# ---------------------------------------------------------------------------


def _mock_session_factory(monkeypatch, row_factory: Any) -> None:
    """Patch AsyncSessionFactory so the DB path returns controlled rows."""

    class _MockResult:
        def __init__(self, rows):
            self._rows = rows

        def scalar(self):
            return self._rows[0][0] if self._rows else 0

        def first(self):
            return self._rows[0] if self._rows else None

        def all(self):
            return self._rows

    class _MockSession:
        def __init__(self):
            self._call_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, stmt, *args, **kwargs):
            return _MockResult(row_factory(self._call_count, stmt, args))

    class _MockFactory:
        def __call__(self):
            return _MockSession()

    monkeypatch.setattr(learning_module, "is_db_available", lambda: True)
    import api.routes.learning as _lr

    _lr.AsyncSessionFactory = _MockFactory()


@pytest.mark.asyncio
async def test_list_trades_db_empty_falls_back_to_agent_grades(client, monkeypatch):
    """When trade_evaluations is empty, DB path bridges to agent_grades."""

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalar(self):
            return self._rows[0][0] if self._rows else None

        def first(self):
            return self._rows[0] if self._rows else None

        def all(self):
            return self._rows

    class _Session:
        _call: int = 0

        async def __aenter__(self):
            _Session._call = 0
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, stmt, *params):
            sql = str(stmt)
            _Session._call += 1
            if "COUNT" in sql and "trade_evaluations" in sql:
                return _Result([(0,)])
            if "COUNT" in sql and "agent_grades" in sql:
                return _Result([(2,)])
            if "agent_grades" in sql:
                return _Result([("trace-1", 0.85, None), ("trace-2", 0.60, None)])
            return _Result([])

    class _Fac:
        def __call__(self):
            return _Session()

    # Patch the module-level is_db_available AND the lazily-imported AsyncSessionFactory
    monkeypatch.setattr(learning_module, "is_db_available", lambda: True)
    import api.database as _db_mod

    monkeypatch.setattr(_db_mod, "AsyncSessionFactory", _Fac())

    resp = await client.get("/learning/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "db"
    assert data["total"] == 2
    assert data["trades"][0][FieldName.TRADE_EVAL_ID] == "trace-1"
    assert data["trades"][0][FieldName.GRADE] == "B"


# ---------------------------------------------------------------------------
# GET /learning/trades/{trade_id} — fallback detail paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trade_detail_db_down_finds_in_grade_history(client):
    """DB-down: detail endpoint falls back to grade_history when trade_evaluations is empty."""
    store = InMemoryStore()
    store.add_grade({"trace_id": "grade-abc", "score": 0.80, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades/grade-abc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    assert data["trade"][FieldName.TRADE_EVAL_ID] == "grade-abc"
    assert data["trade"][FieldName.GRADE] == "B"


@pytest.mark.asyncio
async def test_trade_detail_db_down_404_when_not_found(client):
    """DB-down: returns 404 when ID is not in trade_evaluations or grade_history."""
    store = InMemoryStore()
    store.add_grade({"trace_id": "other-id", "score": 0.70, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trade_detail_db_up_finds_in_agent_grades_bridge(client, monkeypatch):
    """DB-up: detail endpoint bridges to agent_grades when trade_evaluations is empty."""

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalar(self):
            return self._rows[0][0] if self._rows else None

        def first(self):
            return self._rows[0] if self._rows else None

        def all(self):
            return self._rows

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, stmt, *params):
            sql = str(stmt)
            if "trade_evaluations" in sql and "WHERE trade_id" in sql:
                # Primary lookup — no matching row
                return _Result([])
            if "COUNT" in sql and "trade_evaluations" in sql:
                # trade_evaluations is empty
                return _Result([(0,)])
            if "agent_grades" in sql and "WHERE trace_id" in sql:
                return _Result([("trace-xyz", 75.0, None)])
            return _Result([])

    class _Fac:
        def __call__(self):
            return _Session()

    monkeypatch.setattr(learning_module, "is_db_available", lambda: True)
    import api.database as _db_mod

    monkeypatch.setattr(_db_mod, "AsyncSessionFactory", _Fac())

    resp = await client.get("/learning/trades/trace-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "db"
    assert data["trade"][FieldName.TRADE_EVAL_ID] == "trace-xyz"
    # 75.0 normalizes to 0.75 → grade B
    assert data["trade"][FieldName.OVERALL_SCORE] == pytest.approx(0.75, rel=1e-3)
    assert data["trade"][FieldName.GRADE] == "B"
