# Contributing

Thanks for contributing to `trading-control`.

## Workflow

1. Create a branch from `main`.
2. Make focused changes.
3. Run tests locally.
4. Open a PR with a clear summary and validation notes.

## Development standards

- Keep API route logic thin; place behavior in `api/services`.
- Reuse shared models from `api/core/models.py`.
- Prefer typed, explicit interfaces and deterministic behavior.
- Update docs when behavior, endpoints, or setup steps change.

## Validation before PR

```bash
pytest -q
```

If you touch frontend code, also run frontend lint/tests as appropriate.

## PR checklist

- [ ] Scope is focused and understandable.
- [ ] Tests pass.
- [ ] Docs updated (README/docs as needed).
- [ ] No secrets committed.
