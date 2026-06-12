# Runbook — High Latency

## Symptoms
- SigNoz p95 alerts: HTTP (`http_server_duration`), broker
  (`broker_api_latency`), agent (`agent_process_duration`), or DB
  (`database_query_duration`).
- Signal→fill exceeding the 5s SLO (`trade_execution_duration`).

## Impact
Stale executions (fills far from decision price), WebSocket dashboard lag,
stream backlog growth. Latency in this system compounds: a slow stage delays
every stage behind it on the same event loop.

## Triage — find WHICH stage first
```bash
# One query answers it: agent processing p95 grouped by agent (SigNoz,
# Trading dashboard "Agent processing p95" panel). Then:
```
| Slow signal | Likely cause | Check |
|---|---|---|
| `agent.process REASONING_AGENT` | LLM provider slow | `GET /llm/health` — `last_latency_ms`, rate limits; provider status page |
| `broker.place_order` | Alpaca degradation | [broker-unavailable.md](broker-unavailable.md) |
| `database_query_duration` | Postgres saturation | `pg_stat_activity`, slow query log, Render plan limits |
| everything at once | event-loop starvation or CPU throttling | `kubectl top pod` vs limits; a blocking call snuck into async code |
| HTTP only, pipeline fine | dashboard fan-out queries | `GET /system/health` telemetry block |

Stream lag confirms pipeline impact:
```bash
curl -s https://<host>/system/health | python3 -m json.tool   # stream lag section
```

## Mitigate
- **LLM slow:** the router already degrades reason→instruct model under
  throttle. If p95 stays >30s, switch provider (`LLM_PROVIDER` env) or rely
  on fail-closed mode — do NOT raise `LLM_TIMEOUT_SECONDS` as a fix.
- **CPU throttled:** raise the k8s CPU limit (currently 1 core) — watch
  `container_cpu_cfs_throttled_periods` first to confirm.
- **DB:** kill runaway queries (`pg_terminate_backend`), add the missing
  index offline, never under incident pressure.
- **Backlog already huge:** consider the kill switch while it drains —
  executing minutes-old decisions is worse than not executing.

## Resolve
p95s back under: HTTP 500ms, broker 2s, reasoning 15s, DB 100ms — and
stream lag ~0. Watch one full signal→fill trace in SigNoz to confirm.

## Prevent
Per-stage latency budgets are encoded as alerts #4/#10 in
`observability/signoz/alerts.md`; update them when SLOs change.
