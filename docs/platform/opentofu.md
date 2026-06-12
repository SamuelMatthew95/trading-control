# Infrastructure as Code — OpenTofu

`infra/opentofu/` defines the whole stack as reusable modules with strict
environment separation. The Docker provider keeps every environment **free
and locally runnable** while the module interfaces stay cloud-shaped: each
module's outputs are its contract, so a cloud implementation (RDS,
ElastiCache, ECS) can replace a module without touching its consumers.

```
infra/opentofu/
├── modules/
│   ├── network/      bridge network all containers join
│   ├── database/     pgvector Postgres + Redis (outputs: database_url, redis_url)
│   ├── compute/      API container (env wiring, healthcheck, secret map)
│   └── monitoring/   OTel collector → SigNoz (or debug exporter)
└── environments/
    ├── local/        runnable now: local state, ports published, debug telemetry
    ├── dev/          pinned CI image tags, remote-state backend stub, shared SigNoz
    └── prod/         remote state REQUIRED, sha-pinned images enforced by
                      variable validation, signoz_endpoint mandatory
```

## Run the local environment

```bash
docker build -t trading-control-api:local .

cd infra/opentofu/environments/local
tofu init
tofu plan                          # review: network, pg, redis, otelcol, api
tofu apply -auto-approve

curl -s localhost:8000/health | python3 -m json.tool
tofu output                        # api_url, otlp_endpoint, container names

tofu destroy -auto-approve         # full teardown (volumes included)
```

Secrets are env-injected, never written to disk:

```bash
export TF_VAR_alpaca_api_key=... TF_VAR_gemini_api_key=...
tofu apply
```

## State strategy

| Environment | Backend | Locking | Why |
|---|---|---|---|
| local | local file | none | disposable, single user |
| dev | S3-compatible (R2/MinIO/S3) | DynamoDB table or Tofu native lockfile | shared mutation needs serialized applies |
| prod | S3-compatible, versioned bucket | mandatory | audit trail + recovery of prior state |

The backend blocks are committed (commented in dev, documented in prod) so
the policy is reviewable in the repo, not tribal knowledge.

## Guardrails worth noticing

- **Immutable prod images.** `environments/prod` rejects any `api_image`
  that is not `:sha-<40-hex>` via a `validation` block — `:latest` cannot
  reach production by construction.
- **Prod is never unobserved.** `signoz_endpoint` is a required, validated
  variable in prod; the collector falls back to a debug exporter only in
  local/dev.
- **Sensitive values** (`database_url`, passwords, `secret_env`) are marked
  `sensitive` so they are redacted from plan/apply output.
- **Module seams match failure domains.** Swapping self-hosted Postgres for
  a managed database is a one-module change because consumers only see
  `database_url`.

## Conventions

- One module = one responsibility, always `main.tf` / `variables.tf` /
  `outputs.tf`.
- Variables have descriptions and safe defaults only where a default is
  genuinely safe (local credentials, paper-trading mode).
- `tofu fmt -recursive` and `tofu validate` run in pre-commit / CI
  (see `docs/platform/ci-cd.md`).
