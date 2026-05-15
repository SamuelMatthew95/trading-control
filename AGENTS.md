# Repository Agent Rules

These instructions apply to the entire repository.

## Mandatory validation before commit/PR

For **every** code change (especially Codex/agent-authored changes), run this exact sequence:

```bash
ruff check . --fix
ruff format .
ruff format --check .
pytest tests/core tests/api -v --tb=short
pytest tests/integration -v --tb=short
```

Rules:

1. Do **not** commit if any command fails.
2. If `ruff format --check .` prints `Would reformat: ...`, run `ruff format .` and re-run the full sequence.
3. Do **not** open or update a PR until all four commands exit 0.

## Quality expectations

- Keep changes minimal and deterministic.
- Prefer safe fallbacks over risky behavior in trading logic.
- Update tests for behavior changes and keep assertions explicit.

## Runtime fallback contract

The app is deliberately memory-first when `api.runtime_state.is_db_available()` is false.

- Dashboard, websocket hydration, and metrics read paths must check `is_db_available()` before creating any SQLAlchemy session.
- Do not add `Depends(get_db)`, `DBSessionDep`, `AsyncSession`, or unconditional `AsyncSessionFactory()` usage to dashboard read routes.
- If a route can serve from `get_runtime_store()`, it must return a memory payload with `source: "in_memory"` instead of probing Postgres.
- Service-layer readers such as `MetricsAggregator` must support a no-session memory path for dashboard hydration.
- Any new dashboard/metrics route must be covered by a memory-mode regression test that sets `set_db_available(False)` and proves no DB session factory is called.
