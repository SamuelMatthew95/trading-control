# Runbook — Broker Unavailable

## Symptoms
- `broker_api_latency{success="false"}` rate alert (P2) or
  `trades_failed_total` spike.
- Logs: `Alpaca order rejected`, `network error, retrying`, aiohttp timeouts
  from `api/services/execution/brokers/alpaca.py`.

## Impact
Orders fail or hang; decisions keep flowing in and will retry → DLQ. Paper
broker (`BROKER_MODE=paper`) is Redis-backed and is NOT affected by Alpaca
outages — confirm which broker is actually in use first.

## Triage
```bash
# Which broker mode?
curl -s https://<host>/health | grep -o '"broker[^,]*'
# Alpaca status page + direct probe:
curl -s https://paper-api.alpaca.markets/v2/clock -H "APCA-API-KEY-ID: $KEY" -H "APCA-API-SECRET-KEY: $SECRET"
# Are failures auth (401/403), rate limit (429), or outage (5xx/timeouts)?
kubectl -n trading-control logs deploy/api --tail=200 | grep -i alpaca
```

## Mitigate
| Cause | Action |
|---|---|
| Alpaca outage (5xx/timeout) | Engage kill switch if failures are partial/inconsistent: `redis-cli set kill_switch:active 1`. Full outage needs nothing — orders already fail closed into the DLQ. |
| 401/403 | Keys rotated/expired. Update the secret (Render env / k8s Secret), restart. Never paste keys into shell history — use `kubectl create secret ... --from-file`. |
| 429 rate limit | Sustained 429 means a runaway loop — find the caller in SigNoz (`broker.get_*` span rate), don't just raise limits. |

## Resolve
- `broker_api_latency` success rate back to ~100%; DLQ drained
  (`/dlq` endpoint or `redis-cli keys 'dlq:*'`), replays processed.
- Clear the kill switch **deliberately**: `redis-cli del kill_switch:active`
  and watch the first new decision execute cleanly.

## Prevent
- Alerts #4/#5 in `observability/signoz/alerts.md` catch degradation before
  hard failure.
- Broker calls already carry timeouts and exponential backoff; if a new
  failure mode appeared, add it to `docs/troubleshooting/execution-engine.md`
  with a regression test.
