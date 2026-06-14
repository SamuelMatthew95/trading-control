"""Runtime telemetry drift auditor — telemetry governance, Layer B.

Layer A (``tests/core/test_telemetry_schema_governance.py``) blocks unregistered
``trading.*`` attributes at BUILD time. This module is the RUNTIME safety net for
what CI can't see:

* **B1 — app-side.** Observed keys are recorded at the ``_attrs()`` choke point
  in ``api/telemetry.py``; this catches conditional / production-only /
  dynamically-keyed app emissions a static scan misses. It does NOT see
  library-injected attributes (FastAPI/SQLAlchemy/redis instrumentors add
  ``http.*`` / ``db.*`` straight to spans, bypassing ``_attrs``).
* **B2 — SigNoz-side.** Observed label keys + per-key value-cardinality pulled
  from SigNoz's query API. Catches library drift and true cardinality growth.
  The live fetch is a thin wired seam (see ``fetch_signoz_observed_keys``).

Both feed one bounded SIGNAL: a single counter (``TELEMETRY_DRIFT_METRIC``)
labelled only by a 2-value ``kind``, plus a structured log line carrying the
offending key — never the key as a metric label, which would make the detector
the cardinality bomb it polices. Design: ``docs/platform/telemetry-governance.md`` §2.

The auditor is pure + injectable: it records, diffs, and dedups, but never emits
metrics/logs itself — ``api/telemetry.py`` supplies that, so the OTel/SigNoz
coupling stays there and this stays unit-testable with plain dicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Any

from api.constants import (
    DRIFT_KIND_BUDGET_EXCEEDED,
    DRIFT_KIND_UNKNOWN_KEY,
    TELEMETRY_ATTR_PREFIX,
    TELEMETRY_SCHEMA,
    TelemetryAttr,
)
from api.observability import log_structured


@dataclass(frozen=True)
class DriftFinding:
    """One drift detection: an unknown key, or a known key over its budget."""

    kind: str  # DRIFT_KIND_UNKNOWN_KEY | DRIFT_KIND_BUDGET_EXCEEDED
    attribute: str  # the trading.* attribute key
    occurrences: int  # seen-count (unknown) or distinct-value count (budget)


class TelemetryDriftAuditor:
    """Diff observed telemetry attributes against the approved schema."""

    def __init__(self, schema: dict[str, TelemetryAttr] | None = None) -> None:
        self._schema = schema if schema is not None else TELEMETRY_SCHEMA
        self._observed: dict[str, int] = {}  # B1: attribute -> seen count
        self._first_seen: dict[str, float] = {}
        self._reported: set[str] = set()  # dedup tags: "{kind}:{attribute}"
        self._lock = Lock()

    # --- B1 recorder (called from the _attrs choke point) -------------------
    def record_key(self, key: str) -> None:
        """O(1) hot-path record of one emitted trading.* attribute key."""
        if not key.startswith(TELEMETRY_ATTR_PREFIX):
            return
        with self._lock:
            self._observed[key] = self._observed.get(key, 0) + 1
            self._first_seen.setdefault(key, time())

    def observed_snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._observed)

    # --- shared diff --------------------------------------------------------
    def detect(
        self,
        observed_counts: dict[str, int],
        cardinalities: dict[str, int] | None = None,
    ) -> list[DriftFinding]:
        """Unknown trading.* keys + (B2 only) keys over their cardinality budget."""
        findings: list[DriftFinding] = []
        for key, count in observed_counts.items():
            if key.startswith(TELEMETRY_ATTR_PREFIX) and key not in self._schema:
                findings.append(DriftFinding(DRIFT_KIND_UNKNOWN_KEY, key, count))
        for key, distinct in (cardinalities or {}).items():
            attr = self._schema.get(key)
            if attr is not None and 0 < attr.cardinality_budget < distinct:
                findings.append(DriftFinding(DRIFT_KIND_BUDGET_EXCEEDED, key, distinct))
        return findings

    # --- dedup (a standing violation pages once, not every cycle) -----------
    def unreported(self, findings: list[DriftFinding]) -> list[DriftFinding]:
        fresh: list[DriftFinding] = []
        with self._lock:
            for finding in findings:
                tag = f"{finding.kind}:{finding.attribute}"
                if tag not in self._reported:
                    self._reported.add(tag)
                    fresh.append(finding)
        return fresh

    def seed_reported(self, tags: list[str]) -> None:
        """Hydrate the dedup set (e.g. from Redis for B2 across restarts)."""
        with self._lock:
            self._reported.update(tags)

    def reported_tags(self) -> list[str]:
        with self._lock:
            return sorted(self._reported)


async def fetch_signoz_observed_keys(settings: Any) -> tuple[dict[str, int], dict[str, int]]:
    """B2 seam — observed label keys + per-key distinct value counts from SigNoz.

    Returns ``({attribute: seen_count}, {attribute: distinct_value_count})``.

    SigNoz's query endpoint/auth and metric-metadata response shape are
    deployment-specific and cannot be verified from CI, so the configured branch
    is intentionally a stub that returns empty until you wire it: hit
    ``settings.SIGNOZ_QUERY_URL`` with ``SIGNOZ_QUERY_KEY`` and parse the response
    into the two dicts above. Until then B2 is a clean no-op (B1 still runs).
    Must never raise — the auditor fails open.
    """
    if not getattr(settings, "SIGNOZ_QUERY_URL", ""):
        return {}, {}
    # >>> WIRE ME: call the SigNoz query API and parse label keys + cardinality.
    log_structured("info", "telemetry_drift_b2_not_wired", url=settings.SIGNOZ_QUERY_URL)
    return {}, {}
