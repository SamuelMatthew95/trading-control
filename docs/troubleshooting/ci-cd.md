# CI/CD Troubleshooting

## Unpinned ruff causes intermittent lint failures in CI

**Symptom:** `backend-tests (3.11)` CI job fails in ~39 seconds (too fast for test
collection); `backend-tests (3.10)` is cancelled by `fail-fast`. Failure is
consistent across pushes. Local `ruff check .` passes.

**Root cause:** `ruff` was unpinned in `requirements.txt`. CI installs the latest
released version on every run; a newer minor release added rules or changed
formatting behaviour that differs from the locally installed version (0.15.13).

**Fix:** Pinned `ruff==0.15.13` in `requirements.txt` so CI and local environments
use the same linter version.

**Regression test:** CI `Lint (ruff)` step — passes without modifications on every
push once the version is pinned.
