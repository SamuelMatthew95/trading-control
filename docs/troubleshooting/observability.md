# Observability (OpenTelemetry → SigNoz)

Span/metric instrumentation (`api/telemetry.py`), the gateway collector
(`observability/signoz/otel-collector-config.yaml`), and how SigNoz's
Services / Operations views are populated.

---

## SigNoz "Top Operations" fragmented by high-cardinality span names

**Symptom:** The Services → Operations table shows dozens of near-identical
rows — one `agent.process challenger-<hex>` per dynamically-spawned challenger
(random uuid), plus multi-line `SET XADD PUBLISH SET XADD PUBLISH … XTRIM` rows
that differ only in repeat count. P50/P95/P99 are split across all of them and
the active-time-series budget balloons.

**Root cause:** Auto-instrumentation names a span by its raw operation id. The
challenger id is a random hex suffix and the Redis pipeline span name is the
concatenation of every command in the batch, so a 3-item and a 6-item pipeline
are two different "operations." Both are unbounded → unbounded cardinality.

**Fix:** A gateway OTel Collector normalizes names/attributes *before* ingest
(`observability/signoz/otel-collector-config.yaml`):
`transform/standardize_operations` rewrites the span `name` and the
`trading.agent` attribute to stable signatures (`agent.process challenger-<id>`,
`SET XADD PUBLISH XTRIM`); the `spanmetrics` connector then emits uniform RED
with a bounded dimension allowlist that still preserves the `trading.*` schema.
Use the `otel/opentelemetry-collector-contrib` image (the `transform` processor
and `spanmetrics` connector are contrib-only).

**Regression test:** `tests/core/test_otel_collector_normalization.py::TestChallengerNameNormalization::test_all_challenger_names_match`

---

## Redis operations reported at ~5000 ms with ~100% error rate

**Symptom:** In a SigNoz export, `GET` / `SET` / `HGETALL` / `XREADGROUP` /
`XREAD` and the Redis pipeline spans all sit at P50 ≈ 5000 ms with 96–100% error
rate, while `agent.process *` and `broker.*` spans are sub-second / 0% error.

**Root cause:** Those 5 s / error spans are blocking-read and pool-acquire
timeouts, not application failures. `REDIS_POOL_TIMEOUT_SECONDS = 5.0` and
`socket_timeout = 5` (`api/redis_client.py`) bound the wait; the ~14 always-on
`XREADGROUP`/`XREAD BLOCK` consumer loops returning empty (plus pool contention)
surface as 5 s spans the instrumentation marks errored. Redis auto-instrumentation
is OFF by default (`OTEL_INSTRUMENT_REDIS=false`, `api/telemetry.py::_instrument_redis`)
precisely because it is the highest-volume / lowest-value span source; the export
that showed these had it switched on.

**Fix:** Read these as expected blocking/timeout signal, not failures — keep
`OTEL_INSTRUMENT_REDIS=false` in normal operation and enable it only to actively
debug Redis. The collector normalization collapses the pipeline variants so the
(expected) signal appears once instead of fractured across rows. If
request/response ops (`GET`/`SET`) are *genuinely* timing out at 5 s, that is
pool exhaustion, not a metrics artifact — size `REDIS_MAX_CONNECTIONS` per the
invariant in `.claude/rules/memory-storage.md` and confirm via `/health` →
`redis_pool` (`in_use_connections == max_connections` is the saturation
signature).

**Regression test:** `tests/core/test_redis_client.py::test_max_connections_covers_worst_case_always_on_consumers`

---

## RED-only "metrics factory" erases the trading dashboards

**Symptom:** After applying a generic multi-service collector standardization
(disable app metrics + keep-only-`http.*` attribute whitelist + drop non-RED
metrics), the Trading and Broker SigNoz dashboards go blank.

**Root cause:** Those dashboards are built on **domain metrics that cannot be
derived from spans** — `daily_pnl`, `win_rate`, `account_balance`,
`open_positions`, `signals_generated_total`, `trades_{submitted,completed,failed}_total`,
`broker_api_latency`, `trade_execution_duration`. RED (`calls`/`duration`) only
expresses request/error/latency; a strict whitelist also strips the `trading.*`
dimensions the panels group by.

**Fix:** Run RED generation **additively** — the `spanmetrics` connector emits
`calls`/`duration` alongside the app's OTLP domain metrics; the app metrics
pipeline is never disabled and no blanket attribute whitelist / metric drop-filter
is applied. The connector's `dimensions` list is the schema allowlist and keeps
`trading.symbol` / `trading.agent` / `trading.operation` / … so RED stays
sliceable like the domain metrics.

**Regression test:** `tests/core/test_otel_collector_normalization.py::TestNonDestructiveGuards::test_app_metrics_pipeline_still_exports_domain_metrics`
