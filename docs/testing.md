# Testing Guide

## Test suites

Current tests are in `tests/` and cover:

- baseline runtime checks,
- API modularization/route structure,
- orchestrator architecture behavior,
- regression checks for agent operation flows.

## Run tests

```bash
pytest -q
```

## Useful focused runs

```bash
pytest tests/test_basic.py -q
pytest tests/test_api_modularization.py -q
pytest tests/test_orchestrator_architecture.py -q
pytest tests/test_agentops_regression.py -q
```

## Expectations for contributors

- Add or update tests whenever behavior changes.
- Keep tests deterministic (avoid flaky network-dependent assertions).
- Prefer small, focused tests over one large end-to-end script.
