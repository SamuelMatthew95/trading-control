# Phase 1 — Platform Assessment (Production-Readiness Audit)

**Date:** 2026-06-12
**Scope:** Full repository audit before platform transformation (containerization,
CI/CD, observability, Kubernetes, IaC, automation, security, operations).

---

## 1. Architecture Summary

```
                       ┌────────────────────────────┐
   Vercel (frontend)   │  Next.js 14 dashboard      │
                       └─────────────┬──────────────┘
                                     │ REST + WebSocket
                       ┌─────────────▼──────────────┐
   Render (backend)    │  FastAPI (api/main.py)     │
                       │  gunicorn -w1 + uvicorn    │
                       │  lifespan: api/startup.py  │
                       │  ├─ PricePoller (task)     │
                       │  ├─ 11+ agents (tasks)     │
                       │  └─ AgentSupervisor        │
                       └──────┬─────────────┬───────┘
                              │             │
                   ┌──────────▼───┐   ┌─────▼─────────────┐
                   │ Redis 5      │   │ PostgreSQL 15     │
                   │ Streams + KV │   │ + pgvector        │
                   └──────────────┘   └───────────────────┘
                              │
                   ┌──────────▼─────────────────────┐
                   │ External: Alpaca (paper), LLMs │
                   │ (Gemini/Groq/Anthropic/LM      │
                   │ Studio via Tailscale)          │
                   └────────────────────────────────┘
```

- **Process model:** single web process. All agents and the price poller run as
  asyncio tasks inside the FastAPI lifespan (`api/startup.py`). No separate
  worker deployment.
- **Communication:** agents talk exclusively over Redis Streams; shared mutable
  state in Redis KV; durable records in Postgres (or `InMemoryStore` when
  `USE_MEMORY_MODE=true`).
- **Config:** pydantic-settings (`api/config.py`), comprehensive `.env.example`,
  no hardcoded secrets found.
- **Entry command (production):** `.render/start.sh` →
  `gunicorn api.main:app -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`.

## 2. What Already Exists (and is good)

| Capability | State |
|---|---|
| Structured JSON logging | structlog + `log_structured()` (`api/observability.py`), request-id contextvar |
| Trace-id propagation | App-level `trace_id` flows through every agent event and DB row |
| Health endpoints | `/health`, `/readiness` (with 60s startup grace), `/system/health` |
| CI | `backend-ci.yml` (ruff + pytest matrix py3.10/3.11, pip cache, artifacts on failure), `frontend-ci.yml` (lint, tsc, build, vitest) |
| Tests | 160 test files; guardrail tests enforce schema/constants discipline |
| Config hygiene | pydantic-settings validation; secrets only via env; optional API-key + MCP bearer auth |
| Security middleware | TrustedHostMiddleware + CORS allowlist |
| DB migrations | Alembic (14 revisions) with pg_advisory_lock startup serialization |
| Degraded modes | `USE_MEMORY_MODE`, LLM fail-closed (`reject_signal`), kill switch fails closed |

## 3. Technical Debt Findings

1. **In-memory metrics only.** `MetricsStore` (deques + lock) is process-local,
   lost on restart, not scrapeable, and capped at 300 events. No `/metrics`
   endpoint, no exporter.
2. **No distributed tracing.** The app-level `trace_id` is excellent but
   invisible to any tracing backend; latency breakdown across
   signal → reasoning → execution is unobservable.
3. **Single point of failure by design.** `gunicorn -w 1` with all agents
   in-process: a poller bug can take the API down; no horizontal scaling story
   (agents are not leader-elected, so >1 replica would double-trade).
4. **Platform lock-in.** Deployment is expressible only as `render.yaml`; no
   container image exists, so the system cannot run on k8s, a VM, or locally
   with one command.
5. **CI gaps.** No Docker build/publish, no dependency or container scanning,
   no SBOM, no concurrency-safe deploy pipeline; `ruff check . --fix` in CI
   mutates the checkout instead of failing on diff.
6. **No IaC / automation.** Infra exists only as the Render blueprint; no
   reproducible provisioning (Terraform/OpenTofu/Ansible).
7. **No runbooks.** Troubleshooting docs exist (`docs/troubleshooting/`) but
   are bug-history oriented, not operational ("broker down at 3am") runbooks.
8. **Pinned-but-uneven dependencies.** Some pins exact (`fastapi==0.115.12`),
   some floating (`groq`, `alpaca-py`) — non-reproducible builds.

## 4. Missing Production Capabilities

| Gap | Phase that closes it |
|---|---|
| Container image (multi-stage, non-root, healthcheck) | 2 |
| One-command local stack (api+postgres+redis) | 2 |
| Image build/publish pipeline, caching, scanning | 3, 8 |
| OpenTelemetry traces + OTLP metrics + trade-lifecycle spans | 4 |
| Metrics catalog (signals/trades/PnL/latency counters & histograms) | 4 |
| SigNoz backend + dashboards + alert rules | 4 |
| Kubernetes manifests (probes, HPA, PDB, limits, secrets) | 5 |
| OpenTofu modules + environment separation + state strategy | 6 |
| Ansible provisioning/deploy playbooks (idempotent) | 7 |
| Dependency/container/secret scanning, security headers | 8 |
| Incident runbooks | 9 |
| Platform documentation set | 10 |

## 5. Recommended Implementation Plan

Incremental, one phase per commit series, never touching trading logic:

1. **Phase 2 — Containerize.** Multi-stage `Dockerfile` (python:3.11-slim,
   non-root, HEALTHCHECK → `/health`), `.dockerignore`, `docker-compose.yml`
   (api + pgvector/pg15 + redis:7), `docker-compose.dev.yml` (bind mount +
   `uvicorn --reload`). Zero code changes — the app already reads `PORT`,
   `DATABASE_URL`, `REDIS_URL` from env.
2. **Phase 3 — CI/CD.** Keep `backend-ci.yml` (it is the contract the repo's
   guardrails assume); add `docker-build.yml` (buildx + GHA cache + GHCR
   publish on main, PR build-only) and a reusable workflow architecture doc.
3. **Phase 4 — Observability.** Additive `api/telemetry.py` (OTel optional —
   no-op when SDK absent or `OTEL_ENABLED=false`), trade-lifecycle spans via
   small decorators in agents, OTLP metric instruments matching the required
   catalog, SigNoz deploy docs + dashboards + alerts. The existing
   `log_structured` gains trace/span ids automatically via processor.
4. **Phase 5 — Kubernetes.** `deploy/k8s/` manifests + Kind config; single
   API replica (documented: agents are not leader-elected), HPA bounded
   1–1 for the bot but demonstrated on the API tier, PDB, probes mapping to
   `/health` and `/readiness`.
5. **Phase 6 — OpenTofu.** `infra/opentofu/` modules (network/compute/
   database/monitoring) + `environments/{local,dev,prod}`; local env drives
   Docker provider so it is actually runnable and free.
6. **Phase 7 — Ansible.** `infra/ansible/` idempotent playbooks: provision,
   docker, kind/kubectl, app deploy, monitoring, updates, verification;
   example inventories.
7. **Phase 8 — Security.** `security-scan.yml` (pip-audit, Trivy fs+image,
   gitleaks), security headers middleware, SBOM, findings report.
8. **Phase 9 — Operations.** Eight runbooks under `docs/runbooks/`.
9. **Phase 10 — Documentation.** Platform doc set under `docs/` + README
   surgery.

**Constraints honored throughout:** no rewrite of trading logic; all new `api/`
files swept for `FieldName` compliance and added to `CLEAN_FILES`; CI mirror
(`ruff` + split pytest subsets) run before every push.
