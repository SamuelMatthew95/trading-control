# Observability

Three signals, one pipeline: **OpenTelemetry → OTLP → SigNoz**.
Everything is opt-in via `OTEL_ENABLED=true` — with the flag off (default)
the hooks are no-ops and the app behaves exactly as before.

## Quickstart — see production metrics in ~10 minutes (no servers, no cloning)

This is the recommended path for the Render deployment. You host nothing.

1. **Sign up at [signoz.io](https://signoz.io) → SigNoz Cloud.** After
   signup, copy two things from Settings → Ingestion: your **ingestion key**
   and your **region** (`us` / `eu` / `in`).
2. **Render dashboard → your service → Environment → add five vars** (these
   mirror SigNoz's own onboarding guide, including their documented
   `http/protobuf` protocol):
   ```
   OTEL_ENABLED=true
   OTEL_EXPORTER_OTLP_ENDPOINT=https://ingest.<region>.signoz.cloud:443
   OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
   OTEL_EXPORTER_OTLP_INSECURE=false
   OTEL_EXPORTER_OTLP_HEADERS=signoz-ingestion-key=<your-key>
   ```
   Optional sixth, for deploy markers on every chart (the SDK reads it
   natively): `OTEL_RESOURCE_ATTRIBUTES=service.version=<RENDER_GIT_COMMIT>`.
   Saving triggers a redeploy automatically.
3. **Verify it took:** Render → Logs → look for one line:
   `telemetry_initialized`. (If you see `telemetry_disabled`, the
   `OTEL_ENABLED` var didn't apply.)
4. **Open SigNoz Cloud in your browser.** Within ~2 minutes of traffic:
   **Services** shows `trading-control`; **Traces** shows each trade's full
   journey with per-hop timing; **Dashboards → Import JSON** — load the
   three files from `observability/signoz/dashboards/` for the Trading /
   System / Broker views; alert rules to create are in
   `observability/signoz/alerts.md`.

**To turn it all off:** set `OTEL_ENABLED=false`. Telemetry is fail-open by
design — if SigNoz is unreachable, the app logs a warning and trades on.

Notes, so there are no surprises:
- SigNoz Cloud is a paid product with a free trial — check current pricing.
  The self-hosted route below is permanently free in exchange for you
  operating it.
- The app speaks both OTLP protocols: `http/protobuf` (what SigNoz Cloud's
  onboarding documents — use it there) and `grpc` (default, for local
  collectors on :4317). Pick via `OTEL_EXPORTER_OTLP_PROTOCOL`.
- Fork-safety: telemetry initializes inside the FastAPI lifespan — i.e. in
  the gunicorn worker *after* fork — which is exactly what the OTel docs
  require. Don't enable OTEL with `uvicorn --reload` (hot reload spawns
  processes that break instrumentation; the dev compose leaves it off).

```
┌──────────────────────── trading-control (FastAPI) ────────────────────────┐
│ traces   FastAPI auto-instr + agent.process spans + broker.* spans       │
│ metrics  trading catalog (counters/histograms/gauges)                    │
│ logs     structlog JSON + otel_trace_id/otel_span_id stamps              │
└────────────────────┬──────────────────────────────────────────────────────┘
                     │ OTLP gRPC (OTEL_EXPORTER_OTLP_ENDPOINT, default :4317)
                     ▼
               SigNoz collector ─→ ClickHouse ─→ SigNoz UI (dashboards/alerts)
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `OTEL_ENABLED` | `false` | Master switch. Off → zero overhead, SDK never imported |
| `OTEL_SERVICE_NAME` | `trading-control` | `service.name` resource attribute |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP collector / ingest URL |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` (local collectors, :4317) or `http/protobuf` (SigNoz Cloud, :443) |
| `OTEL_EXPORTER_OTLP_INSECURE` | `true` | Plaintext (local collectors). Set `false` for cloud backends (TLS) |
| `OTEL_EXPORTER_OTLP_HEADERS` | empty | Auth headers, standard `k=v,k2=v2` format (e.g. `signoz-ingestion-key=<token>`) |
| `OTEL_GAUGE_POLL_SECONDS` | `30` | Business-gauge refresh interval |

## Choosing a backend (best-practice ladder)

1. **Managed — SigNoz Cloud (recommended for Render-style deployments).**
   Nothing to host; see the Quickstart at the top of this page. Any OTLP
   backend works — the app speaks both `grpc` and `http/protobuf`
   (`OTEL_EXPORTER_OTLP_PROTOCOL`).
2. **Self-hosted SigNoz** (`observability/signoz/README.md`): permanently
   free, when data control or volume-cost matters and you can operate
   ClickHouse. A real ops commitment, not a default.
3. **Local clone + compose:** development and learning only.

## Where instrumentation lives

All of it is in `api/telemetry.py`; the touch points in existing code are
single lines:

| Signal | Source |
|---|---|
| HTTP server spans | `FastAPIInstrumentor` (`/health`, `/readiness` excluded) |
| Redis / SQL / aiohttp spans | library auto-instrumentation |
| `agent.process <agent>` spans | `BaseStreamConsumer._handle_message` (`api/events/consumer.py`) and `MultiStreamAgent._run` (`api/services/agents/base.py`) — every pipeline agent dispatch |
| `broker.place_order` etc. spans | `@traced_broker_call` on `PaperBroker` / `AlpacaBroker` |
| Trade lifecycle correlation | every agent span carries `trading.trace_id` — the app-level trace id that already flows through all events and DB rows |
| Log correlation | `otel_log_processor` in the structlog chain stamps `otel_trace_id` / `otel_span_id` |

### Tracing a trade end-to-end

1. Grab the `trace_id` from any log line / DB row / dashboard event.
2. SigNoz → Traces → filter `trading.trace_id = <id>`.
3. You see the full lifecycle with per-hop latency:
   `agent.process SIGNAL_AGENT → agent.process REASONING_AGENT →
   agent.process execution-engine → broker.place_order →
   agent.process GRADE_AGENT → …`

## Metrics catalog

| Metric | Type | Labels (`trading.*`) | Fed from |
|---|---|---|---|
| `signals_generated_total` | counter | symbol, signal_type | SignalGenerator publish |
| `trades_submitted_total` | counter | symbol, side, broker | broker `place_order` entry |
| `trades_completed_total` | counter | symbol, side, broker | fill result |
| `trades_failed_total` | counter | symbol, side, broker | rejection / exception |
| `trade_execution_duration` (ms) | histogram | symbol, side | submission → fill |
| `broker_api_latency` (ms) | histogram | operation, broker, success | every broker call |
| `database_query_duration` (ms) | histogram | — | SQLAlchemy cursor events |
| `agent_process_duration` (ms) | histogram | agent | every event dispatch |
| `error_count` | counter | component | consumer failure paths |
| `retry_count` | counter | stream | pre-DLQ retry decisions |
| `agent_decisions_total` | counter | model, action | every finalized reasoning decision (`llm_fallback_ratio`) |
| `agent_decision_flips_total` | counter | symbol | reasoning action changed vs the prior decision |
| `daily_pnl` | gauge | — | Redis poller: today's closed trades |
| `open_positions` | gauge | — | Redis poller: non-flat paper positions |
| `win_rate` | gauge | — | Redis poller: agent PnL accumulators |
| `account_balance` | gauge | — | Redis poller: paper cash |

The four business gauges are computed by a **read-only Redis poller**
(`start_gauge_poller`) so the trading path is never touched — losing the
collector can't affect order flow.

## Logging

Already structured JSON via structlog (`api/observability.py`):
ISO timestamps, level, `request_id` contextvar, dict tracebacks, and (when a
span is active) `otel_trace_id`/`otel_span_id`. Searchable in SigNoz logs by
any attribute; pivot log↔trace via the stamped ids.

## Failure modes (deliberate)

- SDK not installed → one warning, app runs.
- Collector unreachable → OTel batches drop with internal warnings; trading
  unaffected (exporters never block the event loop).
- Gauge poller error → logged warning, retries next interval.

## Local quickstart

```bash
# 1. SigNoz up (see observability/signoz/README.md)
# 2. enable export
export OTEL_ENABLED=true OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
uvicorn api.main:app --port 8000
# 3. generate traffic, then open SigNoz → Services → trading-control
```

Dashboards and alert rules: `observability/signoz/`.
Regression tests for the disabled path: `tests/core/test_telemetry.py`.
