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
| CI | `pip-audit --strict`, Trivy fs + image (HIGH/CRITICAL gate), gitleaks over full history, weekly cron, SBOM artifact | `.github/workflows/security-scan.yml` |
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
3. **[Open] Floating dependency pins.** `groq`, `alpaca-py` are unpinned in
   `requirements.txt`; builds are not bit-reproducible. Recommendation: adopt
   `pip-compile` (uv/pip-tools) to generate a fully-pinned lock layer used by
   the Dockerfile while keeping `requirements.txt` as the human-edited input.
4. **[Open] No image signing.** Supply-chain recommendation below.
5. **[Mitigated] Secret exposure via env.** Keys live in env vars (visible in
   `kubectl describe pod` to anyone with namespace read). Mitigation: RBAC on
   the namespace; next step: External Secrets Operator or sealed-secrets.
6. **[Note] `ruff check . --fix` in CI** mutates the checkout rather than
   failing on diff — lint drift can pass silently. Left untouched because the
   repo's guardrail docs define this exact sequence as the contract; flagging
   for a deliberate follow-up.

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
