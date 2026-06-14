"""Guardrails for the telemetry cost engine (governance build-order #2).

Locks the ingestion-VOLUME source (collector self-telemetry) and the cost/drift
alert + dashboard contract so they can't silently regress. Design:
docs/platform/telemetry-governance.md §3. Mirrors the lock-step approach of
test_otel_collector_normalization.py — it pins the contract, not a live scrape.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "observability" / "signoz" / "otel-collector-config.yaml"
ALERTS = ROOT / "observability" / "signoz" / "alerts.md"
README = ROOT / "observability" / "signoz" / "README.md"


class TestCollectorSelfTelemetry:
    def test_self_telemetry_metrics_enabled(self):
        yaml = pytest.importorskip("yaml")
        cfg = yaml.safe_load(COLLECTOR.read_text(encoding="utf-8"))
        metrics = cfg["service"]["telemetry"]["metrics"]
        assert metrics["level"] == "detailed"
        # A Prometheus pull reader must expose the otelcol_* volume metrics.
        prom = [r["pull"]["exporter"]["prometheus"] for r in metrics["readers"] if "pull" in r]
        assert any(p.get("port") == 8888 for p in prom), "self-telemetry scrape port missing"


class TestAlertsContract:
    def test_drift_and_cost_alerts_present(self):
        text = ALERTS.read_text(encoding="utf-8")
        assert 'telemetry_schema_drift_total{drift_kind="unknown_key"}' in text
        assert 'telemetry_schema_drift_total{drift_kind="budget_exceeded"}' in text
        assert "cost_per_business_event" in text


class TestCostDashboardSpec:
    def test_cost_panels_documented(self):
        text = README.read_text(encoding="utf-8")
        assert "Cost Dashboard" in text
        assert "otelcol_exporter_sent_spans" in text
        assert "cost_per_business_event" in text
