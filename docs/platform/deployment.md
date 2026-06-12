# Deployment Guide

Every supported way to run trading-control, from one-command local to
production. All paths run the same container contract (env config, `PORT`,
`/health`, non-root).

## 1. Docker Compose — fastest full stack

```bash
# prod-like: built image + postgres(pgvector) + redis, healthcheck-gated
docker compose up --build
curl -s localhost:8000/health | python3 -m json.tool

# dev loop: hot reload, DB/Redis ports published, DEBUG logs
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# teardown (keep data) / full wipe
docker compose down        # / docker compose down -v
```

Secrets: put keys in a git-ignored `.env`; compose passes them through.
The stack boots with **no keys at all** — LLM decisions fail closed to
`REJECT` and the paper broker needs nothing.

### Image build details

```bash
docker build -t trading-control-api:local .
docker run --rm -p 8000:8000 -e USE_MEMORY_MODE=true -e REDIS_URL=redis://host.docker.internal:6379/0 trading-control-api:local
```

- Multi-stage: builder venv → `python:3.11-slim` runtime, non-root uid 10001.
- `HEALTHCHECK` polls `/health` (start period 30s).
- Single gunicorn worker **by design** — see `docs/platform/architecture.md`.

### Troubleshooting the container

| Symptom | Cause / fix |
|---|---|
| exits immediately, settings traceback | missing/invalid env — compare `.env.example`; `DATABASE_URL` required unless `USE_MEMORY_MODE=true` |
| `400 Invalid host header` | host not in `ALLOWED_HOSTS` — add the hostname you curl |
| healthy but agents idle | Redis unreachable — check `REDIS_URL` resolves *from inside* the container |
| `vector` extension errors | postgres volume predates the init script: `docker compose down -v` or `CREATE EXTENSION vector;` manually |
| build slow every time | keep BuildKit on; the deps layer caches until `requirements.txt` changes |

## 2. Bare process (no Docker)

```bash
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL, REDIS_URL or USE_MEMORY_MODE=true
uvicorn api.main:app --reload
```

## 3. Kubernetes (Kind) — full guide: [kubernetes.md](kubernetes.md)

```bash
kind create cluster --name trading --config deploy/k8s/kind-config.yaml
kubectl apply -k deploy/k8s/
```

## 4. OpenTofu — full guide: [opentofu.md](opentofu.md)

```bash
cd infra/opentofu/environments/local && tofu init && tofu apply
```

## 5. Ansible — full guide: [ansible.md](ansible.md)

```bash
cd infra/ansible && ansible-playbook playbooks/site.yml
```

## 6. Render (current production)

`render.yaml` blueprint: web service + managed Postgres + Redis,
auto-deploy on main, health-checked at `/health`. Secrets live in the Render
dashboard (`sync: false`). The CI-published GHCR image is not used by Render
(it builds from source) — the image is the portability layer for every other
target.

## Release & rollback summary

| Target | Deploy | Roll back |
|---|---|---|
| Compose | `docker compose up --build -d` | `git checkout <tag> && docker compose up --build -d` |
| k8s | `kubectl set image deploy/api api=ghcr.io/...:sha-<commit>` | `kubectl rollout undo deploy/api` |
| Render | push to main (auto) | dashboard → previous deploy → Rollback |
| OpenTofu | `tofu apply` with new `api_image` | `tofu apply` with previous sha tag |

Always deploy by **immutable sha tag** outside local dev. Full procedures and
the stuck-rollout playbook: [../runbooks/failed-deployment.md](../runbooks/failed-deployment.md).
