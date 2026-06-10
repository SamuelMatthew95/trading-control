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

## backend-tests pass on 3.11 but fail on 3.10 (StrEnum `str()` differs)

**Symptom:** `tests/api/test_agent_performance.py::test_stale_failing_agent_drops_to_probation`
asserted `failed_runs == 3` but got `0` — only on the `backend-tests (3.10)`
matrix job; 3.11 was green.

**Root cause:** `api/constants.py` uses real `enum.StrEnum` on 3.11 but a
`class StrEnum(str, Enum)` backport on 3.10. `str(member)` returns the value
(`"failed"`) on 3.11 but `"StatusValue.FAILED"` on 3.10. `_run_tallies` did
`str(run.get(STATUS)).lower()`, and memory-mode `agent_runs` store the enum
member as status — so 3.10 never matched `StatusValue.COMPLETED/FAILED`.

**Fix:** `agent_performance._status_text` normalizes via `getattr(raw, "value", raw)`
(the StrEnum member's `.value` is the plain string on both versions) before
lowercasing. Used by `_run_tallies` and `_liveness_dimension`.

**Lesson:** never `str()` a StrEnum for comparison — it is version-dependent.
Compare the member directly (StrEnum `==` str works) or go through `.value`.

**Regression test:** `tests/api/test_agent_performance.py::test_status_text_handles_enum_and_string`

## Every push logged a failed "PR Review Automation" run with zero jobs

**Symptom:** GitHub Actions showed a red `pr-review.yml` failure on every push
to every branch — `completed / failure` with `total_jobs: 0`, so there were no
job logs to inspect.

**Root cause:** Line 1 of `.github/workflows/pr-review.yml` had a single
leading space (` name: …`), making the YAML document invalid. GitHub registers
a startup-failure run for an unparseable workflow file on each push, even
though the workflow is `workflow_dispatch`-only.

**Fix:** Removed the leading space; all six workflow files now parse
(`python -c "yaml.safe_load(...)"` clean).

**Regression test:** n/a (workflow metadata) — validated by YAML parse of all
files under `.github/workflows/`.
