# Schema and API Versioning (Clarity Guide)

## Why this exists
The codebase has `dashboard_v2` routes and `schema_version='v3'` on persisted records.
These are **different version domains** and are both valid.

## Version domains

- **Dashboard/API version**: `v2`
  - Refers to HTTP route contract and frontend payload shape.
  - Example: `/api/dashboard/...` served by `dashboard_v2.py`.

- **Database schema payload version**: `v3`
  - Refers to persisted row payload semantics (`schema_version` in tables/events).
  - Used by stream producers/consumers and DB validation.

## Source of truth in code
Use `api/schema_version.py` constants instead of hardcoding string literals.

- `DASHBOARD_API_VERSION = "v2"`
- `DB_SCHEMA_VERSION = "v3"`
- `ACCEPTED_DB_SCHEMA_VERSIONS = {"v3", "legacy", None, ""}`

## Operational expectation

- Startup runs DB initialization/migrations before workers start.
- Workers publish events with `schema_version = DB_SCHEMA_VERSION`.
- Consumers validate incoming versions against `ACCEPTED_DB_SCHEMA_VERSIONS`.
- Dashboard queries are version-agnostic and read current runtime tables.

This removes ambiguity and keeps rollout safe while preserving compatibility.
