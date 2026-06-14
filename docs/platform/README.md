# Platform Documentation

The production-platform layer added around the trading system: containers,
CI/CD, observability, Kubernetes, IaC, automation, security, and operations.
Trading logic itself is documented in `docs/` and the hosted Fern docs.

| Document | Covers |
|---|---|
| [assessment.md](assessment.md) | The audit that drove all of this — debt findings, gap analysis, plan |
| [architecture.md](architecture.md) | Final system + platform architecture, diagrams, design decisions |
| [deployment.md](deployment.md) | Every way to run it: compose, dev loop, Render, Kubernetes, OpenTofu, Ansible |
| [ci-cd.md](ci-cd.md) | Workflow architecture, caching, secrets, tagging strategy |
| [observability.md](observability.md) | OpenTelemetry design, metrics catalog, trade-lifecycle tracing, SigNoz |
| [telemetry-governance.md](telemetry-governance.md) | Telemetry control plane (v1 design): schema registry, drift detection, cost model, SLOs, ownership, rollout rules |
| [kubernetes.md](kubernetes.md) | Kind bring-up, probes, the singleton constraint, rollback procedures |
| [opentofu.md](opentofu.md) | Module design, environment separation, state strategy |
| [ansible.md](ansible.md) | Playbooks, idempotency, vault-based secrets |
| [security.md](security.md) | Controls, review findings, supply-chain recommendations |
| [validation.md](validation.md) | Verification matrix — what was tested with which tool, bugs found, residual risks |
| [golden-path.md](golden-path.md) | Design for extracting this platform into a reusable paved road (contract, reusable workflows, copier template, shared telemetry lib) |
| [../runbooks/](../runbooks/README.md) | Incident response: bot stopped, broker down, DB down, latency, deploys, monitoring, trade failures, alert handling |
| [../troubleshooting/](../troubleshooting/README.md) | Bug history per subsystem (pre-existing, self-updating) |

## The platform at a glance

```
            ┌──────────────────────────────────────────────────────────┐
            │                      Trading Bot                          │
            │  FastAPI + 7-agent pipeline + Redis Streams + Postgres    │
            └───────┬──────────────────────────────────────┬───────────┘
                    │ runs on                               │ emits
        ┌───────────▼───────────┐               ┌──────────▼──────────┐
        │ Docker (multi-stage,  │               │ OpenTelemetry        │
        │ non-root, healthcheck)│               │ traces·metrics·logs  │
        └───────────┬───────────┘               └──────────┬──────────┘
                    │ deployed to                           │ OTLP
   ┌────────────────┼────────────────┐          ┌──────────▼──────────┐
   │ Compose  │ Kubernetes │ Render  │          │       SigNoz         │
   │ (local)  │ (Kind)     │ (prod)  │          │ dashboards + alerts  │
   └────────────────┬────────────────┘          └─────────────────────┘
                    │ provisioned by
        ┌───────────▼───────────┐   ┌─────────────────────┐
        │ OpenTofu (modules +   │   │ Ansible (provision,  │
        │ env separation)       │   │ deploy, verify)      │
        └───────────────────────┘   └─────────────────────┘
                    ▲
                    │ built & gated by
        ┌───────────┴───────────┐
        │ GitHub Actions: lint, │
        │ tests, image, security│
        └───────────────────────┘
```
