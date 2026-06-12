# CI/CD Architecture

All automation runs on GitHub Actions. The pipeline is split into small,
path-filtered workflows so a frontend change never burns backend CI minutes
and vice versa.

```
                         ┌──────────────────────────────────────────────┐
 Pull Request ──────────►│ backend-ci.yml      lint + unit + integration│
   (api/**, frontend/**) │ frontend-ci.yml     eslint + tsc + build +   │
                         │                     vitest coverage          │
                         │ docker-build.yml    image builds + boots     │
                         │                     (smoke test, no push)    │
                         │ security-scan.yml   pip-audit + Trivy +      │
                         │                     gitleaks (Phase 8)       │
                         └──────────────┬───────────────────────────────┘
                                        │ merge
                                        ▼
                         ┌──────────────────────────────────────────────┐
 Push to main ──────────►│ backend-ci.yml      re-verify on main        │
                         │ docker-build.yml    build + push to GHCR     │
                         │                     (:latest, :sha-<commit>) │
                         │ security-scan.yml   scan published image     │
                         └──────────────┬───────────────────────────────┘
                                        │
                                        ▼
                          Render auto-deploy (render.yaml) — or pull the
                          GHCR image into Kubernetes (deploy/k8s/, Phase 5)
```

## Workflows

| Workflow | Trigger | What it proves |
|---|---|---|
| `backend-ci.yml` | PR + main, backend paths | ruff lint/format/critical errors; `pytest tests/core tests/api`; `pytest tests/integration` on Python 3.10 **and** 3.11 (parallel matrix) |
| `frontend-ci.yml` | PR + main, `frontend/**` | ESLint (zero warnings), `tsc`, production build, vitest coverage artifact |
| `docker-build.yml` | PR + main, backend/Docker paths | Multi-stage image builds; on PRs the container is booted in memory mode and `/health` polled; on main the image is pushed to GHCR |
| `security-scan.yml` | PR + main + weekly cron | Dependency audit, filesystem + image CVE scan, secret scan (see `docs/platform/security.md`) |
| `auto-pr-deps.yml`, `param-evolution-pr.yml`, `config-version-bump.yml`, `pr-review.yml` | various | Pre-existing repo automation (dependency PRs, learning-loop parameter PRs, review bot) — untouched by the platform work |

## Design decisions

- **Caching.** `actions/setup-python` pip cache keyed on `requirements.txt`;
  Docker layers cached via `cache-from/to: type=gha` so PR builds reuse the
  dependency layer (~90% of build time) across runs.
- **Parallelism.** Backend tests fan out across a Python-version matrix with
  `fail-fast: false`; the lint/test, Docker, and security workflows run
  concurrently on the same PR.
- **Concurrency groups.** Every workflow cancels superseded runs of the same
  ref (`cancel-in-progress: true`) — force-pushing a PR never queues stale CI.
- **Secrets.** Image publishing uses the ephemeral, job-scoped
  `GITHUB_TOKEN` with `permissions: packages: write` — no long-lived registry
  PAT exists. Trading/LLM API keys are **never** referenced in CI; tests run
  hermetically against fakeredis/SQLite. Fork PRs therefore can't exfiltrate
  anything: there is nothing to exfiltrate.
- **Failure notifications.** Failed jobs write a `$GITHUB_STEP_SUMMARY`
  banner and upload the full test output as an artifact; GitHub's native
  notification routing (email/Slack app) keys off the check failure itself.
- **Tags.** Images are addressable by immutable commit
  (`sha-<40-hex>`) for rollback, by branch for tracking, and `latest` only on
  the default branch.

## Local CI mirror

Run exactly what CI runs before pushing (order matters — CI splits the pytest
subsets, and ordering-sensitive failures only appear split):

```bash
ruff check . --fix
ruff format --check .
ruff check . --select=E9,F63,F7,F82
pytest tests/core tests/api -v --tb=short
pytest tests/integration -v --tb=short
pytest tests/agents -v --tb=short   # local only — not in CI
```
