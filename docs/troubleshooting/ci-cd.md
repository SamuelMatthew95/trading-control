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

## Deprecated SQLAlchemy `declarative_base` import path

**Symptom:** `MovedIn20Warning` emitted on import — `from sqlalchemy.ext.declarative import declarative_base` is deprecated and slated for removal in a future SQLAlchemy release.

**Root cause:** `api/core/models/base.py` used the pre-2.0 import path. (`api/database.py` already imported from the correct location, so only this one module was affected.)

**Fix:** Import from the 2.0 location — `from sqlalchemy.orm import declarative_base` (`api/core/models/base.py:6`).

**Regression test:** `tests/core/test_sqlalchemy_import_guardrail.py::test_no_deprecated_declarative_base_import`
