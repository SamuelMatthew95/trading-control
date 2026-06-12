# Security Posture & Review Findings

Reviewed 2026-06-12 as part of the platform transformation. Scope: backend,
container, CI, Kubernetes, IaC.

## Controls in place

| Layer | Control | Where |
|---|---|---|
| Container | Non-root (uid 10001), no shell login, slim base, multi-stage (no toolchain in runtime) | `Dockerfile` |
| Container | `.dockerignore` excludes `.env*`, keys, tests, git history | `.dockerignore` |
| Kubernetes | `restricted` Pod Security Standards on the namespace; read-only rootfs, `allowPrivilegeEscalation: false`, all capabilities dropped, seccomp RuntimeDefault | `deploy/k8s/` |
| Kubernetes | Secrets out-of-band (`secret.example.yaml` is a template; Deployment marks the Secret `optional` and the app fails closed without keys) | `deploy/k8s/secret.example.yaml` |
| App | TrustedHostMiddleware + CORS allowlist; optional `x-api-key` auth on `/api/*` write surfaces; optional Bearer token on `/mcp` | `api/main.py`, `api/security.py` |
| App | Security headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store`, HSTS on https | `api/main.py` middleware |
| App | Fail-closed defaults: kill-switch check raises on Redis loss (order → DLQ); LLM outage → `REJECT`, never a blind trade; paper broker default | platform invariants |
| CI | `pip-audit --strict`, Trivy fs + image (HIGH/CRITICAL gate), gitleaks CLI over full history (precise allowlist in `.gitleaks.toml` — only the documented `lm-studio` placeholder token), weekly cron, SBOM artifact | `.github/workflows/security-scan.yml` |
| CI | Image publish uses job-scoped `GITHUB_TOKEN` `packages:write` — no long-lived registry credential | `.github/workflows/docker-build.yml` |
| IaC | Prod rejects non-sha-pinned images via variable validation; sensitive outputs/vars marked `sensitive`; secrets via `TF_VAR_*` only | `infra/opentofu/environments/prod` |
| Automation | ansible-vault for deploy secrets, `no_log` on secret-bearing tasks, ssh password auth disabled, ufw default-deny | `infra/ansible/` |

## Review findings (ordered by priority)

1. **[Accepted risk] Local Postgres credentials are static** (`trading/trading`)
   in compose/k8s/tofu local environments. Acceptable for local-only stacks;
   dev/prod paths take the password via variable/secret. Do not reuse local
   manifests against shared infrastructure.
2. **[Open] No authentication on read endpoints.** `/dashboard/*`, `/health`,
   `/decisions` are public by design for the demo dashboard. Before any
   non-paper deployment: set `API_SECRET_KEY` (enables key auth on the write
   surfaces) and put the read surfaces behind an authenticating proxy.
3. **[Fixed] Vulnerable pinned dependencies.** The first pip-audit run
   surfaced ~40 CVEs in the previous pins. Remediated by upgrading
   `aiohttp 3.9.1→3.14.0`, `fastapi 0.115→0.136` (starlette 1.3.1),
   `fastmcp 2.9→3.4.2` (mcp 1.27; clears the SSRF/OAuthProxy CVEs Trivy
   flagged in the image — the API surface this repo uses was unchanged),
   `gunicorn 21.2→23.0`, `uvicorn 0.24→0.38`, `python-dotenv`, and the
   pytest toolchain (`pytest 9`, `pytest-asyncio 1.3`). The Dockerfile also
   upgrades pip/setuptools/wheel in both stages — stock setuptools 79
   vendors jaraco.context 5.3.0 (CVE-2026-23949) and wheel 0.45.1
   (CVE-2026-24049); setuptools ≥ 82 drops the vendored copies. Verified:
   full test suite green (1,473 + 89 + 605), gunicorn/UvicornWorker boot
   serves `/health`, `/mcp` mount answers. pip-audit is clean with **zero
   ignore flags**.
   **[Still open]** `groq`, `alpaca-py` float; adopt `pip-compile`
   (uv/pip-tools) for a fully-pinned lock layer used by the Dockerfile.
4. **[Open] No image signing.** Supply-chain recommendation below.
5. **[Mitigated] Secret exposure via env.** Keys live in env vars (visible in
   `kubectl describe pod` to anyone with namespace read). Mitigation: RBAC on
   the namespace; next step: External Secrets Operator or sealed-secrets.
6. **[Note] `ruff check . --fix` in CI** mutates the checkout rather than
   failing on diff — lint drift can pass silently. Left untouched because the
   repo's guardrail docs define this exact sequence as the contract; flagging
   for a deliberate follow-up.

### Frontend (Trivy fs scan findings)

`next 14.2.15 → 14.2.35` clears CRITICAL CVE-2025-29927 (middleware auth
bypass) and the 14.x-fixable DoS advisories; `lodash → 4.18.1` (pnpm
override) clears CVE-2026-4800. Verified: typecheck, 409 vitest tests, and
the production build all pass. Five remaining Next.js advisories are fixed
only in Next ≥ 15.5.16 — a major framework migration (React 19, async
request APIs) deliberately out of scope here; they are listed in
`.trivyignore` with reasons and an explicit exit condition.
**Follow-up:** migrate the dashboard to Next 15.x and delete that block.

### Secret-scan hygiene

gitleaks scans all branches in CI (3,311 commits). Two allowlist entries in
`.gitleaks.toml`, both precise: the documented `lm-studio` placeholder
token, and `.next/` build output committed on old unmerged branches (the
flagged values are Next.js auto-generated per-build preview-mode tokens,
not external credentials).

## Supply-chain recommendations

- **Sign images** with cosign keyless in `docker-build.yml`
  (`cosign sign ghcr.io/...@<digest>`) and enforce verification at deploy
  time (Kyverno/policy-controller).
- **Pin GitHub Actions by commit SHA** instead of major tags for
  third-party actions (Trivy, gitleaks) — tag-jacking resistance.
- **SBOM** is already produced per build (SPDX artifact); attach it to GHCR
  via `cosign attest` so consumers can query it.
- **Dependabot/Renovate** for the base image (`python:3.11-slim`) and action
  versions; the repo already has `auto-pr-deps.yml` for Python deps.
- **Branch protection**: require backend-ci + security-scan checks, no force
  pushes, signed commits if the team grows beyond one.

## Secrets management decision tree

| Context | Mechanism |
|---|---|
| Local dev | `.env` (git-ignored), `direnv` optional |
| Docker Compose | env passthrough from `.env`; never baked into images |
| CI | GitHub Actions secrets; only `GITHUB_TOKEN` is used today |
| Kubernetes | `Secret` created out-of-band → External Secrets Operator when a real secret store exists |
| OpenTofu | `TF_VAR_*` env injection; state treated as secret-bearing (remote, encrypted, access-controlled) |
| Ansible | `ansible-vault` files passed with `-e @file` |
| Render (current prod) | dashboard-managed env vars (`sync: false` in render.yaml) |
