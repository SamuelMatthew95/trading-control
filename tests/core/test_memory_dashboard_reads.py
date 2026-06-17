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
    for _ in range(110):
        store.add_order({FieldName.SYMBOL: "BTC/USD", FieldName.PNL: 10.0})
    set_runtime_store(store)

    summary = _performance_trends_from_runtime_store()["summary"]
    assert summary[FieldName.TOTAL_TRADES] == 100
    assert summary[FieldName.AVG_WIN] == 10.0


def test_memory_proposals_have_unique_ids_and_applied_rows_are_not_pending():
    """Regression (queue-spam): proposals from one reflection share the
    reflection trace — rows keyed on it collapsed to one identity (approving
    one approved all). And applier audit rows (applied=True, no status) must
    never read back as pending."""
    from api.constants import LogType, ProposalStatus
    from api.services.dashboard.proposals import _in_memory_proposals

    store = InMemoryStore()
    for n in (1, 2):
        store.add_event(
            {
                FieldName.LOG_TYPE: LogType.PROPOSAL,
                FieldName.TRACE_ID: "shared-reflection-trace",
                FieldName.PAYLOAD: {
                    FieldName.MSG_ID: f"msg-{n}",
                    FieldName.PROPOSAL_TYPE: "parameter_change",
                    FieldName.CONTENT: {FieldName.DESCRIPTION: f"candidate {n}"},
                },
            }
        )
    # Old-style applier audit row: applied flag, no explicit status.
    store.add_event(
        {
            FieldName.LOG_TYPE: LogType.PROPOSAL,
            FieldName.TRACE_ID: "shared-reflection-trace",
            FieldName.PAYLOAD: {
                FieldName.MSG_ID: "msg-audit",
                FieldName.PROPOSAL_TYPE: "parameter_change",
                FieldName.APPLIED: True,
            },
        }
    )
    set_runtime_store(store)

    rows = _in_memory_proposals(limit=10)
    ids = [r[FieldName.ID] for r in rows]
    assert len(ids) == len(set(ids)), "each proposal must have its own identity"
    audit = next(r for r in rows if r[FieldName.ID] == "msg-audit")
    assert audit["status"] == ProposalStatus.APPLIED


def test_dashboard_snapshot_proposals_are_flattened_not_raw_envelopes():
    """Regression: in memory mode dashboard_fallback_snapshot() (the
    /dashboard/state + WebSocket snapshot the Proposals page hydrates from)
    returned raw event envelopes — proposal_type/content/id/status lived under
    `payload`, so the frontend rendered identity-less, garbled rows. The
    snapshot must emit the SAME flattened shape as the DB path."""
    from api.constants import OrderStatus

    store = InMemoryStore()
    store.add_event(
        {
            FieldName.LOG_TYPE: LogType.PROPOSAL,
            FieldName.TRACE_ID: "refl-1",
            FieldName.PAYLOAD: {
                FieldName.MSG_ID: "msg-1",
                FieldName.PROPOSAL_TYPE: "prompt_evolution",
                FieldName.CONTENT: {FieldName.DESCRIPTION: "sharpen directive"},
                FieldName.CONFIDENCE: 0.82,
            },
        }
    )

    rows = store.dashboard_fallback_snapshot()[FieldName.PROPOSALS]
    assert len(rows) == 1
    row = rows[0]
    # Flattened to top level — not buried under `payload`.
    assert FieldName.PAYLOAD not in row
    assert row[FieldName.ID] == "msg-1"
    assert row["proposal_type"] == "prompt_evolution"
    assert row["confidence"] == 0.82
    assert row["status"] == OrderStatus.PENDING


def test_dashboard_snapshot_and_proposals_endpoint_agree():
    """The /dashboard/state snapshot and the /dashboard/proposals endpoint must
    surface identical proposal rows (both flow through normalized_proposals)."""
    from api.services.dashboard.proposals import _in_memory_proposals

    store = InMemoryStore()
    store.add_event(
        {
            FieldName.LOG_TYPE: LogType.PROPOSAL,
            FieldName.TRACE_ID: "refl-2",
            FieldName.PAYLOAD: {
                FieldName.MSG_ID: "msg-2",
                FieldName.PROPOSAL_TYPE: "parameter_change",
                FieldName.CONTENT: {FieldName.DESCRIPTION: "raise threshold"},
            },
        }
    )
    set_runtime_store(store)

    snapshot_rows = store.dashboard_fallback_snapshot()[FieldName.PROPOSALS]
    endpoint_rows = _in_memory_proposals(limit=20)
    assert snapshot_rows == endpoint_rows


def test_grade_history_views_exclude_signal_accuracy_rows():
    """Memory mode must apply the same grade-history filter as the DB path:
    SignalGenerator's per-signal accuracy rows share grade_history but are not
    trade grades, and leaked into /dashboard/grades and the learning panel."""
    from api.constants import GradeType

    store = InMemoryStore()
    store.add_grade({FieldName.TRACE_ID: "g-overall", FieldName.SCORE: 0.8})
    store.add_grade(
        {
            FieldName.TRACE_ID: "g-signal",
            FieldName.GRADE_TYPE: GradeType.ACCURACY,
            FieldName.SCORE: 0.6,
        }
    )

    overall = store.get_overall_grades(limit=10)
    assert [g[FieldName.TRACE_ID] for g in overall] == ["g-overall"]
    snapshot = store.dashboard_fallback_snapshot()
    assert [g[FieldName.TRACE_ID] for g in snapshot[FieldName.LEARNING_EVENTS]] == ["g-overall"]
