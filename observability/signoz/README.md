# SigNoz — Local Observability Backend

SigNoz ingests everything the backend exports over OTLP: traces (FastAPI,
Redis, SQLAlchemy, aiohttp, per-agent pipeline spans), the trading metrics
catalog, and JSON logs with `otel_trace_id` correlation.

## 1. Deploy SigNoz (free, local)

SigNoz ships a maintained Docker Compose bundle (ClickHouse + collector +
query service + UI):

```bash
git clone -b main https://github.com/SigNoz/signoz.git ~/signoz
cd ~/signoz/deploy/docker
docker compose up -d
```

- UI: <http://localhost:8080> (older releases: 3301)
- OTLP ingest: `localhost:4317` (gRPC) / `localhost:4318` (HTTP)

## 2. Point the backend at it

```bash
# .env (or compose / k8s env)
OTEL_ENABLED=true
OTEL_SERVICE_NAME=trading-control
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

Running the API inside Docker Compose? The default in `docker-compose.yml`
already targets `host.docker.internal:4317`. On Kubernetes (Kind), use the
collector's cluster-reachable address.

Restart the backend and confirm:

```bash
curl -s localhost:8000/health | head -1          # app up
# SigNoz → Services: "trading-control" appears within ~1 min of traffic
```

## 3. Log shipping (optional)

The app writes structured JSON to stdout with `otel_trace_id` /
`otel_span_id` on every line that runs inside a span. Ship container stdout
with the logs pipeline of the SigNoz collector (already configured in their
compose bundle for Docker via `filelog`/`docker_stats`), or in Kubernetes via
the SigNoz k8s-infra chart. No app changes needed.

## 4. Dashboards

Import the JSON files from `dashboards/` (SigNoz → Dashboards → New →
Import JSON). SigNoz's dashboard schema evolves; if an import is rejected,
recreate the panels from this spec — the queries are the contract:

### System Dashboard (`dashboards/system.json`)
| Panel | Query |
|---|---|
| CPU | `system_cpu_utilization` (host metrics from collector) |
| Memory | `system_memory_usage` |
| Request rate | `http_server_duration_count` rate, group by `http_route` |
| Error rate | `http_server_duration_count` rate filtered `http_status_code >= 500` |
| p95 latency | `http_server_duration` p95 by `http_route` |

### Trading Dashboard (`dashboards/trading.json`)
| Panel | Query |
|---|---|
| Signals/min | `signals_generated_total` rate, group by `trading.symbol` |
| Trades submitted vs completed | `trades_submitted_total`, `trades_completed_total` rates |
| Trade failures | `trades_failed_total` rate, group by `trading.symbol` |
| Win rate | `win_rate` (gauge, latest) |
| Daily PnL | `daily_pnl` (gauge, latest) |
| Account balance | `account_balance` (gauge, latest) |
| Open positions | `open_positions` (gauge, latest) |
| Execution latency p95 | `trade_execution_duration` p95 |
| Agent processing p95 | `agent_process_duration` p95, group by `trading.agent` |

### Broker Dashboard (`dashboards/broker.json`)
| Panel | Query |
|---|---|
| API latency p50/p95/p99 | `broker_api_latency` percentiles, group by `trading.operation` |
| Call failures | `broker_api_latency_count` rate filtered `trading.success = false` |
| Retries | `retry_count` rate, group by `trading.stream` |
| Errors by component | `error_count` rate, group by `trading.component` |
| DB query p95 | `database_query_duration` p95 |

## 5. Trade lifecycle tracing

Every agent dispatch span carries the app-level `trading.trace_id`
attribute. To reconstruct a full trade: Traces → filter
`trading.trace_id = <id>` → you get
`agent.process SIGNAL_AGENT → agent.process REASONING_AGENT →
agent.process execution-engine → broker.place_order → agent.process
GRADE_AGENT` with exact timing of each hop.

## 6. Alerts

See `alerts.md` for the recommended alert rules and thresholds.

## 7. SigNoz Cloud — gateway collector (operation standardization)

When shipping to **SigNoz Cloud** (e.g. `https://artistic-macaw.us2.signoz.cloud`)
instead of a local SigNoz, run a small **gateway collector** between the app and
the cloud. Config: [`otel-collector-config.yaml`](./otel-collector-config.yaml).
It does two things the app cannot do for itself:

1. **Normalizes high-cardinality operation names/attributes** before they reach
   ClickHouse, so the *Services → Operations* table aggregates correctly:
   - `agent.process challenger-<hex>` → `agent.process challenger-<id>` (one row
     for every dynamically-spawned challenger, not one per random uuid)
   - `SET XADD PUBLISH … XTRIM` (variable-length Redis pipeline concatenation) →
     `SET XADD PUBLISH XTRIM`
   - the same random id carried on the `trading.agent` attribute is collapsed
     too (the real active-time-series driver).
2. **Generates uniform R.E.D. metrics** (`calls` + `duration`) from those spans
   via the `spanmetrics` connector — identical latency buckets and a fixed
   dimension allowlist for every operation.

### Additive, not RED-only

This service's dashboards depend on **domain metrics that cannot be derived from
spans** — `daily_pnl`, `win_rate`, `account_balance`, `open_positions`,
`signals_generated_total`, `trades_{submitted,completed,failed}_total`,
`broker_api_latency`, `trade_execution_duration`. The collector runs RED
generation **alongside** the app's OTLP metrics; it does **not** disable app
metrics, apply a keep-only-`http.*` whitelist, or drop non-RED metrics (the
generic multi-service "factory" pattern would erase the Trading/Broker
dashboards). The `spanmetrics` `dimensions` list *is* the schema allowlist — it
keeps the `trading.*` dimensions so RED can be sliced by symbol / agent /
operation just like the domain metrics.

### Run it

Use the **contrib** image — the `transform` processor and `spanmetrics`
connector are not in the core `opentelemetry-collector` distribution:

```bash
export SIGNOZ_INGESTION_KEY=<your-key>      # SigNoz → Settings → Ingestion
docker run --rm -p 4317:4317 -p 4318:4318 -p 13133:13133 \
  -e SIGNOZ_INGESTION_KEY \
  -v "$PWD/observability/signoz/otel-collector-config.yaml:/etc/otelcol-contrib/config.yaml:ro" \
  otel/opentelemetry-collector-contrib:latest
```

Then point the app at the collector instead of SigNoz Cloud directly:

```bash
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://<collector-host>:4317   # gRPC; collector forwards to the cloud
```

On Kubernetes, mount the file as a ConfigMap and run the contrib image as a
Deployment in the `observability` namespace — `deploy/k8s/configmap.yaml`
already points the app at `signoz-otel-collector.observability:4317`. On Render,
run the collector as a private service and set the app's
`OTEL_EXPORTER_OTLP_ENDPOINT` to it.

### Verify

```bash
curl -s localhost:13133      # collector health → {"status":"Server available"}
# SigNoz → Services → trading-control → Operations: the challenger rows collapse
# to one, and the Redis pipeline shows a single "SET XADD PUBLISH XTRIM" row.
```

Guardrail: `tests/core/test_otel_collector_normalization.py` keeps the
normalization regexes and the additive (non-destructive) wiring locked in.

> **Why are `GET`/`SET`/`XREADGROUP` shown at ~5 s / ~100% error?** Those are
> blocking-read / pool-timeout signals, not failures — Redis auto-instrumentation
> is off by default for exactly this reason. See
> [`docs/troubleshooting/observability.md`](../../docs/troubleshooting/observability.md).
