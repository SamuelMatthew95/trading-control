# Runbooks

Incident-response procedures for trading-control. Each runbook follows the
same shape: **Symptoms → Impact → Triage → Mitigate → Resolve → Prevent**.

| Runbook | Page when |
|---|---|
| [bot-stopped.md](bot-stopped.md) | API down / agents silent / no heartbeats |
| [broker-unavailable.md](broker-unavailable.md) | Alpaca errors, order placement failing |
| [database-unavailable.md](database-unavailable.md) | Postgres unreachable / memory-mode fallback engaged |
| [high-latency.md](high-latency.md) | p95 latency alerts (HTTP, broker, agent processing) |
| [failed-deployment.md](failed-deployment.md) | Deploy/rollout broken on Render or Kubernetes |
| [monitoring-outage.md](monitoring-outage.md) | SigNoz/collector down — flying blind |
| [trade-failures.md](trade-failures.md) | `trades_failed_total` spiking, DLQ filling |
| [alert-handling.md](alert-handling.md) | How to take, work, and close any alert |

First principles for this system:

1. **Stop the bleeding first.** The kill switch halts all order placement
   instantly and survives restarts:
   `redis-cli set kill_switch:active 1` (clear with `del`).
2. **Paper account.** Default deployments trade paper money — bias toward
   investigation over panic, but treat every incident as if it were live.
3. **Redis is the hard dependency.** Postgres loss degrades gracefully
   (memory mode); Redis loss stops the platform — and that is intentional
   (fail closed).
4. **Everything is traceable.** Grab the `trace_id` from any log/row/event
   and follow it through logs, DB (`agent_runs.trace_id`), and SigNoz
   (`trading.trace_id` span attribute).
