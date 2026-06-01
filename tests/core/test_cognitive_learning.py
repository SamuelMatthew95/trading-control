"""Unit tests for attribution, importance metadata, and the LearningEngine.

The central invariant under test: learning produces OBSERVATIONS and METADATA
only — it has no method that edits config or weights.
"""

from __future__ import annotations

from cognitive.learning import (
    Attribution,
    ImportanceTracker,
    LearningEngine,
    attribute,
)


def test_attribution_splits_pnl_by_absolute_contribution_share():
    breakdown = {"news": 0.2, "tech": 0.1, "macro": -0.1}  # total |contrib| = 0.4
    attribution = attribute(breakdown, realized_pnl=100.0)
    assert attribution.shares["news"] == 0.5
    assert attribution.shares["tech"] == 0.25
    assert attribution.shares["macro"] == 0.25
    assert attribution.pnl_attribution["news"] == 50.0
    assert sum(attribution.shares.values()) == 1.0


def test_attribution_handles_zero_contribution():
    attribution = attribute({"news": 0.0, "tech": 0.0, "macro": 0.0}, realized_pnl=10.0)
    assert all(share == 0.0 for share in attribution.shares.values())


def test_importance_tracker_is_a_pure_fold():
    tracker = ImportanceTracker()
    # news consistently right (positive contribution, winning trades)
    for _ in range(40):
        tracker.update(attribute({"news": 0.3, "tech": 0.0, "macro": 0.0}, 5.0), outcome_sign=1)
    meta = tracker.metadata()
    assert meta["news"]["samples"] == 40
    assert meta["news"]["correct_rate"] == 1.0
    assert meta["news"]["total_pnl_attribution"] > 0
    assert meta["macro"]["samples"] == 40  # every signal sampled each trade


def test_learning_engine_emits_observations_only():
    engine = LearningEngine(min_samples=30)
    # only news has enough samples + an edge
    metadata = {
        "news": {
            "samples": 50,
            "avg_abs_contribution": 0.3,
            "total_pnl_attribution": 100.0,
            "correct_rate": 0.8,
        },
        "tech": {
            "samples": 10,
            "avg_abs_contribution": 0.2,
            "total_pnl_attribution": 5.0,
            "correct_rate": 0.9,
        },
        "macro": {
            "samples": 50,
            "avg_abs_contribution": 0.1,
            "total_pnl_attribution": -20.0,
            "correct_rate": 0.3,
        },
    }
    observations = engine.observe(metadata)
    by_signal = {obs.signal: obs for obs in observations}
    assert by_signal["news"].direction == "outperforming"
    assert by_signal["macro"].direction == "underperforming"
    assert "tech" not in by_signal  # below min_samples -> no observation
    # evidence is attached so a conclusion can be drilled into
    assert by_signal["news"].evidence["sample_size"] == 50
    assert "agent_grade" in by_signal["news"].evidence


def test_learning_engine_has_no_mutation_methods():
    engine = LearningEngine()
    forbidden = {"apply", "set_weight", "update_config", "write", "merge"}
    assert forbidden.isdisjoint(dir(engine))


def test_attribution_dataclass_is_frozen():
    attribution = attribute({"news": 0.1, "tech": 0.0, "macro": 0.0}, 1.0)
    assert isinstance(attribution, Attribution)
    try:
        attribution.realized_pnl = 9.9  # type: ignore[misc]
        raise AssertionError("Attribution should be immutable")
    except (AttributeError, TypeError):
        pass
