# Architecture

## System layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PRESENTATION   Next.js 14 dashboard (Vercel) — REST hydrate + WebSocket │
├─────────────────────────────────────────────────────────────────────────┤
│ API            FastAPI · TrustedHost/CORS/security headers · request-id │
│                middleware · /health /readiness probes · MCP mount       │
├─────────────────────────────────────────────────────────────────────────┤
│ TRADING CORE   7-agent event pipeline over Redis Streams:               │
│   market_ticks → SignalGenerator → signals → ReasoningAgent (LLM)       │
│   → decisions → ExecutionEngine → executions/trade_performance          │
│   → GradeAgent → ICUpdater / ReflectionAgent → StrategyProposer         │
│   → proposals → ProposalApplier (closes the self-evolving loop)         │
│   Safety: kill switch (fail-closed) · risk gates · DLQ · idempotency    │
├─────────────────────────────────────────────────────────────────────────┤
│ STATE          Redis (streams + KV control plane + paper broker)        │
│                PostgreSQL 15 + pgvector (durable audit, vector memory)  │
│                InMemoryStore (Postgres-outage fallback, by design)      │
├─────────────────────────────────────────────────────────────────────────┤
│ TELEMETRY      OpenTelemetry (opt-in) → OTLP → SigNoz                   │
│                spans: HTTP, agent.process, broker.*, SQL, Redis         │
│                metrics: trading catalog · logs: structlog JSON + ids    │
├─────────────────────────────────────────────────────────────────────────┤
│ PLATFORM       Docker → {Compose, Kind/k8s, Render} · OpenTofu modules  │
│                Ansible playbooks · GitHub Actions (test/build/scan)     │
└─────────────────────────────────────────────────────────────────────────┘
```

## Load-bearing design decisions

1. **Single trading process.** Agents are asyncio tasks inside the API
   lifespan, not separate deployments. Pro: zero infra for exactly-once
   stream consumption. Cost: horizontal scaling requires the documented
   split (singleton worker + stateless API) — encoded in `deploy/k8s/`
   (Recreate, replicas 1, PDB maxUnavailable 0, HPA pinned).
2. **Fail closed everywhere money moves.** Redis down → kill-switch check
   raises → order to DLQ. LLM down → `REJECT`, not a heuristic trade.
   Unknown schema → DLQ. The platform layer preserves these invariants
   (e.g. rollouts never run two traders).
3. **Two trace systems, one key.** The app-level `trace_id` (every event,
   every DB row) predates OTel and stays authoritative; OTel spans carry it
   as `trading.trace_id`, so SigNoz, logs, and Postgres all join on the
   same identifier.
4. **Telemetry is additive and optional.** `api/telemetry.py` no-ops without
   `OTEL_ENABLED=true`; business gauges come from a read-only Redis poller
   rather than hooks in the trading path. Observability can never break
   trading.
5. **Postgres is degradable, Redis is not.** Explicit storage contract
   (`.claude/rules/memory-storage.md`): InMemoryStore substitutes for
   Postgres only; Redis loss halts trading deliberately.

## Request/event lifecycles

**Trade lifecycle** (each arrow is a Redis stream hop, each hop a span):
```
price poll → market_ticks → signal (RSI/ATR/momentum) → LLM decision
  (constitution + evolved directive + tool calls) → risk gates → order
  (idempotency key + symbol lock) → broker fill → PnL → grade → IC weights
  / reflection → proposals → applied evolution → next decision
```

**Dashboard hydration**: REST `GET /dashboard/state` (Postgres or
InMemoryStore + Redis enrichment) on load/reconnect, then WebSocket push.

## Deployment topologies

| Topology | Path | Use |
|---|---|---|
| Compose | `docker-compose.yml` (+ `.dev`) | local prod-like / hot-reload dev |
| Kubernetes | `deploy/k8s/` on Kind | platform validation, ops drills |
| Render | `render.yaml` | the live deployment |
| OpenTofu | `infra/opentofu/environments/*` | IaC-managed Docker hosts |

All four run the same image contract: env-config (12-factor), `PORT`,
`/health` + `/readiness`, non-root uid 10001, single worker.
