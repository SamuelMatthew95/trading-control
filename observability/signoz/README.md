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
