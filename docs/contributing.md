# Contributing

## Workflow

1. Create a branch from `main` with a descriptive name.
2. Make focused, scoped changes — one feature or fix per PR.
3. Run the full validation checklist below before opening a PR.
4. Open a PR with a clear title and summary of what changed and why.

## Development standards

- Keep route handlers thin — place all business logic in `api/services/`.
- All database writes go through `SafeWriter` — never write directly.
- All agent communication goes through Redis Streams — never call agents directly.
- Use `log_structured()` from `api.observability` for all logging — no `print()`, no `logger.*`.
- Always use `exc_info=True` on error logs:
  ```python
  log_structured("error", "operation failed", exc_info=True)
  ```
- New FastAPI dependencies use `Annotated` syntax:
  ```python
  async def endpoint(service: Annotated[MyService, Depends(get_service)]):
  ```
- Chain exceptions with `from None` in except blocks:
  ```python
  raise HTTPException(status_code=500, detail=str(e)) from None
  ```
- Schema version on every new DB insert: `schema_version='v3'`.

## Validation before PR

Run all of these and paste the output in your PR:

```bash
# 1. Lint
ruff check . --fix

# 2. Format check
ruff format --check .

# 3. Critical error check
ruff check . --select=E9,F63,F7,F82

# 4. Full test suite
pytest tests/ -v --tb=short

# 5. No print statements
grep -rn "^[[:space:]]*print(" api/ --include="*.py" | grep -v ".pyc"
# Expected: empty
```

All commands must exit 0. No exceptions.

## PR checklist

- [ ] Scope is focused and understandable.
- [ ] All tests pass (`pytest tests/ -v --tb=short`).
- [ ] Ruff lint and format pass.
- [ ] No `print()` statements in `api/`.
- [ ] Docs updated (`README.md`, `docs/` as needed).
- [ ] `CHANGELOG.md` updated.
- [ ] If endpoint added/changed: Fern definition updated in `fern-support/matthew`.
- [ ] No secrets or API keys committed.

## Fern API docs sync

Any change to `api/routes/` that adds, removes, or modifies an endpoint requires a matching update to the Fern definition at `fern-support/matthew`. See `CLAUDE.md` for the sync flow.
