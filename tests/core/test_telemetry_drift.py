"""Runtime drift auditor (telemetry governance Layer B) — api/telemetry_drift.py.

Unit-tests the pure auditor logic with plain dicts (no OTel, no SigNoz), plus
the B2 fetch seam (must fail open) and the B1 recorder hook in api/telemetry.py.
"""

from api import telemetry
from api.constants import (
    DRIFT_KIND_BUDGET_EXCEEDED,
    DRIFT_KIND_UNKNOWN_KEY,
    TELEMETRY_SCHEMA,
)
from api.telemetry_drift import (
    DriftFinding,
    TelemetryDriftAuditor,
    fetch_signoz_observed_keys,
)


class TestDetect:
    def test_registered_keys_produce_no_findings(self):
        observed = dict.fromkeys(TELEMETRY_SCHEMA, 1)
        assert TelemetryDriftAuditor().detect(observed) == []

    def test_unknown_key_is_flagged(self):
        findings = TelemetryDriftAuditor().detect({"trading.session_id": 7})
        assert findings == [DriftFinding(DRIFT_KIND_UNKNOWN_KEY, "trading.session_id", 7)]

    def test_non_trading_keys_are_ignored(self):
        # http.* / db.* belong to library instrumentation, not this schema.
        assert TelemetryDriftAuditor().detect({"http.method": 99, "db.system": 5}) == []

    def test_budget_exceeded_only_with_cardinalities(self):
        # trading.symbol budget is 50 in the shipped schema.
        findings = TelemetryDriftAuditor().detect({"trading.symbol": 1}, {"trading.symbol": 999})
        assert findings == [DriftFinding(DRIFT_KIND_BUDGET_EXCEEDED, "trading.symbol", 999)]

    def test_within_budget_is_not_flagged(self):
        assert TelemetryDriftAuditor().detect({}, {"trading.symbol": 10}) == []

    def test_unbounded_sentinel_never_budget_flags(self):
        # trading.trace_id carries the 0 (unbounded) sentinel — any count is fine.
        assert TelemetryDriftAuditor().detect({}, {"trading.trace_id": 10_000_000}) == []


class TestRecorder:
    def test_records_only_trading_prefixed_keys(self):
        auditor = TelemetryDriftAuditor()
        auditor.record_key("trading.symbol")
        auditor.record_key("trading.symbol")
        auditor.record_key("http.method")  # ignored — not trading.*
        assert auditor.observed_snapshot() == {"trading.symbol": 2}


class TestDedup:
    def test_each_tag_reported_once(self):
        auditor = TelemetryDriftAuditor()
        assert auditor.unreported(auditor.detect({"trading.session_id": 1}))  # first: fresh
        assert auditor.unreported(auditor.detect({"trading.session_id": 2})) == []  # deduped

    def test_seed_and_snapshot_roundtrip(self):
        auditor = TelemetryDriftAuditor()
        auditor.seed_reported(["unknown_key:trading.session_id"])
        assert auditor.unreported(auditor.detect({"trading.session_id": 1})) == []
        assert "unknown_key:trading.session_id" in auditor.reported_tags()


class TestB2FetchSeam:
    async def test_noop_when_url_unset(self):
        class _Settings:
            SIGNOZ_QUERY_URL = ""

        assert await fetch_signoz_observed_keys(_Settings()) == ({}, {})

    async def test_configured_but_unwired_fails_open(self):
        class _Settings:
            SIGNOZ_QUERY_URL = "https://example.signoz.cloud/query"

        # The seam must return empty (never raise) until it is wired.
        assert await fetch_signoz_observed_keys(_Settings()) == ({}, {})


class TestTelemetryIntegration:
    def test_attrs_records_when_drift_enabled(self, monkeypatch):
        auditor = TelemetryDriftAuditor()
        monkeypatch.setattr(telemetry, "_drift_enabled", True)
        monkeypatch.setattr(telemetry, "_auditor", auditor)
        telemetry._attrs(symbol="BTC/USD", side="buy")
        assert auditor.observed_snapshot() == {"trading.symbol": 1, "trading.side": 1}

    def test_attrs_does_not_record_when_disabled(self, monkeypatch):
        auditor = TelemetryDriftAuditor()
        monkeypatch.setattr(telemetry, "_drift_enabled", False)
        monkeypatch.setattr(telemetry, "_auditor", auditor)
        telemetry._attrs(symbol="BTC/USD")
        assert auditor.observed_snapshot() == {}

    def test_start_drift_auditor_noop_when_telemetry_disabled(self, fake_redis):
        # Mirrors the gauge-poller no-op contract: nothing starts while off.
        telemetry.start_drift_auditor(fake_redis)
        assert telemetry._drift_task is None
