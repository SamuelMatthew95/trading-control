# Kubernetes Deployment (Kind)

Local, free, production-shaped. Manifests live in `deploy/k8s/`.

## Topology

```
namespace trading-control  (PSS: restricted)
├── api         Deployment ×1 (Recreate) — FastAPI + agent fleet
│               probes: startup+liveness /health, readiness /readiness
│               non-root uid 10001, read-only rootfs, no capabilities
│               HPA (pinned 1–1), PDB maxUnavailable=0
├── postgres    StatefulSet ×1 + headless Service + 2Gi PVC (pgvector/pg15)
├── redis       Deployment ×1 (Recreate) + 1Gi PVC (AOF persistence)
└── ingress     nginx → api  (host: trading.localtest.me)
```

**Why one API replica?** The trading agents and the price poller run inside
the API process and are not leader-elected. Two pods = both consume the same
Redis streams = double trades. `Recreate` strategy + `PDB maxUnavailable: 0`
extend that single-writer invariant to rollouts and node drains. The HPA
exists with `maxReplicas: 1` so the constraint is explicit; the scale-out
path (split agents into a singleton worker Deployment, then HPA the
stateless API) is documented in the manifest comments.

## Bring-up

```bash
# 1. Cluster + ingress controller
kind create cluster --name trading --config deploy/k8s/kind-config.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod -l app.kubernetes.io/component=controller --timeout=120s

# 2. Image — either pull from GHCR (published by CI) or build locally:
docker build -t trading-control-api:local .
kind load docker-image trading-control-api:local --name trading
# (if using the local image, set `image: trading-control-api:local` in api.yaml)

# 3. Secrets (optional — boots without keys, LLM fail-closed)
kubectl create namespace trading-control --dry-run=client -o yaml | kubectl apply -f -
kubectl -n trading-control create secret generic trading-control-secrets \
  --from-literal=GEMINI_API_KEY=... \
  --from-literal=ALPACA_API_KEY=... \
  --from-literal=ALPACA_SECRET_KEY=...

# 4. Everything else
kubectl apply -k deploy/k8s/
```

## Validation

```bash
kubectl -n trading-control get pods -w                      # all Running/Ready
kubectl -n trading-control wait --for=condition=ready pod -l app.kubernetes.io/name=api --timeout=180s
curl -s http://trading.localtest.me/health | python3 -m json.tool
curl -s http://trading.localtest.me/readiness               # "ready"
kubectl -n trading-control logs deploy/api --tail=50        # JSON logs, agents started
kubectl -n trading-control get hpa,pdb,pvc                  # objects healthy
```

Smoke checklist:
- [ ] `/health` returns `database: connected` (or `memory` if `USE_MEMORY_MODE=true`)
- [ ] `/readiness` returns `ready`
- [ ] logs show `system_startup_status` with the agent list
- [ ] `kubectl top pod` (needs metrics-server) within resource requests

## Rollout & rollback

```bash
# Deploy a new image by immutable tag (never re-pull :latest blindly)
kubectl -n trading-control set image deploy/api api=ghcr.io/samuelmatthew95/trading-control:sha-<commit>
kubectl -n trading-control rollout status deploy/api --timeout=180s

# Roll back
kubectl -n trading-control rollout history deploy/api
kubectl -n trading-control rollout undo deploy/api            # previous revision
kubectl -n trading-control rollout undo deploy/api --to-revision=<n>
```

Note: with `Recreate`, a rollout has a brief intentional gap (old pod stops
before new pod starts) — the no-concurrent-traders invariant outranks
zero-downtime here. The kill switch (`kill_switch:active` in Redis) persists
across the gap.

## Operations cheatsheet

```bash
kubectl -n trading-control exec -it deploy/redis -- redis-cli get kill_switch:active
kubectl -n trading-control exec -it postgres-0 -- psql -U trading trading_control -c 'select count(*) from agent_runs;'
kubectl -n trading-control port-forward svc/api 8000:80      # bypass ingress
kubectl -n trading-control describe pod -l app.kubernetes.io/name=api | sed -n '/Events/,$p'
kind delete cluster --name trading                            # teardown
```
