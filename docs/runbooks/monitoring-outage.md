# Runbook — Monitoring Outage

## Symptoms
- SigNoz UI down, or all panels empty while the app is demonstrably fine.
- App logs: OTLP export warnings (`Failed to export ...`).
- The tell: **every** metric stopped at the same instant = monitoring died,
  not the app.

## Impact
No dashboards, no alerts — flying blind. **Trading is unaffected**: OTel
exporters are non-blocking and the gauge poller swallows failures. The real
risk is a trading incident occurring *while* monitoring is out.

## Triage
```bash
# Prove the app is fine first (direct, no SigNoz):
curl -s https://<host>/health | python3 -m json.tool
curl -s https://<host>/system/health | python3 -m json.tool   # built-in telemetry
# SigNoz stack:
docker compose -f ~/signoz/deploy/docker/docker-compose.yaml ps
docker compose -f ~/signoz/deploy/docker/docker-compose.yaml logs --tail=50 otel-collector clickhouse query-service
```
Common causes: ClickHouse disk full, collector OOM, retention misconfig.

## Mitigate
1. **Establish manual watch:** until alerts are back, poll the built-ins —
   `/health`, `/system/health` (error rate, latency, stream lag), and the
   dashboard. The app's own `MetricsStore` keeps working with no collector.
2. Restart the failed SigNoz component:
   `docker compose ... restart otel-collector` (or the full stack).
3. ClickHouse disk full → lower retention (SigNoz → Settings → Retention)
   and prune; then resize.

## Resolve
- Fresh datapoints in SigNoz; fire a test alert (temporary 0-threshold rule)
  to prove the alert→notification path end-to-end, then remove it.
- Backfill check: traces/metrics during the outage are lost (OTLP is
  fire-and-forget) — note the blind window in the incident record.

## Prevent
- Dead-man's-switch style alert (#1 in `alerts.md`) on an external uptime
  checker (UptimeRobot free tier) pointing at `/health` — monitoring for the
  monitoring.
- Disk alerts on the SigNoz host itself.
