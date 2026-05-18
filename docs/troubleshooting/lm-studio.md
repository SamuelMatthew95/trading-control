# LM Studio / LM Link Local Inference

## App fails to start when LM Studio is unreachable

**Symptom:** FastAPI startup hangs or errors when `LM_STUDIO_ENABLED=true` but the home GPU machine is offline.

**Root cause:** The startup health probe was incorrectly awaited without a timeout guard.

**Fix:** `check_health()` in `api/services/lmstudio_provider.py` calls `client.models.list()` via an `openai.AsyncOpenAI` client configured with `timeout=LM_STUDIO_TIMEOUT_SECONDS`. A failed probe logs a warning and returns `False` — the app continues in cloud-only mode without raising.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_check_health_enabled_but_unavailable`

---

## LM Studio call silently returns wrong provider name

**Symptom:** Dashboard shows `provider: gemini` even when LM Studio is active.

**Root cause:** `call_llm()` in `llm_router.py` was not tagging the parsed result with `FieldName.PROVIDER = LM_STUDIO_PROVIDER` on the local path.

**Fix:** After a successful LM Studio call, `parsed[FieldName.PROVIDER] = LM_STUDIO_PROVIDER` is set before returning. The `/llm/health` response also exposes `active_provider` which reflects the actually-serving provider.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_success`

---

## LM Studio timeout causes Redis consumer to crash

**Symptom:** Agent consumer loop exits with an unhandled timeout error when LM Studio is slow.

**Root cause:** Timeout errors propagated out of `call_lmstudio()` without being caught and wrapped.

**Fix:** `call_lmstudio()` catches `openai.APITimeoutError` explicitly, records the failure, and raises `LMStudioUnavailableError` instead. The router catches `LMStudioUnavailableError` and falls back to cloud silently.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_llm_lmstudio_timeout_falls_back_to_cloud`

---

## LM_LINK_TOKEN appears in log output

**Symptom:** `LM_LINK_TOKEN` value visible in structured log records.

**Root cause:** Exception messages were being formatted with `str(exc)` which can include URL or auth context containing the token.

**Fix:** `lmstudio_provider.py` never reads `LM_LINK_TOKEN` inside exception paths; the token is passed to the openai client constructor only and never interpolated into log strings.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_no_secrets_in_logs`

---

## Provider uses guessed lmstudio SDK method names

**Symptom:** `check_health()` or `call_lmstudio()` fails at runtime with `AttributeError` against the `lmstudio` native SDK.

**Root cause:** The original implementation used `lms.AsyncClient`, `client.llm.respond`, and `client.llm.list_loaded()` — guessed method names from the native `lmstudio` Python SDK that do not match the actual API.

**Fix:** The provider was rewritten to use `openai.AsyncOpenAI` pointed at LM Studio's stable OpenAI-compatible REST endpoint (`/v1/chat/completions`, `/v1/models`). The `lmstudio` package was removed from `requirements.txt`. The `_make_client()` helper is the only place that creates the client; tests mock it directly.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_success`
