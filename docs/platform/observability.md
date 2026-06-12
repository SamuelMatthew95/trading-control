# Observability

Three signals, one pipeline: **OpenTelemetry → OTLP → SigNoz**.
Everything is opt-in via `OTEL_ENABLED=true` — with the flag off (default)
the hooks are no-ops and the app behaves exactly as before.

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
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP gRPC collector |
| `OTEL_EXPORTER_OTLP_INSECURE` | `true` | Plaintext gRPC (local collectors). Set `false` for cloud backends (TLS) |
| `OTEL_EXPORTER_OTLP_HEADERS` | empty | Auth headers, standard `k=v,k2=v2` format (e.g. `signoz-ingestion-key=<token>`) |
| `OTEL_GAUGE_POLL_SECONDS` | `30` | Business-gauge refresh interval |

## Choosing a backend (best-practice ladder)

1. **Managed (recommended for Render-style deployments):** SigNoz Cloud or
   Grafana Cloud free tier. Nothing to host — set three env vars on the
   service and dashboards appear in the vendor UI:
   ```bash
   OTEL_ENABLED=true
   OTEL_EXPORTER_OTLP_ENDPOINT=ingest.<region>.signoz.cloud:443
   OTEL_EXPORTER_OTLP_INSECURE=false
   OTEL_EXPORTER_OTLP_HEADERS=signoz-ingestion-key=<token>
   ```
2. **Self-hosted SigNoz** (`observability/signoz/README.md`): when data
   control or volume-cost matters and you can operate ClickHouse. This is a
   real ops commitment, not a default.
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
