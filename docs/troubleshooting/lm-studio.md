# LM Studio / LM Link Local Inference

## App fails to start when LM Studio is unreachable

**Symptom:** FastAPI startup hangs or errors when `LM_STUDIO_ENABLED=true` but the home GPU machine is offline.

**Root cause:** The startup health probe was incorrectly awaited without a timeout guard.

**Fix:** `check_health()` in `api/services/lmstudio_provider.py` wraps the `list_loaded()` call in `asyncio.wait_for` with `LM_STUDIO_TIMEOUT_SECONDS`. A failed probe logs `degraded_mode=True` but never raises.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_check_health_enabled_but_unavailable`

---

## LM Studio call silently returns wrong provider name

**Symptom:** Dashboard shows `provider: gemini` even when LM Studio is active.

**Root cause:** `call_llm()` in `llm_router.py` was not tagging the parsed result with `FieldName.PROVIDER = LM_STUDIO_PROVIDER` on the local path.

**Fix:** After a successful LM Studio call, `parsed[FieldName.PROVIDER] = LM_STUDIO_PROVIDER` is set before returning.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_success`

---

## LM Studio timeout causes Redis consumer to crash

**Symptom:** Agent consumer loop exits with unhandled `asyncio.TimeoutError` when LM Studio is slow.

**Root cause:** `asyncio.TimeoutError` propagated out of `call_lmstudio()` without being caught and wrapped.

**Fix:** `call_lmstudio()` catches `asyncio.TimeoutError` explicitly, records the failure, and raises `LMStudioUnavailable` instead. The router catches `LMStudioUnavailable` and falls back to cloud silently.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_llm_lmstudio_timeout_falls_back_to_cloud`

---

## LM_LINK_TOKEN appears in log output

**Symptom:** `LM_LINK_TOKEN` value visible in structured log records.

**Root cause:** Exception messages were being formatted with `str(exc)` which can include URL or auth context containing the token.

**Fix:** `lmstudio_provider.py` never reads `LM_LINK_TOKEN` inside exception paths; the token is config-only and never interpolated into log strings.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_no_secrets_in_logs`
