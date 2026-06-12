# Validation Report

Every platform artifact was verified with the strictest tool available;
where a tool could not run in the build sandbox, that is stated rather than
implied. Re-run column = how to reproduce locally.

## Verification matrix

| Artifact | Tool / method | Result | Re-run |
|---|---|---|---|
| Python (api, tests) | `ruff check` + `ruff format --check` + `--select=E9,F63,F7,F82` | ✅ clean | `ruff check . && ruff format --check .` |
| Unit tests | pytest, CI subset split | ✅ 1,473 passed / 3 skipped | `pytest tests/core tests/api` |
| Integration tests | pytest | ✅ 89 passed | `pytest tests/integration` |
| Agent tests (local-only suite) | pytest | ✅ 605 passed / 3 skipped | `pytest tests/agents` |
| Test parity with CI deps | full re-run **with OpenTelemetry SDK installed** (CI installs it; default sandbox didn't) | ✅ identical results both ways | install `requirements.txt`, re-run |
| OTel disabled path | `tests/core/test_telemetry.py` (10 tests) | ✅ perfect no-op | `pytest tests/core/test_telemetry.py` |
| OTel **enabled** path | manual drive: `init_telemetry`, recording spans, counters, broker decorator (success/rejected/exception), gauge poller lifecycle, log-processor id stamping | ✅ all pass; OTLP export failure without a collector is non-fatal (logged retry, clean exit) | script in this doc's history; or enable against SigNoz |
| FastAPI auto-instrumentation | functional: InMemorySpanExporter + real requests through `api.main:app` | ✅ spans for `/notifications`; `/health` correctly excluded (note: instrumentor patches `build_middleware_stack`, so it never appears in `app.user_middleware`) | snippet in `docs/platform/observability.md` |
| SQLAlchemy query histogram | functional: listener attached to the real `engine.sync_engine`, `SELECT 1` recorded 0.456 ms | ✅ records | — |
| Redis string contract | `decode_responses=True` confirmed in `api/redis_client.py`; gauge poller + tests use the same | ✅ | — |
| GitHub workflows | `actionlint` v1.7.7 | ✅ zero findings | `actionlint .github/workflows/*.yml` |
| Dockerfile | `hadolint` v2.12.0 | ✅ clean (one DL3008 waiver, justified inline) | `hadolint Dockerfile` |
| Docker image build/boot | **not runnable in sandbox** (Docker Hub rate-limited) — covered by the PR smoke test in `docker-build.yml` (builds, boots in memory mode, polls `/health`) | ⚠️ verify on first CI run | `docker compose up --build` |
| Compose files | `docker compose config -q` (base + dev overlay) | ✅ both parse | same |
| K8s manifests | `kubeconform -strict` against upstream schemas | ✅ 15/15 resources valid (`kind-config.yaml` is a Kind config, not a K8s object — no schema, expected) | `kubeconform -strict deploy/k8s/*.yaml` |
| Kustomization | `kustomize build` v5.5.0 → rendered output re-validated with kubeconform | ✅ 14/14 valid, zero warnings | `kubectl kustomize deploy/k8s` |
| OpenTofu | `tofu fmt -check -recursive` v1.8.8 (parses all HCL) + scripted module-interface cross-check (args vs variables, refs vs outputs, all 3 envs) | ✅ clean — after fixing one real parse bug (heredoc ternary, see below) | `tofu fmt -check -recursive infra/opentofu` |
| `tofu validate` | **not runnable in sandbox** (provider registry 403) | ⚠️ run once locally: `tofu init -backend=false && tofu validate` per env | same |
| Ansible playbooks | `ansible-playbook --syntax-check`, all 8 playbooks incl. `site.yml` import chain (collections stubbed — galaxy 403; module names are upstream-correct) | ✅ 8/8 pass | `ansible-playbook --syntax-check playbooks/site.yml` |

## Bugs found and fixed by this pass

1. **`infra/opentofu/modules/monitoring/main.tf` — invalid HCL.** A
   conditional expression with two heredocs split across lines does not
   parse (`Missing false expression in conditional`). Would have failed the
   very first `tofu init`. Fixed by extracting both heredocs into named
   locals selected by a single-line conditional; re-verified with
   `tofu fmt -check`.
2. **`deploy/k8s/kustomization.yaml` — deprecated `commonLabels`.** Also
   subtly mutates `selector.matchLabels` on every Deployment. Replaced with
   the `labels:` + `pairs:` form (template labels only); `kustomize build`
   now renders warning-free and the output re-validates 14/14.
3. **Missing ignore rules.** `.gitignore` had no OpenTofu entries —
   `.terraform/`, state files, and `*.tfvars` could have been committed
   (state can contain secrets). Also added `deploy/k8s/secret.yaml` so the
   real-secret copy of the template can never land in git.

## First CI run on PR #310 — results and fixes

- ✅ `backend-tests` (3.10 + 3.11) and the **Docker build + boot smoke test
  passed in CI** — the image builds and serves `/health` (closes the
  sandbox gap noted below).
- ❌→✅ `security-scan` initially failed on all four jobs; each was fixed
  and re-verified locally:
  - Trivy action pin `0.28.0` no longer resolves (tags became
    `v`-prefixed upstream) → `@v0.36.0`.
  - gitleaks-action demands a paid license for org accounts → replaced
    with the MIT gitleaks CLI; full 927-commit history scan is clean after
    a precise `.gitleaks.toml` allowlist for the documented `lm-studio`
    placeholder token (46 false positives, verified individually).
  - pip-audit found ~40 real CVEs in pre-existing pins → dependencies
    upgraded (aiohttp 3.14, fastapi 0.136/starlette 1.3.1, fastmcp 2.14.7,
    gunicorn 23, uvicorn 0.38, pytest 9 toolchain). Full suite re-run
    green on the new stack AND the gunicorn `UvicornWorker` production
    boot path verified against a live Redis. One no-fix-available ignore
    (`CVE-2025-69872`, diskcache) documented in the workflow.

## Known residual risks (deliberate, tracked)

- Trivy image scan executes first in CI, not locally — watch the
  `security-scan.yml` image job.
- `tofu init` against the real provider registry and `ansible-galaxy`
  collection installs were network-blocked in the sandbox; both are
  standard first-run steps documented in their guides.
- SigNoz dashboard JSON import format drifts across SigNoz versions; the
  panel queries in `observability/signoz/README.md` are the durable contract.
