# Documentation Index

This folder is the local source-of-truth companion to the hosted Fern docs.

- Primary docs portal: https://matthew.docs.buildwithfern.com/
- API reference: https://matthew.docs.buildwithfern.com/api-reference/api-reference/

## Start here

If you're new to the repo, read in this order:

1. [development-guide.md](development-guide.md)
2. [architecture.md](architecture.md)
3. [testing.md](testing.md)
4. [deployment-guide.md](deployment-guide.md)

## Local docs map

| File | Coverage |
|---|---|
| [architecture.md](architecture.md) | Agent pipeline, stream chain, persistence guarantees, schema context |
| [learning-loop.md](learning-loop.md) | End-to-end buy→sell→grade→learn→propose→GitOps-PR loop; fan-out, shadow trading, param evolution |
| [development-guide.md](development-guide.md) | Local setup, env variables, runbook commands, coding expectations |
| [testing.md](testing.md) | Suite structure, mocking patterns, CI parity expectations |
| [deployment-guide.md](deployment-guide.md) | Render/Vercel deployment + production smoke checks |
| [contributing.md](contributing.md) | Branch/PR workflow and repository contribution standards |
| [AGENTS.md](AGENTS.md) | Agent runtime rules, trace propagation, startup sequence |
| [mcp.md](mcp.md) | MCP endpoint usage, auth, and production verification checklist |
| [troubleshooting/README.md](troubleshooting/README.md) | Central index for incident-focused troubleshooting guides |
| [schema_versioning.md](schema_versioning.md) | Schema version strategy and compatibility contract |
| [schema_v2_audit.md](schema_v2_audit.md) | Schema v2 audit notes and reconciliation status |
| [local-inference.md](local-inference.md) | Running local model inference paths and guardrails |

## Quick links

- Root README: [../README.md](../README.md)
- Changelog: [../CHANGELOG.md](../CHANGELOG.md)
- Claude Code rules: [../CLAUDE.md](../CLAUDE.md)
- Live dashboard: https://trading-control-khaki.vercel.app/dashboard
