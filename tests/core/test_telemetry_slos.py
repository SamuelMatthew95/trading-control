"""Guardrail for the SLO spec (governance build-order #3 scaffolding).

Locks that the SLO definitions reference SLIs that actually exist, that targets
are calibration-gated (so an uncalibrated number can't masquerade as final), and
that burn-rate alerting is multi-window. Design:
docs/platform/telemetry-governance.md §4 + observability/signoz/slos.md.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLOS = ROOT / "observability" / "signoz" / "slos.md"


class TestSloSpec:
    def test_exists(self):
        assert SLOS.is_file(), f"SLO spec missing at {SLOS}"

    def test_slis_reference_real_metrics(self):
        text = SLOS.read_text(encoding="utf-8")
        for metric in (
            "broker_api_latency",
            "trades_failed_total",
            "trades_submitted_total",
            "agent_process_duration",
            "http_server_duration_count",
        ):
            assert metric in text, f"SLO spec must reference the real SLI metric {metric}"

    def test_targets_are_calibration_gated(self):
        text = SLOS.read_text(encoding="utf-8")
        assert "CALIBRATE" in text, "framework targets must be flagged for calibration"
        assert "P99" in text, "the measured-P99 calibration discipline must be documented"

    def test_multiwindow_burn_rate_defined(self):
        text = SLOS.read_text(encoding="utf-8").lower()
        assert "burn" in text
        # Multi-window: both a long and a short window must be present.
        assert "1h" in text and "5m" in text
