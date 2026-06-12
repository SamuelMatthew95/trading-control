# Runbook — Bot Stopped

## Symptoms
- `/health` times out or connection refused; SigNoz "API down" (P1) firing.
- Dashboard shows all agents OFFLINE; no `signals_generated_total` movement.
- Render/k8s shows the service restarting or crashed.

## Impact
No trading, no monitoring of open positions. Open paper positions remain at
the broker but are unmanaged (no stops adjusted, no exits).

## Triage (5 min)
```bash
# Is the process up?
curl -sv --max-time 5 https://<host>/health
# Kubernetes:
kubectl -n trading-control get pods
kubectl -n trading-control describe pod -l app.kubernetes.io/name=api | sed -n '/Events/,$p'
kubectl -n trading-control logs deploy/api --previous --tail=100
# Render: dashboard → service → Logs (look for the last structured log line)
# Docker compose:
docker compose ps && docker compose logs --tail=100 api
```

Classify:
| Finding | Go to |
|---|---|
| `CrashLoopBackOff` / repeated tracebacks at startup | Mitigate A |
| OOMKilled in pod events | Mitigate B |
| Process up but `/health` "degraded", agents dead | Mitigate C |
| Node/host down | reschedule (k8s does this) / restart host |

## Mitigate
**A — crash loop on startup.** Read the traceback. Most common causes:
bad env (settings validation raises), unreachable Redis (hard dependency),
migration failure. Fix the input, not the symptom; if a bad deploy caused it
→ [failed-deployment.md](failed-deployment.md) and roll back.

**B — OOM.** Restart restores service immediately; then raise the memory
limit (k8s: `resources.limits.memory`, compose: host) and look for the leak
in SigNoz memory panel before closing.

**C — zombie API (HTTP alive, agents dead).** The AgentSupervisor restarts
crashed agents automatically; if it hasn't:
```bash
curl -s https://<host>/system/health | python3 -m json.tool   # which agent died
kubectl -n trading-control rollout restart deploy/api          # full clean restart
```

## Resolve
- `/health` returns `healthy`; `/readiness` returns `ready`.
- Dashboard shows all agents ACTIVE within 2 min (heartbeat TTL).
- A new `system_startup_status` log line lists the full agent fleet.
- Check open positions reconcile: `GET /positions` matches broker state.

## Prevent
- Every crash gets a regression test (repo rule) and an entry in
  `docs/troubleshooting/`.
- Verify liveness/startup probes weren't the killer (probe timeout during a
  slow migration → lengthen `startupProbe.failureThreshold`).
