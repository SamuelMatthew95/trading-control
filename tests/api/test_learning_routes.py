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
from api.routes.learning import (
    _grade_from_score,
    _grade_record_to_trade,
    _iso,
    _mem_grades_as_trades,
    _row_to_trade_eval,
)
from api.runtime_state import set_db_available, set_runtime_store


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


def test_row_to_trade_eval_with_provenance():
    row = (
        "id-1", "trade-1", "BTC/USD", "buy", 12.0, 1.2,
        0.7, 0.6, 0.65, 0.8, 2.0, 0.72, "B", 0.8,
        ["late_entry"], ["good_rr"], "2026-05-23T00:00:00+00:00",
        "gemini:flash", "vwap_reclaim",
    )
    out = _row_to_trade_eval(row, has_provenance=True)
    assert out[FieldName.TRADE_EVAL_ID] == "trade-1"
    assert out[FieldName.MODEL_USED] == "gemini:flash"
    assert out[FieldName.PRIMARY_EDGE] == "vwap_reclaim"
    assert out[FieldName.MISTAKES] == ["late_entry"]


def test_row_to_trade_eval_without_provenance_is_blank():
    # Base row has 17 columns; helper must not index past it when provenance is off.
    row = (
        "id-2", "trade-2", "ETH/USD", "sell", -3.0, -0.5,
        0.4, 0.5, 0.45, 0.6, 1.0, 0.4, "D", 0.5,
        [], [], "2026-05-23T00:00:00+00:00",
    )
    out = _row_to_trade_eval(row, has_provenance=False)
    assert out[FieldName.MODEL_USED] == ""
    assert out[FieldName.PRIMARY_EDGE] == ""


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_iso_handles_unix_float():
    """_iso converts time.time() floats to proper ISO strings, not raw stringified floats."""
    ts = 1700000000.123
    result = _iso(ts)
    assert result is not None
    assert "T" in result  # proper ISO 8601 format
    assert "." not in result.split("T")[0]  # date part is not a raw float


def test_iso_handles_none():
    assert _iso(None) is None


def test_iso_handles_string_passthrough():
    s = "2024-01-15T10:30:00+00:00"
    assert _iso(s) == s


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


def test_mem_grades_as_trades_beyond_200_entries():
    """Pagination is correct even when grade_history exceeds 200 entries."""
    store = InMemoryStore()
    # store.grade_history caps at 500; add 250 entries
    for i in range(250):
        store.add_grade({"trace_id": f"t{i}", "score": 0.7, "timestamp": time.time()})

    trades, total = _mem_grades_as_trades(store, limit=10, offset=240)
    assert total == 250
    assert len(trades) == 10


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
async def test_model_performance_db_down_groups_by_model(client):
    store = InMemoryStore()
    for i, (model, pnl, score) in enumerate(
        [("gemini:flash", 10.0, 0.8), ("gemini:flash", -4.0, 0.4), ("lmstudio:llama", 6.0, 0.7)]
    ):
        store.add_trade_evaluation(
            {
                FieldName.TRADE_EVAL_ID: f"eval-{i}",
                FieldName.MODEL_USED: model,
                FieldName.PNL: pnl,
                FieldName.OVERALL_SCORE: score,
                "created_at": time.time(),
            }
        )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/model-performance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    by_model = {m[FieldName.MODEL_USED]: m for m in data[FieldName.MODELS]}
    assert by_model["gemini:flash"][FieldName.TRADE_COUNT] == 2
    assert by_model["gemini:flash"][FieldName.WIN_RATE] == 0.5
    assert by_model["gemini:flash"][FieldName.TOTAL_PNL] == 6.0
    assert by_model["lmstudio:llama"][FieldName.TRADE_COUNT] == 1
    # Models with no model_used are excluded; sorted by trade count desc.
    assert data[FieldName.MODELS][0][FieldName.MODEL_USED] == "gemini:flash"


@pytest.mark.asyncio
async def test_model_performance_empty_store(client):
    set_runtime_store(InMemoryStore())
    set_db_available(False)
    resp = await client.get("/learning/model-performance")
    assert resp.status_code == 200
    assert resp.json()[FieldName.MODELS] == []


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


@pytest.mark.asyncio
async def test_list_trades_db_down_trade_evals_full_count(client):
    """total reflects all 300 trade_evaluations, not capped at 200."""
    store = InMemoryStore()
    for i in range(300):
        store.add_trade_evaluation(
            {
                FieldName.TRADE_EVAL_ID: f"e{i}",
                FieldName.OVERALL_SCORE: 0.7,
                "created_at": time.time(),
            }
        )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 300  # not capped at 200
    assert len(data["trades"]) == 10


@pytest.mark.asyncio
async def test_list_trades_db_down_timestamps_are_iso(client):
    """time.time() float timestamps are converted to ISO 8601 strings in responses."""
    store = InMemoryStore()
    store.add_grade({"trace_id": "t1", "score": 0.75, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades")
    data = resp.json()
    ts = data["trades"][0].get("created_at")
    assert ts is not None
    assert "T" in ts  # ISO 8601 contains a T separator


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
    """Metrics synthesize PnL from score so win_rate/avg_return are non-zero."""
    store = InMemoryStore()
    # score 0.80 → synthetic pnl_pct +6% (win), score 0.60 → +2% (win)
    store.add_grade({"trace_id": "g1", "score": 0.80, "timestamp": time.time()})
    store.add_grade({"trace_id": "g2", "score": 0.60, "timestamp": time.time()})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "memory"
    assert data["win_rate"] == pytest.approx(1.0)  # both scores > 0.5 → synthetic pnl > 0
    assert data["avg_return"] > 0  # synthetic pnl_pct is positive
    assert data["avg_score"] == pytest.approx(0.70, rel=1e-2)


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


def test_store_add_strategy_generates_id():
    """add_strategy auto-generates id so strategies have unique React keys."""
    store = InMemoryStore()
    s = store.add_strategy({FieldName.STATUS: "pending"})
    assert "id" in s
    assert len(s["id"]) == 36  # UUID4 format


def test_store_add_reflection_generates_id():
    """add_reflection auto-generates id for consistency."""
    store = InMemoryStore()
    r = store.add_reflection({FieldName.PATTERNS: []})
    assert "id" in r
    assert len(r["id"]) == 36


@pytest.mark.asyncio
async def test_trade_detail_db_down_finds_beyond_200_in_grade_history(client):
    """Detail endpoint searches all grade_history, not just first 200."""
    store = InMemoryStore()
    # Push 250 grades so the target is beyond the 200-entry page
    for i in range(250):
        store.add_grade({"trace_id": f"g{i}", "score": 0.70, "timestamp": time.time()})
    # The 0th grade added will be at position 249 in grade_history (oldest first)
    # grade_history[0] = g0 — it will be at offset 249 in reversed list
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades/g0")  # oldest = beyond position 200
    assert resp.status_code == 200
    data = resp.json()
    assert data["trade"][FieldName.TRADE_EVAL_ID] == "g0"


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

    # Patch is_db_available AND AsyncSessionFactory on the route module under test.
    monkeypatch.setattr(learning_module, "is_db_available", lambda: True)
    monkeypatch.setattr(learning_module, "AsyncSessionFactory", _Fac())

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
    monkeypatch.setattr(learning_module, "AsyncSessionFactory", _Fac())

    resp = await client.get("/learning/trades/trace-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "db"
    assert data["trade"][FieldName.TRADE_EVAL_ID] == "trace-xyz"
    # 75.0 normalizes to 0.75 → grade B
    assert data["trade"][FieldName.OVERALL_SCORE] == pytest.approx(0.75, rel=1e-3)
    assert data["trade"][FieldName.GRADE] == "B"


@pytest.mark.asyncio
async def test_trade_detail_db_up_bridges_when_trade_evals_table_inaccessible(client, monkeypatch):
    """DB-up: 500 must not be raised when trade_evaluations is inaccessible (partial migration).

    The detail endpoint must still reach the agent_grades bridge even when the
    initial SELECT FROM trade_evaluations raises (e.g., table not yet created).
    """

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
            if "trade_evaluations" in sql:
                # Simulate table not existing during partial migration
                raise Exception('relation "trade_evaluations" does not exist')
            if "agent_grades" in sql and "WHERE trace_id" in sql:
                return _Result([("missing-te-id", 65.0, None)])
            return _Result([])

    class _Fac:
        def __call__(self):
            return _Session()

    monkeypatch.setattr(learning_module, "is_db_available", lambda: True)
    monkeypatch.setattr(learning_module, "AsyncSessionFactory", _Fac())

    resp = await client.get("/learning/trades/missing-te-id")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "db"
    assert data["trade"][FieldName.TRADE_EVAL_ID] == "missing-te-id"
    # 65.0 normalizes to 0.65 → grade C
    assert data["trade"][FieldName.OVERALL_SCORE] == pytest.approx(0.65, rel=1e-3)


@pytest.mark.asyncio
async def test_trade_detail_db_down_returns_newest_on_duplicate_trace(client):
    """DB-down: when the same trace_id is graded twice, detail returns the newest score."""
    store = InMemoryStore()
    now = time.time()
    # Old entry with a low score, then a newer entry with a higher score.
    store.add_grade({"trace_id": "dup-id", "score": 20.0, "timestamp": now - 10})
    store.add_grade({"trace_id": "dup-id", "score": 80.0, "timestamp": now})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades/dup-id")
    assert resp.status_code == 200
    data = resp.json()
    # Newest grade (80 → 0.80 normalised) must win, not the stale 20 → 0.20
    assert data["trade"][FieldName.OVERALL_SCORE] == pytest.approx(0.80, rel=1e-3)
    assert data["trade"][FieldName.GRADE] == "B"


@pytest.mark.asyncio
async def test_metrics_db_down_grade_history_chronological_order(client):
    """DB-down metrics: grade_history is fed oldest→newest so score_trend is correct."""
    store = InMemoryStore()
    now = time.time()
    # Scores improving over time: 40, 60, 80 (oldest→newest)
    for score in [40.0, 60.0, 80.0]:
        store.add_grade({"trace_id": f"t-{score}", "score": score, "timestamp": now})
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/metrics")
    assert resp.status_code == 200
    data = resp.json()
    # With improving scores the trend must not be "declining"
    assert data.get("score_trend") in ("improving", "stable")


@pytest.mark.asyncio
async def test_list_trades_db_down_excludes_accuracy_grades(client):
    """DB-down: accuracy grades from SignalGenerator must not appear in /learning/trades."""
    from api.constants import GradeType

    store = InMemoryStore()
    now = time.time()
    # One real trade grade (no grade_type set — GradeAgent memory path)
    store.add_grade({"trace_id": "trade-grade", "score": 0.80, "timestamp": now})
    # One accuracy grade from SignalGenerator
    store.add_grade(
        {
            "trace_id": "signal-grade",
            "grade_type": GradeType.ACCURACY,
            "score": 0.90,
            "timestamp": now,
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades")
    assert resp.status_code == 200
    data = resp.json()
    # Only the trade grade must be visible; the accuracy grade must be excluded
    assert data["total"] == 1
    ids = [t[FieldName.TRADE_EVAL_ID] for t in data["trades"]]
    assert "trade-grade" in ids
    assert "signal-grade" not in ids


@pytest.mark.asyncio
async def test_metrics_db_down_excludes_accuracy_grades(client):
    """DB-down metrics: accuracy grades from SignalGenerator must not skew metrics."""
    from api.constants import GradeType

    store = InMemoryStore()
    now = time.time()
    # Three real trade grades at score 0.80
    for i in range(3):
        store.add_grade({"trace_id": f"trade-{i}", "score": 0.80, "timestamp": now})
    # One accuracy grade with a very different score — must not affect avg_score
    store.add_grade(
        {
            "trace_id": "signal-acc",
            "grade_type": GradeType.ACCURACY,
            "score": 0.10,
            "timestamp": now,
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/metrics")
    assert resp.status_code == 200
    data = resp.json()
    # avg_score must reflect only the three 0.80 grades
    assert data.get("avg_score", 0) == pytest.approx(0.80, abs=0.05)


@pytest.mark.asyncio
async def test_trade_detail_db_down_excludes_accuracy_grade(client):
    """DB-down detail: accuracy-typed grade must not be returned for a trade_id lookup."""
    from api.constants import GradeType

    store = InMemoryStore()
    now = time.time()
    # Only an accuracy grade exists for this trace_id — must return 404
    store.add_grade(
        {
            "trace_id": "signal-only",
            "grade_type": GradeType.ACCURACY,
            "score": 0.90,
            "timestamp": now,
        }
    )
    set_runtime_store(store)
    set_db_available(False)

    resp = await client.get("/learning/trades/signal-only")
    assert resp.status_code == 404
