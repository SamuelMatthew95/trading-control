# Repository Agent Rules

These instructions apply to the entire repository.

## Mandatory validation before commit/PR

For **every** code change (especially Codex/agent-authored changes), run this exact sequence:

```bash
ruff check . --fix
ruff format .
ruff format --check .
pytest tests/ -v --tb=short
```

Rules:

1. Do **not** commit if any command fails.
2. If `ruff format --check .` prints `Would reformat: ...`, run `ruff format .` and re-run the full sequence.
3. Do **not** open or update a PR until all four commands exit 0.

## Quality expectations

- Keep changes minimal and deterministic.
- Prefer safe fallbacks over risky behavior in trading logic.
- Update tests for behavior changes and keep assertions explicit.
