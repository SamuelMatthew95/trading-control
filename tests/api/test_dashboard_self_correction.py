"""The grade self-correction diagnostic surfaces through the dashboard serializers.

Memory-mode path (no DB): write_grade_to_db mirrors the diagnostic into the
InMemoryStore grade record, and both get_grade_history_payload and
get_learning_loop_payload expose it for the Self-Correction dashboard card.
"""

import pytest

from api.constants import FieldName
from api.services.agents.db_helpers import write_grade_to_db
from api.services.dashboard.learning import (
    get_grade_history_payload,
    get_learning_loop_payload,
)

_DIAGNOSTIC = {
    FieldName.ANOMALY_DETECTED: True,
    FieldName.DIRECTION: "negative_drop",
    FieldName.Z_SCORE: -2.5,
    FieldName.BASELINE_MEAN: 0.80,
    FieldName.BASELINE_STD: 0.01,
    FieldName.BASELINE_SAMPLES: 6,
    FieldName.TRAJECTORY: {
        FieldName.SLOPE: -0.05,
        FieldName.DIRECTION: "decaying",
        FieldName.DECAYING: True,
    },
    FieldName.ATTRIBUTION: [{FieldName.DIMENSION: FieldName.ACCURACY, FieldName.DELTA: -0.3}],
    FieldName.MESSAGE: "grade negative_drop z=-2.50 ...",
}


@pytest.mark.asyncio
async def test_grade_history_surfaces_self_correction_in_memory_mode():
    # conftest resets to memory mode (is_db_available() == False) with an empty store.
    await write_grade_to_db(
        "trace-sc", 62.0, {FieldName.ACCURACY: 0.5}, self_correction=_DIAGNOSTIC
    )
    payload = await get_grade_history_payload(limit=10)

    grades = payload[FieldName.GRADES]
    assert grades, "expected the grade we just wrote to the in-memory store"
    diagnostic = grades[0][FieldName.SELF_CORRECTION]
    assert diagnostic[FieldName.ANOMALY_DETECTED] is True
    assert diagnostic[FieldName.DIRECTION] == "negative_drop"
    assert diagnostic[FieldName.TRAJECTORY][FieldName.DECAYING] is True


@pytest.mark.asyncio
async def test_learning_loop_latest_grade_includes_self_correction():
    await write_grade_to_db(
        "trace-sc2", 62.0, {FieldName.ACCURACY: 0.5}, self_correction=_DIAGNOSTIC
    )
    payload = await get_learning_loop_payload()

    latest = payload[FieldName.LATEST_GRADE]
    assert latest is not None
    assert latest[FieldName.SELF_CORRECTION][FieldName.DIRECTION] == "negative_drop"


@pytest.mark.asyncio
async def test_grade_without_self_correction_defaults_to_empty():
    # Older callers that omit self_correction must still serialize cleanly.
    await write_grade_to_db("trace-plain", 70.0, {FieldName.ACCURACY: 0.6})
    payload = await get_grade_history_payload(limit=10)

    grades = payload[FieldName.GRADES]
    assert grades
    assert grades[0][FieldName.SELF_CORRECTION] == {}
