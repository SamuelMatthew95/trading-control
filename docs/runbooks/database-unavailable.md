# Runbook — Database Unavailable

## Symptoms
- `/health` shows `database: disconnected`; logs show
  `database_init_attempt_failed` or asyncpg connection errors.
- `database_query_duration` flatlines while traffic continues.

## Impact
**Degraded, not down — by design.** The platform falls back to
`InMemoryStore`: agents keep trading, the dashboard keeps rendering
(`mode: memory` in `/learning/*` responses), Redis keeps the durable bits
(closed trades, agent PnL, decisions). What you lose: the durable audit
trail (`agent_runs`, `orders`, `vector_memory`) for the duration, and
InMemoryStore contents on any restart.

## Triage
```bash
curl -s https://<host>/health | python3 -m json.tool        # database: ?
# Postgres itself:
kubectl -n trading-control exec -it postgres-0 -- pg_isready -U trading   # k8s
# Render: dashboard → trading-control-db → status / metrics (connections, storage)
# Connection exhaustion? (pool is 5+5 per instance)
kubectl -n trading-control exec -it postgres-0 -- psql -U trading trading_control \
  -c "select count(*), state from pg_stat_activity group by state;"
```

| Finding | Action |
|---|---|
| Postgres down/crashlooping | Mitigate A |
| Postgres up, app can't connect | Mitigate B (DNS/secret/network) |
| Storage full | Mitigate C |

## Mitigate
**A.** Restart it (`kubectl rollout restart statefulset/postgres` /
Render restart). The app reconnects automatically with backoff —
no app restart needed.

**B.** Verify `DATABASE_URL` matches reality (`kubectl get cm
trading-control-config -o yaml`), check NetworkPolicy/DNS:
`kubectl -n trading-control exec deploy/api -- python -c "import socket; print(socket.gethostbyname('postgres'))"`.

**C.** Free space fast (truncate oldest `agent_logs` partitions / vacuum),
then grow the volume.

**Do not restart the API while the DB is down** unless forced — a restart
wipes InMemoryStore and with it the only copy of the outage-window state.

## Resolve
- `/health` shows `database: connected`.
- New rows appearing: `select max(created_at) from agent_runs;`
- Note: memory-window data is not backfilled into Postgres; record the gap
  in the incident notes.

## Prevent
- Alert on Postgres disk >80% and connection saturation.
- Long-term: schedule the InMemoryStore→Postgres reconciliation job (known
  gap, accepted for paper trading).
