# Telemetry Governance System Design (v1)

**Status:** Design — not yet implemented. This document specifies the control
plane that turns the existing, well-instrumented telemetry pipeline into a
*governed* one. It does not change any code; it defines the contracts and the
build order that the follow-up PRs implement.

**Scope:** The governance/evolution layer that sits *around* the telemetry that
already exists — schema registry, drift detection, cost model, SLOs, ownership,
and rollout rules. It is explicitly **not** a collector rewrite, new
instrumentation, or new dashboards. Those are already built:

| Already built | Where |
|---|---|
| Gateway collector + cardinality normalization + additive RED | `observability/signoz/otel-collector-config.yaml` |
| Metrics catalog, trace lifecycle, log correlation | `api/telemetry.py`, `docs/platform/observability.md` |
| Dashboards (System / Trading / Broker) | `observability/signoz/README.md` §4 |
| Threshold alerts (P1–P3, PagerDuty routing) | `observability/signoz/alerts.md` |
| Redis-span suppression (cheaper than Tier-C sampling) | `OTEL_INSTRUMENT_REDIS=false` (`api/telemetry.py::_instrument_redis`) |

---

## 0. Why a governance layer

The system is past the "telemetry design" phase. The remaining risk is **silent
evolution**: a new service attribute, an agent tag, or a library upgrade that
changes instrumentation can expand cardinality (and the SigNoz bill) with no
code review catching it, because today schema correctness is *assumed* and
enforcement is *implicit* (discipline + the normalization guardrail test).

The governance layer makes three things explicit and enforced:

1. **Schema** — which telemetry attributes are approved, and their cardinality budget.
2. **Cost** — what telemetry costs *per unit of business behavior*, not per span.
3. **Service levels** — error budgets, not just point-in-time alerts.

It is a **control plane for telemetry evolution**, owned in code (the repo's
existing pattern: cross-module contracts live in `api/constants.py` and are
locked by guardrail tests).

**Maturity model.** The system has passed Stage 1 (instrumentation), Stage 2
(OTLP pipeline), and Stage 3 (observability platform — dashboards + alerts).
This layer is **Stage 4: governed observability** (schema registry + CI
enforcement + drift + cost + SLO). Stage 5 (autonomous telemetry — auto-sampling,
anomaly-driven instrumentation, self-healing pipelines) is explicitly **out of
scope for v1**: it is only safe once Stage 4 makes evolution observable.

---

## 1. Schema registry

### Source of truth

The telemetry schema is the set of `trading.*` span/metric attributes emitted by
`api/telemetry.py::_attrs()` and consumed as RED dimensions by the collector's
`spanmetrics.dimensions` allowlist. Today that set is implied by two places that
can drift apart. v1 makes it **one declared registry** in `api/constants.py`,
alongside (and distinct from) the existing `FieldName` payload-key registry:

- `FieldName` (≈720 members) = the payload/DB-row/Redis-message **key** registry.
- `TELEMETRY_SCHEMA` (new) = the **telemetry attribute** registry: which
  `trading.*` keys may appear on spans/metrics, and their cardinality budget.

### Format

```python
# api/constants.py  (proposed)
from dataclasses import dataclass

@dataclass(frozen=True)
class TelemetryAttr:
    key: str               # full attribute name, e.g. "trading.symbol"
    cardinality_budget: int  # max distinct values before it is a drift incident
    is_red_dimension: bool   # may be used as a spanmetrics RED label
    owner: str               # team/area accountable (see §6)
    note: str

TELEMETRY_SCHEMA: dict[str, TelemetryAttr] = {
    "trading.symbol":    TelemetryAttr("trading.symbol",    50,  True,  "backend", "approved trading universe"),
    "trading.agent":     TelemetryAttr("trading.agent",     200, True,  "backend", "fleet + challenger-<id> (normalized)"),
    "trading.operation": TelemetryAttr("trading.operation", 30,  True,  "backend", "broker/agent operation names"),
    "trading.side":      TelemetryAttr("trading.side",      4,   True,  "backend", "buy/sell/None"),
    "trading.stream":    TelemetryAttr("trading.stream",    30,  True,  "backend", "Redis stream names"),
    "trading.component": TelemetryAttr("trading.component", 40,  True,  "backend", "error-source components"),
    "trading.broker":    TelemetryAttr("trading.broker",    5,   True,  "backend", "paper/alpaca"),
    "trading.signal_type": TelemetryAttr("trading.signal_type", 20, False, "backend", "metric-only; not a RED dim"),
    "trading.trace_id":  TelemetryAttr("trading.trace_id",  0,   False, "backend", "UNBOUNDED on purpose — span attribute only, NEVER a metric label"),
}
```

Budget rationale: `trading.agent = 200` covers the 7-agent fleet plus up to
`MAX_CONCURRENT_CHALLENGERS` distinct `challenger-<id>` values *before*
normalization — after the collector collapses them to `challenger-<id>` the live
value is ~8, so 200 is the pre-normalization safety ceiling. `trading.symbol`
tracks the approved universe (`SUPPORTED_SYMBOLS`). `trading.trace_id` is the one
deliberately unbounded key: it is a **span attribute for lifecycle search only**
and `cardinality_budget=0` is a sentinel meaning "must never become a metric
label" (the drift auditor treats it as a hard rule, not a numeric budget).

---

## 2. Drift detection

Drift is caught in **two layers** — build-time (robust, blocks the bad change)
and runtime (catches what bypasses CI: library upgrades, dynamic attributes).

### Layer A — build-time guardrail (primary)

A pytest in `tests/core/` — same pattern as
`test_otel_collector_normalization.py` — asserts the registry is the single
source of truth:

1. Every `trading.*` attribute referenced in `api/telemetry.py` `_attrs(...)`
   calls is present in `TELEMETRY_SCHEMA` (AST scan of `_attrs` keyword args).
2. Every `trading.*` name in the collector's `spanmetrics.dimensions` allowlist
   is in `TELEMETRY_SCHEMA` **with `is_red_dimension=True`**.
3. Every registry entry has a positive budget *or* the `0` sentinel + a note.

This makes a new attribute a **failing build**, not a silent cost increase —
exactly how the repo already locks the normalization regexes.

**Optional — PR risk score.** The guardrail is a hard binary block; a softer
companion is a PR scanner that *scores* telemetry changes so reviewers see blast
radius even when a change is allowed:

```text
risk_score = new_attributes              * 5
           + unbounded_cardinality_attrs * 10
           + red_dimension_changes       * 20
# BLOCK when: an attribute is unregistered, a RED dimension changed, or a
# budget/enum is violated.  WARN (annotate the PR) otherwise.
```

It is additive to Layer A (which already blocks the unregistered case); the
score's value is making **RED-dimension changes** — the costliest kind, since
they multiply active time series — loud in review rather than buried in a diff.

### Layer B — runtime auditor (defence in depth) — IMPLEMENTED

`api/telemetry_drift.py` + the audit loop in `api/telemetry.py`, gated by
`OTEL_DRIFT_AUDIT_ENABLED` (default off), interval `OTEL_DRIFT_AUDIT_INTERVAL_SECONDS`.
One auditor, two observation sources:

- **B1 — app-side (built).** Every `trading.*` key is recorded as it passes the
  `_attrs()` choke point; the loop diffs the observed set against
  `TELEMETRY_SCHEMA`. Catches dynamically-keyed / conditional / production-only
  *app* emissions the static Layer-A scan can't see. Does **not** see
  library-injected attributes (`http.*`/`db.*` are added by the instrumentors
  straight to spans, bypassing `_attrs`).
- **B2 — SigNoz-side (seam).** `fetch_signoz_observed_keys()` pulls observed
  label keys + per-key value-cardinality from SigNoz's query API; the same diff
  runs over them. Catches library drift and true cardinality growth. The live
  fetch is a thin adapter you wire (`SIGNOZ_QUERY_URL`/`SIGNOZ_QUERY_KEY`); empty
  URL → B2 is a clean no-op and B1 still runs.

**The drift signal is bounded (the critical rule).** Findings emit a *single*
counter `telemetry_schema_drift_total` labelled only by a 2-value `drift_kind`
(`unknown_key` | `budget_exceeded`); the offending key + count ride in a
structured log line (`telemetry_schema_drift`), **never as a metric label** — a
per-key label would make the detector the cardinality bomb it polices. A
Redis-persisted reported-set (`telemetry:drift:reported`) dedups so a standing
violation pages once across restarts. The loop is read-only and fail-open (a
query error logs a warning and retries next interval — never blocks trading).

Budget breaches require value-cardinality, which only B2 can measure cheaply;
B1 alone reports unknown keys. The unbounded sentinel (`cardinality_budget == 0`,
e.g. `trace_id`) is additionally enforced at *build* time by Layer A — it can
never be a RED dimension.

---

## 3. Cost model

The blind spot today: only LLM **dollar** cost is tracked (`llm:cost:{date}`),
not **telemetry ingest** cost. v1 defines cost as **per unit of business
behavior**, which is what actually predicts the bill.

### Inputs

Enable the collector's own telemetry pipeline (`service.telemetry.metrics`,
scraped into SigNoz) to get ingestion volume at the gateway:

```text
otelcol_exporter_sent_spans{exporter="otlp/signoz"}
otelcol_exporter_sent_metric_points{exporter="otlp/signoz"}
otelcol_exporter_sent_log_records{exporter="otlp/signoz"}
signoz_active_time_series            # from SigNoz Cloud usage / metadata
```

### Derived governance metrics

```text
# 1. Ingestion volume proxy (per signal class)
spans_per_min   = rate(otelcol_exporter_sent_spans)
series_active    = signoz_active_time_series

# 2. Signal efficiency — fraction of telemetry that is business-meaningful
signal_efficiency = rate(signals_generated_total + trades_submitted_total
                         + trades_completed_total + trades_failed_total)
                    / rate(spanmetrics_calls_total)        # all RED calls

# 3. Cost per business event — THE headline number
cost_per_business_event = ingested_units / rate(trades_completed_total)
#   ingested_units = weighted(spans, metric_points, active_series) using the
#   backend's price sheet (SigNoz Cloud bills time series + ingested GB; plug
#   the current rates in as constants so the number is in real currency).

# 4. Structural early-warning
active_series_growth_24h = (series_active - series_active offset 24h) / series_active offset 24h
```

`cost_per_business_event` rising while `trades_completed_total` is flat is the
signature of telemetry bloat (the way observability bills silently explode). It
is the single metric to put on a cost panel and alert on (§5).

---

## 4. SLO model

Alerts answer "is something wrong now?"; SLOs answer "how close are we to
structural failure?". v1 converts the existing metrics into SLIs/SLOs with error
budgets. **Targets below are FRAMEWORK placeholders and must be calibrated
against measured baselines before they go live** — the repo's own data shows the
naive numbers are wrong:

| SLO | SLI (from existing metric) | Proposed target | Calibration note |
|---|---|---|---|
| Stream freshness | message lag p99 | 99% of msgs processed < 2s lag | Verify against real lag histogram |
| Trade execution | `broker_api_latency{operation="place_order"}` p99 | 99.9% < **TBD** | **150ms is unrealistic for a broker round-trip** — calibrate from `broker_api_latency` history; the existing P2 alert uses 5000ms |
| Agent decision | `agent_process_duration{agent="REASONING_AGENT"}` p95 | 95% < **TBD** | **2s is unrealistic** — reasoning is LLM-powered; measured P99 ≈ 66.8s (the spanmetrics top bucket was sized to 120s for exactly this). Either set ~10–30s or split fast-path vs LLM-path SLIs |
| API availability | `http_server_duration_count` presence | 99.9% non-5xx | Maps to alerts.md #1/#9 |

Error-budget framing (example, once targets are calibrated): a 99.9% execution
SLO over 30 days = ~43m of budget; alert on **burn rate** (e.g. 5% of the 30-day
budget consumed in 1h) rather than on a raw threshold crossing. Each SLO links
its runbook in `docs/runbooks/`.

> Calibration is a hard gate, not a nicety: shipping an SLO whose target is
> tighter than the measured P99 guarantees permanent budget burn and trains
> responders to ignore the page. Pull 30 days of `broker_api_latency` and
> `agent_process_duration` percentiles from SigNoz and set targets at a
> defensible multiple of observed P99 — the same discipline that sized the
> RED buckets above measured P99.

---

## 5. Governance alerts

New alerts for the governance signals, added to `observability/signoz/alerts.md`
under a "Governance" group (same severity contract):

| Alert | Condition | Window | Severity |
|---|---|---|---|
| Schema drift — unknown attribute | `rate(telemetry_schema_drift_total{drift_kind="unknown_key"}) > 0` | 1h | P2 |
| Cardinality budget exceeded | `rate(telemetry_schema_drift_total{drift_kind="budget_exceeded"}) > 0` | 6h | P2 |
| Cost per trade anomaly | `cost_per_business_event > 3× rolling_7d_median` | 6h | P2 |
| Active series growth | `active_series_growth_24h > 0.25` | 24h | P2 |
| SLO burn (per SLO) | error-budget burn rate > 5%/1h | 1h | P1/P2 |

Routing unchanged: P1 → pager, P2 → team channel, P3 → digest.

---

## 6. Ownership boundaries

Each layer has exactly one accountable owner so drift has an addressee:

| Layer | Artifact | Owner | Responsibility |
|---|---|---|---|
| Instrumentation | `api/telemetry.py`, `_attrs()` keys | Backend | Emits only registered `trading.*` attributes |
| Schema registry | `TELEMETRY_SCHEMA` in `api/constants.py` | Backend | Approves keys + budgets; reviews registry PRs |
| Collector / RED | `observability/signoz/otel-collector-config.yaml` | Platform | Normalization, dimension allowlist, RED buckets |
| Drift auditor | scheduled job + guardrail test | Platform | Keeps Layer A/B green; triages drift alerts |
| Cost model | derived metrics + cost panel | Platform | Maintains price-sheet constants, cost alerts |
| SLOs | `docs/platform/telemetry-governance.md` §4 + SigNoz | Ops | Calibrates targets, owns burn-rate response |
| Runbooks | `docs/runbooks/` | Ops | One runbook per governance/SLO alert |

The contract: **the producer of an attribute owns its budget**. A new agent that
emits a new tag does not get to expand cardinality silently — it must land a
registry entry (Backend review) before the guardrail will go green.

**Schema location & extraction trigger.** `TELEMETRY_SCHEMA` lives in
`api/constants.py` today per the repo's placement rule (a cross-module contract
with ≥2 consumers). When it outgrows the single `trading.*` namespace or a second
telemetry-emitting service appears, lift `TelemetryAttr` + `TELEMETRY_SCHEMA` into
`api/telemetry_schema.py` and re-export from `constants.py` — zero import churn,
and the Layer-A guardrail catches any breakage. Until that trigger, keeping it in
`constants.py` avoids premature structure.

---

## 7. Rollout rules for new attributes

The lifecycle for introducing any new `trading.*` attribute (the ratchet that
makes drift a deliberate, reviewed act):

1. **Declare** — add a `TelemetryAttr` to `TELEMETRY_SCHEMA` with an explicit
   `cardinality_budget` and `owner`. (If it is also a payload key, add it to
   `FieldName` first per the existing rule.)
2. **Emit** — reference it via `_attrs(...)` in `api/telemetry.py`. Never emit a
   `trading.*` key that is not in the registry.
3. **Decide RED-or-not** — only add it to the collector `spanmetrics.dimensions`
   allowlist if RED must be sliceable by it, and only if `is_red_dimension=True`.
   High-cardinality keys (ids, trace ids) stay **span attributes only**.
4. **Normalize if unbounded** — if the value contains a random id, add a
   `transform` rule (and a case in `test_otel_collector_normalization.py`)
   collapsing it, exactly like `challenger-<id>`.
5. **Guardrail green** — Layer A test passes (registered + budgeted + dims ⊆ registry).
6. **Verify in prod** — after deploy, the drift auditor confirms observed
   cardinality is within budget; no `unknown_attribute_detected_total` for the key.

### New-attribute PR checklist

- [ ] Entry in `TELEMETRY_SCHEMA` with budget + owner
- [ ] Emitted only via `_attrs()`; no raw `trading.*` strings elsewhere
- [ ] RED dimension added **only if** needed and `is_red_dimension=True`
- [ ] Normalization rule + test case if the value can carry a random id
- [ ] `pytest tests/core/test_otel_collector_normalization.py` and the new schema guardrail pass

---

## 8. Build order (priority)

Ordered by ROI ÷ risk, matching the agreed priority:

| # | Deliverable | Risk | Touches | Guardrail it needs |
|---|---|---|---|---|
| 1 | **Drift + schema governance** (`TELEMETRY_SCHEMA`, Layer A test, Layer B auditor) | **Low** — purely additive signal; no sampling/RED change | `api/constants.py`, new `api/services/*`, new test | schema-registry guardrail (Layer A) |
| 2 | **Cost observability** (collector self-telemetry, derived metrics, cost panel + alert) | Low–Med | collector `service.telemetry`, new metrics, `alerts.md` | metric-name + price-sheet test |
| 3 | **SLO formalization** (calibrate targets, define error budgets, burn-rate alerts) | Low (mostly config/docs) | SigNoz config, this doc, runbooks | none (config) |
| 4 | **Agent/LLM observability spec** (LLM spans, token/cost metrics, per-agent telemetry cap) | Low (additive instrumentation) | `api/telemetry.py`, agents | extends schema guardrail |

Each is independently shippable; #1 unblocks the rest by giving them a registry
to register against.

---

## 8.5 Behavioral observability (advanced layer, Stage 4+)

RED + domain metrics catch *crash* and *latency* failure modes. They miss the
trading-specific one: the system stays "green" while its **behavior** degrades —
agents retry more, flip decisions under latency pressure, or thrash across tools.
These are additive instruments (each new attribute registers in
`TELEMETRY_SCHEMA` per §7) and are the natural Stage-4 follow-on to build-order #4:

| Signal | Metric (proposed) | Derived from | Detects |
|---|---|---|---|
| Retry inflation | `retries_per_trade` | `rate(retry_count) / rate(trades_completed_total)` | poison-message / broker churn before it reaches the DLQ |
| Decision instability | `agent_decision_flip_rate` | variance of `action` over `decisions:recent` per symbol | reasoning thrash / prompt regression under load |
| Tool entropy | `tool_call_diversity` | distinct tools per decision (`ToolRegistry` / `tools/call *` spans) | tool-selection degradation as alpha decays |
| Fallback rate | `llm_fallback_ratio` | `model_used == "policy"` share of decisions | silent LLM degradation (the fail-closed path firing) |

The point: a flat `win_rate` with a rising `agent_decision_flip_rate` is the
early signal of strategy drift that no latency or error dashboard shows.

## 9. What NOT to do (honors tested decisions)

These are locked by existing guardrails — the governance layer must not
re-introduce them:

- **No keep-only-`http.*` attribute whitelist / drop-non-RED filter.** It blanks
  the Trading/Broker dashboards (domain metrics like `daily_pnl`/`win_rate`
  cannot be derived from spans). Locked by
  `test_otel_collector_normalization.py::TestNonDestructiveGuards`.
- **No Tier-C "sample 90–99% of idle Redis reads."** The repo already does
  better by *not creating* those spans (`OTEL_INSTRUMENT_REDIS=false`); sampling
  would reintroduce cost and complexity for zero gain.
- **No premature collector tiering.** Cardinality is already bounded by
  normalization + the dimension allowlist; a Tier A/B/C pipeline split is
  speculative abstraction until the registry + cost model prove a need.

---

## 10. Open questions / calibration TODOs

- Pull 30 days of `broker_api_latency{operation="place_order"}` and
  `agent_process_duration{agent="REASONING_AGENT"}` percentiles to set the §4
  SLO targets at a defensible multiple of measured P99.
- Confirm the SigNoz Cloud price sheet (active time series + ingested GB rates)
  to express `cost_per_business_event` in real currency.
- **Wire B2:** implement `fetch_signoz_observed_keys()` against your SigNoz query
  API (endpoint / auth / response shape) — it ships as a fail-open stub. B1
  (app-side) runs today without it.
- ~~In-app vs cron auditor~~ — resolved: in-app task (`start_drift_auditor`,
  parity with the read-only gauge poller).
