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

---

## Whitespace LM_STUDIO_MODEL bypasses the unconfigured guard

**Symptom:** `last_local_error` shows `lmstudio_inference_failed: ...` (a cryptic API error) instead of the expected `lm_studio_model_not_configured` when `LM_STUDIO_MODEL` is set to spaces or a tab.

**Root cause:** `if not model_id:` treats any non-empty string as truthy, including `"   "`. The whitespace-only value was passed directly to LM Studio's `chat/completions` endpoint which rejected it with an opaque error.

**Fix:** `call_lmstudio()` now strips the model ID before the guard: `model_id = settings.LM_STUDIO_MODEL.strip()`. `health_snapshot()` also strips before the `or None` coercion so the dashboard never displays a whitespace model name.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_whitespace_model_raises`

---

## LM Link produces "peerapi: unknown peer" and "incompatible SOCKS version" in Tailscale daemon

**Symptom:** Tailscale daemon logs `peerapi: unknown peer 127.0.0.1:<port>` and `socks5: client connection failed: incompatible SOCKS version` whenever LM Studio calls are made via LM Link.

**Root cause:** The `openai.AsyncOpenAI` client uses `httpx` internally, which by default reads system proxy environment variables (`ALL_PROXY`, `HTTP_PROXY`). Tailscale sets `ALL_PROXY=socks5://127.0.0.1:<port>` to route non-Tailscale traffic through its SOCKS5 proxy. But LM Link traffic to a Tailscale peer is already routed at the OS network layer — the SOCKS5 proxy receives plain HTTP instead of a SOCKS5 handshake, causing both errors.

**Fix:** `_make_client()` in `api/services/lmstudio_provider.py` passes `httpx.AsyncClient(trust_env=False)` when `LM_LINK_ENABLED=True`, bypassing system proxy env vars. Tailscale handles routing at the network layer without an explicit proxy.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_make_client_lm_link_uses_trust_env_false`

---

## LLM Health panel shows "0/0 last 5m" and "--" latency after backend restart

**Symptom:** Dashboard LLM Health card shows "Success Rate: 0% (0/0 last 5m)", "Avg Latency: --", and status "Unknown" even though Redis shows dozens of lifetime/daily calls.

**Root cause:** The in-process `LLMMetricsCollector` ring buffer resets to empty on every backend restart. The `/llm/health` endpoint already merges Redis durable counters for `total_calls_lifetime` and `daily_calls`, but `avg_latency_ms` (used for the Avg Latency display) was left at 0 from the empty ring buffer. No fallback existed for the last known latency.

**Fix:** `api/routes/llm_health.py` now falls back to `redis_metrics.last_latency_ms` for `avg_latency_ms` when the ring buffer has no recent successes. It also surfaces `last_success_at` at the top level of the response. `LLMHealthPanel.tsx` shows "No calls in window — last: Xh ago" when `total_in_window === 0` and `last_success_at` is available.

**Regression test:** `tests/api/test_llm_health.py::test_llm_health_avg_latency_fallback_from_redis`
