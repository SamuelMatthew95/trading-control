# Golden Path — Generalizing This Platform for Any Service

This platform layer was built *for* trading-control, but almost none of it is
*about* trading. This document is the design for extracting it into a paved
road any team can adopt — defaults that are production-grade out of the box,
with escape hatches instead of forks.

## The core insight: the platform binds to a contract, not to this app

Everything in `deploy/`, `infra/`, `.github/workflows/`, and
`observability/` depends only on a small behavioral contract. Any service
that satisfies it gets the entire platform for free:

| Contract clause | Why the platform needs it |
|---|---|
| Config via env vars only (12-factor) | compose / k8s / tofu / ansible all inject the same way |
| Listens on `$PORT` | one Dockerfile CMD, one Service/Ingress shape |
| `GET /health` (liveness, answers during warmup) | container HEALTHCHECK, k8s probes, deploy gates, uptime checks |
| `GET /readiness` (deps-aware) | k8s readiness, Ansible verify, rollout gating |
| Structured JSON logs to stdout | log shipping with zero app config |
| OTLP export behind one env flag | observability is opt-in and can never break the app |
| Boots with no secrets (degraded, fail-closed) | CI smoke tests and fresh-clone DX need zero provisioning |

**Action:** publish this table as `CONTRACT.md` in the template. It is the
golden path's API; everything else is implementation.

## What's already generic vs. bespoke (audit of this repo)

| Asset | State | Gap to generic |
|---|---|---|
| `infra/opentofu/modules/*` | ✅ already parameterized (image, name_prefix, URLs as outputs) | none — lift as-is |
| `infra/ansible/playbooks/*` | ✅ inventory-driven, app specifics are vars (`repo_url`, `api_health_url`) | none — lift as-is |
| `.github/workflows/{docker-build,security-scan}.yml` | 🟡 generic logic, hardcoded repo/paths | convert to `workflow_call` with inputs |
| `Dockerfile` | 🟡 generic shape | parameterize the `COPY` package list + worker count |
| `deploy/k8s/*` | 🟡 generic shape, hardcoded names/namespace | restructure as kustomize `base/` + per-app overlay |
| `docker-compose*.yml` | 🟡 generic shape | template the service env block |
| `api/telemetry.py` | 🟡 ~90% generic | split: generic core (init, spans, decorators, gauge poller plumbing) vs. app config (metric names, Redis keys, FieldName) |
| `.gitleaks.toml`, `.trivyignore` | 🟡 mechanism generic, entries app-specific | template ships them empty with the "every entry needs a reason + exit condition" rule |
| `docs/runbooks/*` | 🟡 structure generic, content app-specific | ship as skeletons with the Symptoms→Impact→Triage→Mitigate→Resolve→Prevent frame pre-filled |
| Backend CI (`backend-ci.yml`), FieldName guardrails | ❌ deliberately bespoke | leave per-repo; the golden path must not absorb app-level test policy |

## Three-tier extraction (in order of leverage)

### Tier 1 — Reusable workflows (days, highest leverage)

Move CI logic to a central repo; consumers keep ~10-line callers:

```yaml
# consumer repo: .github/workflows/platform.yml
jobs:
  docker:
    uses: org/platform-workflows/.github/workflows/docker-build.yml@v1
    with:
      image-name: ${{ github.repository }}
      smoke-env: "USE_MEMORY_MODE=true"   # how to boot WITHOUT real deps
    secrets: inherit
  security:
    uses: org/platform-workflows/.github/workflows/security-scan.yml@v1
    with:
      ecosystems: "python,node"
```

One CVE-handling improvement (like today's Trivy tag fix) then ships to every
repo by bumping `@v1` — instead of N copy-paste PRs. Enforce adoption with an
org ruleset requiring these checks.

### Tier 2 — Scaffolding with **copier** (the actual golden path)

A template repo instantiated per service:

```
platform-template/
├── copier.yml                  # questions: project_name, language, needs_postgres,
│                               #   needs_redis, port, k8s_namespace, registry
├── CONTRACT.md
├── Dockerfile.jinja
├── docker-compose.yml.jinja
├── deploy/k8s/                 # kustomize base + {{project_name}} overlay
├── infra/opentofu/             # modules verbatim + env skeletons
├── infra/ansible/              # playbooks verbatim + inventory skeleton
├── observability/              # SigNoz guide, dashboard JSONs with {{metric_prefix}}
├── docs/runbooks/              # skeletons
└── .github/workflows/platform.yml   # thin callers into Tier 1
```

**Why copier over cookiecutter:** `copier update` re-applies template
evolution onto already-generated projects (three-way merge). That converts
the template from a one-time generator into a *channel* — golden paths rot
precisely when instances can't receive updates.

### Tier 3 — Shared runtime library (weeks, do last)

Extract `api/telemetry.py` into a pip package:

```python
# the generic 90%
from platform_telemetry import init_telemetry, traced_call, start_gauge_poller

init_telemetry(app, service_name=settings.OTEL_SERVICE_NAME)

# the app-specific 10% stays in the app: metric names + how to read gauges
start_gauge_poller(redis, gauges={
    "daily_pnl": read_daily_pnl,          # app-supplied callables
    "open_positions": read_open_positions,
})
```

The decorator/span/no-op machinery, SQLAlchemy listener, and structlog
processor are app-agnostic today; only instrument names and the Redis-reading
callables are not. Same split applies to the k8s manifests → a Helm chart or
remote kustomize base with `values`-style overlays.

## Principles that keep it a golden path (not a cage)

1. **Defaults are production-grade; deviation is explicit.** Non-root,
   probes, PDBs, scan gates ship on. Opting out = editing a generated file
   you own (copier marks it as diverged), never forking the platform.
2. **The contract is the only coupling.** The template never imports app
   code; apps never reach into template internals.
3. **Singleton honesty travels.** This repo's hardest-won lesson — encode
   scaling constraints (HPA pinned, Recreate, PDB) in the template as a
   `singleton: true/false` copier question rather than letting each team
   rediscover double-trading the hard way.
4. **Every suppression has a reason and an exit condition** (`.trivyignore`,
   `.gitleaks.toml`, pip-audit ignores) — the rule generalizes verbatim.
5. **Paved road, measured.** Track adoption like a product: how many repos on
   `@v1` workflows, how many behind on `copier update`.

## Migration plan for this repo (when the template exists)

1. Create `platform-workflows`; move docker-build + security-scan logic;
   replace this repo's copies with thin callers. (No behavior change — the
   diff is the proof.)
2. Create `platform-template` seeded from this repo's `deploy/`, `infra/`,
   `Dockerfile`, compose, observability docs; parameterize with copier.
3. Adopt the template here via `copier copy --vcs-ref=HEAD` onto a branch and
   diff against the hand-built files — divergences are either template bugs
   or legitimate app-specific config; resolve each explicitly.
4. Extract `platform-telemetry` last, once a second consumer exists ("rule of
   two": don't library-ize with one user).

The end state: a new service goes from `git init` to deployed-with-
dashboards-probes-scans-and-runbooks in under an hour, and this repo becomes
the reference instance of the path rather than a bespoke artifact.
