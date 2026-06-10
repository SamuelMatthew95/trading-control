"""Regression tests for memory-mode dashboard read paths.

Covers the sweep fixes:
- flow counters must report real in-memory list lengths (orders / trade feed /
  agent logs), not hardcoded zeros or the events feed length;
- memory-mode reflections must collapse the dual-written rows (payload-bearing
  event_history copy + payload-less agent_logs mirror) to one row per trace;
- the memory grade→trade bridge must tolerate grade rows whose score fields
  exist but are None (dict.get(key, default) keeps the explicit None);
- memory performance trends must compute averages over the SAME order window
  the paired summary uses.
"""

from __future__ import annotations

from api.constants import FieldName, LogType
from api.in_memory_store import InMemoryStore
from api.routes.learning_helpers import _mem_grades_as_trades
from api.runtime_state import set_runtime_store
from api.services.dashboard.flow import _flow_status_memory_payload
from api.services.dashboard.learning import _in_memory_reflections
from api.services.dashboard.trading import _performance_trends_from_runtime_store


def test_flow_counts_report_real_memory_lengths():
    store = InMemoryStore()
    store.add_order({FieldName.SYMBOL: "BTC/USD", FieldName.PNL: 1.0})
    store.add_order({FieldName.SYMBOL: "ETH/USD", FieldName.PNL: -1.0})
    store.upsert_trade_fill({FieldName.ORDER_ID: "o-1", FieldName.SYMBOL: "BTC/USD"})
    store.add_agent_log({FieldName.MESSAGE: "hello"})
    store.add_event({FieldName.ID: "ev-1", FieldName.KIND: "risk_alerts"})
    set_runtime_store(store)

    counts = _flow_status_memory_payload()[FieldName.COUNTS]
    assert counts[FieldName.ORDERS] == 2
    assert counts[FieldName.TRADE_LIFECYCLE] == 1
    assert counts[FieldName.AGENT_LOGS] == 1


def test_memory_reflections_deduped_to_payload_bearing_row():
    """write_agent_log dual-writes a reflection; the dashboard must list it once."""
    store = InMemoryStore()
    # Payload-bearing copy (event_history) + payload-less mirror (agent_logs),
    # exactly the shape db_helpers.write_agent_log produces in memory mode.
    store.add_event(
        {
            FieldName.LOG_TYPE: LogType.REFLECTION,
            FieldName.TRACE_ID: "refl-1",
            FieldName.PAYLOAD: {FieldName.SUMMARY: "real summary", FieldName.HYPOTHESES: ["h1"]},
        }
    )
    store.add_agent_log(
        {
            FieldName.LOG_TYPE: LogType.REFLECTION,
            FieldName.TRACE_ID: "refl-1",
            FieldName.MESSAGE: "reflection",
        }
    )
    set_runtime_store(store)

    reflections = _in_memory_reflections(limit=10)
    assert len(reflections) == 1
    assert reflections[0][FieldName.SUMMARY] == "real summary"


def test_mem_grade_bridge_tolerates_none_scores():
    """A grade row with score=None / score_pct=None must not 500 the bridge."""
    store = InMemoryStore()
    store.add_grade({FieldName.TRACE_ID: "g-1", FieldName.SCORE: None, FieldName.SCORE_PCT: None})

    trades, total = _mem_grades_as_trades(store, limit=10, offset=0)
    assert total == 1
    assert len(trades) == 1


def test_performance_trends_averages_use_paired_window():
    """avg_win must divide sums and counts from the SAME order slice."""
    store = InMemoryStore()
    # 110 winning orders: the paired summary windows the last 100. Old code
    # summed wins over ALL orders but divided by the windowed count.
    for i in range(110):
        store.add_order({FieldName.SYMBOL: "BTC/USD", FieldName.PNL: 10.0})
    set_runtime_store(store)

    summary = _performance_trends_from_runtime_store()["summary"]
    assert summary[FieldName.TOTAL_TRADES] == 100
    assert summary[FieldName.AVG_WIN] == 10.0
