---
name: run-ci
description: Run the full trading-control CI pipeline — ruff lint, format check, critical errors, pytest. Invoke before pushing or after significant changes.
argument-hint: [--tests-only | --lint-only]
allowed-tools: Bash
---

Run the trading-control CI pipeline. Execute steps in order, stopping on first failure.

```bash
# Step 1: Auto-fix lint issues (must show "All checks passed!")
ruff check . --fix

# Step 2: Verify formatting (must show "N files already formatted")
ruff format --check .

# Step 3: Critical errors only — E9, F63, F7, F82
ruff check . --select=E9,F63,F7,F82

# Step 4: Full test suite
pytest tests/ -v --tb=short
```

Report ✅ or ❌ for each step. On failure, show full error output and stop.

If argument is `--tests-only`: skip steps 1–3, run step 4 only.
If argument is `--lint-only`: run steps 1–3 only, skip step 4.
