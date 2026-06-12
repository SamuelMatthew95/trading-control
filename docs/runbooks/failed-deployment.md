# Runbook — Failed Deployment

## Symptoms
- Render deploy stuck/failed, or k8s rollout not completing
  (`kubectl rollout status deploy/api` times out).
- New pod crash-looping while the old one is already gone (Recreate
  strategy → brief intentional gap; a *stuck* gap is the incident).
- CI green but runtime broken (env/config drift — the worst kind).

## Impact
During a stuck rollout the bot is down → same impact as
[bot-stopped.md](bot-stopped.md). The kill switch state lives in Redis and
survives deploys.

## Triage
```bash
# Kubernetes
kubectl -n trading-control rollout status deploy/api
kubectl -n trading-control get pods                      # ImagePullBackOff? CrashLoop?
kubectl -n trading-control logs deploy/api --tail=100
kubectl -n trading-control describe pod -l app.kubernetes.io/name=api | sed -n '/Events/,$p'
# Render: dashboard → Deploys → failing deploy → build/runtime logs
```

| Finding | Cause |
|---|---|
| `ImagePullBackOff` | tag doesn't exist / GHCR auth — check `docker-build.yml` run for the commit |
| Settings validation traceback | missing/renamed env var — diff ConfigMap vs `api/config.py` |
| Migration error then crash | Alembic failure (advisory lock means only one instance migrates) |
| Probe failures, app actually fine | probe timing too tight for first-boot migrations |

## Mitigate — roll back first, diagnose second
```bash
# Kubernetes
kubectl -n trading-control rollout undo deploy/api
kubectl -n trading-control rollout status deploy/api
# Or pin the previous immutable tag explicitly:
kubectl -n trading-control set image deploy/api api=ghcr.io/samuelmatthew95/trading-control:sha-<last-good>
# Render: Deploys → last successful → "Rollback to this deploy"
```
Migration partially applied? **Do not** hand-edit schema. Roll the app back
(old code tolerates new columns per the additive-migration convention) and
fix the migration forward in a PR.

## Resolve
- `/health` healthy on the rolled-back version; incident closed only when
  the *forward* fix is merged and deployed cleanly.

## Prevent
- Deploy by immutable `sha-` tags only (enforced in tofu prod; make it habit
  in k8s commands).
- The PR smoke test in `docker-build.yml` boots the image and polls
  `/health` — config-shape regressions should die there; if one escaped,
  extend the smoke test env to cover the variable that broke.
