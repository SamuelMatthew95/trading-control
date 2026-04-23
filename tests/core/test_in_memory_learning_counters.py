"""Tests for in-memory store learning counters functionality."""

import time

from api.constants import (
    FieldName,
    LogType,
)
from api.in_memory_store import InMemoryStore


def test_in_memory_learning_counters_initial_state():
    """Test that learning counters start at zero."""

    store = InMemoryStore()
    counters = store.get_learning_counters()

    # Verify all counters start at zero
    assert counters["trades_evaluated"] == 0
    assert counters["reflections_completed"] == 0
    assert counters["ic_values_updated"] == 0
    assert counters["strategies_tested"] == 0


def test_trades_evaluated_counter_increments_with_grades():
    """Test that trades_evaluated counter increments with grade history entries."""

    store = InMemoryStore()

    # Add grade history entries
    grade_entries = [
        {
            FieldName.TRACE_ID: "trace-1",
            FieldName.GRADE_TYPE: "accuracy",
            FieldName.SCORE: 85.0,
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.TRACE_ID: "trace-2",
            FieldName.GRADE_TYPE: "accuracy",
            FieldName.SCORE: 75.0,
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.TRACE_ID: "trace-3",
            FieldName.GRADE_TYPE: "accuracy",
            FieldName.SCORE: 90.0,
            FieldName.TIMESTAMP: time.time(),
        },
    ]

    for grade in grade_entries:
        store.add_grade(grade)

    counters = store.get_learning_counters()

    # Verify trades_evaluated counter matches grade history count
    assert counters["trades_evaluated"] == 3
    assert len(store.grade_history) == 3


def test_reflections_completed_counter_increments_with_reflections():
    """Test that reflections_completed counter increments with reflection events."""

    store = InMemoryStore()

    # Add reflection events
    reflection_events = [
        {
            FieldName.LOG_TYPE: LogType.REFLECTION,
            FieldName.TRACE_ID: "reflection-1",
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.LOG_TYPE: LogType.REFLECTION,
            FieldName.TRACE_ID: "reflection-2",
            FieldName.TIMESTAMP: time.time(),
        },
    ]

    for reflection in reflection_events:
        store.add_event(reflection)

    counters = store.get_learning_counters()

    # Verify reflections_completed counter matches reflection events count
    assert counters["reflections_completed"] == 2


def test_ic_values_updated_counter_increments_with_ic_updates():
    """Test that ic_values_updated counter increments with IC update events."""

    store = InMemoryStore()

    # Add IC update events
    ic_events = [
        {
            FieldName.LOG_TYPE: LogType.IC_UPDATE,
            FieldName.TRACE_ID: "ic-update-1",
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.LOG_TYPE: LogType.IC_UPDATE,
            FieldName.TRACE_ID: "ic-update-2",
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.LOG_TYPE: LogType.IC_UPDATE,
            FieldName.TRACE_ID: "ic-update-3",
            FieldName.TIMESTAMP: time.time(),
        },
    ]

    for ic_event in ic_events:
        store.add_event(ic_event)

    counters = store.get_learning_counters()

    # Verify ic_values_updated counter matches IC update events count
    assert counters["ic_values_updated"] == 3


def test_strategies_tested_counter_increments_with_proposals():
    """Test that strategies_tested counter increments with proposal events."""

    store = InMemoryStore()

    # Add proposal events
    proposal_events = [
        {
            FieldName.LOG_TYPE: LogType.PROPOSAL,
            FieldName.TRACE_ID: "proposal-1",
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.LOG_TYPE: LogType.PROPOSAL,
            FieldName.TRACE_ID: "proposal-2",
            FieldName.TIMESTAMP: time.time(),
        },
    ]

    for proposal in proposal_events:
        store.add_event(proposal)

    counters = store.get_learning_counters()

    # Verify strategies_tested counter matches proposal events count
    assert counters["strategies_tested"] == 2


def test_learning_counters_mixed_event_types():
    """Test that learning counters correctly count mixed event types."""

    store = InMemoryStore()

    # Add mixed events
    events = [
        # Grade entries
        {
            FieldName.TRACE_ID: "grade-1",
            FieldName.GRADE_TYPE: "accuracy",
            FieldName.SCORE: 85.0,
            FieldName.TIMESTAMP: time.time(),
        },
        # Reflection event
        {
            FieldName.LOG_TYPE: LogType.REFLECTION,
            FieldName.TRACE_ID: "reflection-1",
            FieldName.TIMESTAMP: time.time(),
        },
        # IC update event
        {
            FieldName.LOG_TYPE: LogType.IC_UPDATE,
            FieldName.TRACE_ID: "ic-1",
            FieldName.TIMESTAMP: time.time(),
        },
        # Proposal event
        {
            FieldName.LOG_TYPE: LogType.PROPOSAL,
            FieldName.TRACE_ID: "proposal-1",
            FieldName.TIMESTAMP: time.time(),
        },
        # Another grade entry
        {
            FieldName.TRACE_ID: "grade-2",
            FieldName.GRADE_TYPE: "accuracy",
            FieldName.SCORE: 75.0,
            FieldName.TIMESTAMP: time.time(),
        },
    ]

    # Add events to appropriate stores
    for event in events:
        if FieldName.GRADE_TYPE in event:
            store.add_grade(event)
        else:
            store.add_event(event)

    counters = store.get_learning_counters()

    # Verify all counters are correct
    assert counters["trades_evaluated"] == 2  # 2 grade entries
    assert counters["reflections_completed"] == 1  # 1 reflection event
    assert counters["ic_values_updated"] == 1  # 1 IC update event
    assert counters["strategies_tested"] == 1  # 1 proposal event


def test_learning_counters_ignore_other_event_types():
    """Test that learning counters ignore non-relevant event types."""

    store = InMemoryStore()

    # Add events that should NOT be counted
    irrelevant_events = [
        {
            FieldName.LOG_TYPE: LogType.SIGNAL_GENERATED,
            FieldName.TRACE_ID: "signal-1",
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.LOG_TYPE: "trade_executed",
            FieldName.TRACE_ID: "trade-1",
            FieldName.TIMESTAMP: time.time(),
        },
        {
            FieldName.LOG_TYPE: "unknown_log_type",
            FieldName.TRACE_ID: "unknown-1",
            FieldName.TIMESTAMP: time.time(),
        },
    ]

    for event in irrelevant_events:
        store.add_event(event)

    counters = store.get_learning_counters()

    # Verify all counters remain at zero
    assert counters["trades_evaluated"] == 0
    assert counters["reflections_completed"] == 0
    assert counters["ic_values_updated"] == 0
    assert counters["strategies_tested"] == 0


def test_learning_counters_consistency_with_actual_data():
    """Test that learning counters are consistent with actual store data."""

    store = InMemoryStore()

    # Add various events
    store.add_grade(
        {
            FieldName.TRACE_ID: "grade-1",
            FieldName.GRADE_TYPE: "accuracy",
            FieldName.SCORE: 85.0,
            FieldName.TIMESTAMP: time.time(),
        }
    )

    store.add_event(
        {
            FieldName.LOG_TYPE: LogType.REFLECTION,
            FieldName.TRACE_ID: "reflection-1",
            FieldName.TIMESTAMP: time.time(),
        }
    )

    store.add_event(
        {
            FieldName.LOG_TYPE: "ic_update",
            FieldName.TRACE_ID: "ic-1",
            FieldName.TIMESTAMP: time.time(),
        }
    )

    store.add_event(
        {
            FieldName.LOG_TYPE: "proposal",
            FieldName.TRACE_ID: "proposal-1",
            FieldName.TIMESTAMP: time.time(),
        }
    )

    counters = store.get_learning_counters()

    # Verify counters match actual data counts
    assert counters["trades_evaluated"] == len(store.grade_history)
    assert counters["reflections_completed"] == len(
        [e for e in store.event_history if e.get(FieldName.LOG_TYPE) == LogType.REFLECTION]
    )
    assert counters["ic_values_updated"] == len(
        [e for e in store.event_history if "ic_update" in str(e.get(FieldName.LOG_TYPE, ""))]
    )
    assert counters["strategies_tested"] == len(
        [e for e in store.event_history if "proposal" in str(e.get(FieldName.LOG_TYPE, ""))]
    )


def test_learning_counters_after_data_clearing():
    """Test learning counters behavior after clearing data."""

    store = InMemoryStore()

    # Add initial data
    store.add_grade(
        {
            FieldName.TRACE_ID: "grade-1",
            FieldName.GRADE_TYPE: "accuracy",
            FieldName.SCORE: 85.0,
            FieldName.TIMESTAMP: time.time(),
        }
    )

    store.add_event(
        {
            FieldName.LOG_TYPE: LogType.REFLECTION,
            FieldName.TRACE_ID: "reflection-1",
            FieldName.TIMESTAMP: time.time(),
        }
    )

    # Verify initial counters
    counters = store.get_learning_counters()
    assert counters["trades_evaluated"] == 1
    assert counters["reflections_completed"] == 1

    # Clear data
    store.grade_history.clear()
    store.event_history.clear()

    # Verify counters are now zero
    counters = store.get_learning_counters()
    assert counters["trades_evaluated"] == 0
    assert counters["reflections_completed"] == 0
    assert counters["ic_values_updated"] == 0
    assert counters["strategies_tested"] == 0


def test_learning_counters_large_dataset():
    """Test learning counters performance with large datasets."""

    store = InMemoryStore()

    # Add large number of events
    num_grades = 100
    num_reflections = 50
    num_ic_updates = 25
    num_proposals = 10

    # Add grades
    for i in range(num_grades):
        store.add_grade(
            {
                FieldName.TRACE_ID: f"grade-{i}",
                FieldName.GRADE_TYPE: "accuracy",
                FieldName.SCORE: 80.0 + i % 20,
                FieldName.TIMESTAMP: time.time() + i,
            }
        )

    # Add reflection events
    for i in range(num_reflections):
        store.add_event(
            {
                FieldName.LOG_TYPE: LogType.REFLECTION,
                FieldName.TRACE_ID: f"reflection-{i}",
                FieldName.TIMESTAMP: time.time() + i,
            }
        )

    # Add IC update events
    for i in range(num_ic_updates):
        store.add_event(
            {
                FieldName.LOG_TYPE: "ic_update",
                FieldName.TRACE_ID: f"ic-{i}",
                FieldName.TIMESTAMP: time.time() + i,
            }
        )

    # Add proposal events
    for i in range(num_proposals):
        store.add_event(
            {
                FieldName.LOG_TYPE: "proposal",
                FieldName.TRACE_ID: f"proposal-{i}",
                FieldName.TIMESTAMP: time.time() + i,
            }
        )

    counters = store.get_learning_counters()

    # Verify counters match expected values
    assert counters["trades_evaluated"] == num_grades
    assert counters["reflections_completed"] == num_reflections
    assert counters["ic_values_updated"] == num_ic_updates
    assert counters["strategies_tested"] == num_proposals


def test_learning_counters_return_type():
    """Test that learning counters return the correct data structure."""

    store = InMemoryStore()
    counters = store.get_learning_counters()

    # Verify return type is dict
    assert isinstance(counters, dict)

    # Verify all expected keys are present
    expected_keys = [
        "trades_evaluated",
        "reflections_completed",
        "ic_values_updated",
        "strategies_tested",
    ]
    for key in expected_keys:
        assert key in counters

    # Verify all values are integers
    for key in expected_keys:
        assert isinstance(counters[key], int)
        assert counters[key] >= 0  # Should never be negative
