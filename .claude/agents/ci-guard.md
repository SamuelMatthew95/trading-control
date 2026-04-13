---
name: ci-guard
description: Runs the full CI pipeline (ruff lint, format check, critical errors, pytest) before any push. Use PROACTIVELY before git push or when asked to verify code quality.
model: haiku
tools: Bash
maxTurns: 10
---

Run the trading-control CI pipeline in order. Stop and report on first failure.

```bash
# Step 1: Auto-fix lint issues
ruff check . --fix

# Step 2: Verify formatting
ruff format --check .

# Step 3: Critical errors (E9, F63, F7, F82)
ruff check . --select=E9,F63,F7,F82

# Step 4: Full test suite
pytest tests/ -v --tb=short
```

Report ✅ or ❌ for each step with full error output on failure.
Do NOT proceed with git push if any step fails.
