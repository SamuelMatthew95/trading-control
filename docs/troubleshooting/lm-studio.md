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

## `socks5: client connection failed: incompatible SOCKS version` on Render + Tailscale userspace mode

**Symptom:** Render logs show `socks5: client connection failed: incompatible SOCKS version` and the reasoning agent times out with `reasoning_llm_timeout`. LM Studio calls never reach `100.112.224.78:1234`.

**Root cause:** Tailscale running with `--tun=userspace-networking` creates no kernel TUN device. Traffic to Tailscale peers (e.g. `100.112.224.78`) cannot reach them via direct TCP — it must be routed through the proxy that `tailscaled` exposes. Previously, `_make_client()` set `trust_env=False` and made no direct proxy configuration, so httpx attempted a direct TCP connection that failed silently or ended up hitting `localhost:1055` (the SOCKS5 listener) with plain HTTP — which SOCKS5 rejects with "incompatible SOCKS version".

**Fix:**
1. Added `LM_STUDIO_PROXY_URL` setting (e.g. `http://127.0.0.1:1055`) that configures an explicit HTTP CONNECT proxy on the httpx client via `httpx.AsyncClient(proxy=proxy_url, trust_env=False)`.
2. `tailscaled` is now started with `--outbound-http-proxy-listen=localhost:1055` in `.render/start.sh` so it serves as an HTTP CONNECT proxy in addition to SOCKS5.
3. `validate_lm_studio_config()` added — fails fast at startup if `LM_STUDIO_HOST:LM_STUDIO_PORT` resolves to `localhost:1055`, `127.0.0.1:1055`, or `0.0.0.0:1055` (the proxy endpoint, not LM Studio).
4. `trust_env=False` is now always applied (not conditional on `LM_LINK_ENABLED`), preventing httpx from ever inheriting `ALL_PROXY`/`HTTP_PROXY` from the environment.

**Required env vars (Render):**
```
LM_STUDIO_HOST=100.112.224.78      # Mac Tailscale IP — NOT 127.0.0.1
LM_STUDIO_PORT=1234
LM_STUDIO_PROXY_URL=http://127.0.0.1:1055
TAILSCALE_AUTHKEY=tskey-auth-...
```

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_validate_config_rejects_127_0_0_1_port_1055`

---

## LLM Health panel shows "0/0 last 5m" and "--" latency after backend restart

**Symptom:** Dashboard LLM Health card shows "Success Rate: 0% (0/0 last 5m)", "Avg Latency: --", and status "Unknown" even though Redis shows dozens of lifetime/daily calls.

**Root cause:** The in-process `LLMMetricsCollector` ring buffer resets to empty on every backend restart. The `/llm/health` endpoint already merges Redis durable counters for `total_calls_lifetime` and `daily_calls`, but `avg_latency_ms` (used for the Avg Latency display) was left at 0 from the empty ring buffer. No fallback existed for the last known latency.

**Fix:** `api/routes/llm_health.py` now falls back to `redis_metrics.last_latency_ms` for `avg_latency_ms` when the ring buffer has no recent successes. It also surfaces `last_success_at` at the top level of the response. `LLMHealthPanel.tsx` shows "No calls in window — last: Xh ago" when `total_in_window === 0` and `last_success_at` is available.

**Regression test:** `tests/api/test_llm_health.py::test_llm_health_avg_latency_fallback_from_redis`

---

## Dashboard shows "Provider: gemini / LLM Health: Down / Local GPU: Offline" when LM Studio is configured

**Symptom:** Dashboard reports `provider: gemini`, `model: gemini_2.5-flash-lite`, `last error: gemini_model_not_found`, and `Local GPU: Offline / Connection error` even though LM Studio is the intended provider.

**Root cause (three compounding issues):**
1. `LLM_PROVIDER` defaulted to `"gemini"` — no explicit mechanism to select LM Studio as the primary provider. `LM_STUDIO_ENABLED=true` only made LM Studio a first-try option, still falling back to Gemini.
2. A remote backend (Render) cannot reach `localhost:1234` on the developer's laptop, but the error surfaced as a vague "Connection error" with no guidance.
3. When `LLM_PROVIDER=lmstudio` was set, the router would fall through to the cloud-provider dispatch and raise `unknown_provider: 'lmstudio'` — a confusing internal error.

**Fix:**
- Set `LLM_PROVIDER=lmstudio` to make LM Studio the explicit primary provider. This automatically enables LM Studio without needing `LM_STUDIO_ENABLED=true`, and removes the requirement for any cloud API key.
- `lmstudio_provider.check_health()` now detects the remote+localhost mismatch (`RENDER_EXTERNAL_URL` set + `LM_STUDIO_HOST=localhost`) and returns a clear error: *"Remote backend cannot reach local LM Studio at localhost. Use a public tunnel, Tailscale, or run backend locally."*
- `/llm/health` response includes `remote_localhost_mismatch: true/false` and `base_url_host` so the dashboard can surface a targeted warning instead of "Connection error".
- `LLM_FALLBACK_ENABLED=false` (recommended with `LLM_PROVIDER=lmstudio`) prevents silent fallback to Gemini when LM Studio is unavailable.
- When `LLM_PROVIDER=lmstudio` and LM Studio fails with fallback disabled, the error is `lmstudio_unavailable: <reason>` — not a Gemini error.
- `check_health()` validates that the configured `LM_STUDIO_MODEL` is present in the models LM Studio has loaded, and lists available models in the health response if there is a mismatch.
- `LM_STUDIO_BASE_URL` env var added as a convenient alternative to `LM_STUDIO_HOST` + `LM_STUDIO_PORT`.

**Required env vars (Render, LM Studio via Tailscale):**
```
LLM_PROVIDER=lmstudio
LLM_FALLBACK_ENABLED=false
LM_STUDIO_HOST=<tailscale-ip-of-mac>   # e.g. 100.112.224.78 — NOT localhost
LM_STUDIO_PORT=1234
LM_STUDIO_MODEL=<exact model name from LM Studio>
LM_STUDIO_PROXY_URL=http://127.0.0.1:1055
TAILSCALE_AUTHKEY=tskey-auth-...
```

**Required env vars (local backend + local LM Studio):**
```
LLM_PROVIDER=lmstudio
LLM_FALLBACK_ENABLED=false
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=<exact model name from LM Studio>
```

**Regression tests:**
- `tests/agents/test_lmstudio_provider.py::test_is_remote_localhost_mismatch_true_when_render_and_localhost`
- `tests/agents/test_lmstudio_provider.py::test_check_health_returns_false_with_mismatch_error`
- `tests/agents/test_lmstudio_provider.py::test_llm_provider_lmstudio_enables_lm_studio`
- `tests/api/test_llm_health.py::test_call_llm_lmstudio_primary_no_fallback_raises`
- `tests/api/test_llm_health.py::test_call_llm_lmstudio_primary_does_not_call_gemini_without_key`

---

## validate_lm_studio_config bypass via LM_STUDIO_BASE_URL

**Symptom:** Setting `LM_STUDIO_BASE_URL=http://127.0.0.1:1055/v1` with valid `LM_STUDIO_HOST`/`LM_STUDIO_PORT` allowed the Tailscale proxy endpoint to be used as the LM Studio destination without raising an error.

**Root cause:** `validate_lm_studio_config()` only checked the `LM_STUDIO_HOST:LM_STUDIO_PORT` combination; the `LM_STUDIO_BASE_URL` override was not inspected, so the proxy-endpoint guard could be bypassed by setting only the URL.

**Fix:** `api/services/lmstudio_provider.py::validate_lm_studio_config()` now also parses `LM_STUDIO_BASE_URL` (when set) and raises `RuntimeError` if its extracted host:port matches any entry in `_BLOCKED_HOST_PORT`.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_validate_config_rejects_base_url_with_proxy_host_port`

---

## check_health reports healthy when LM_STUDIO_MODEL is blank

**Symptom:** `/llm/health` reports `lm_studio_healthy: true` and `active_provider: lmstudio`, but every inference call immediately fails with `lm_studio_model_not_configured`. With `LLM_FALLBACK_ENABLED=false` this causes a total inference outage while the dashboard shows everything as healthy.

**Root cause:** `check_health()` ran the model-presence check only when `configured` was non-empty (`if configured and configured not in model_ids`). When `LM_STUDIO_MODEL` was blank the condition was short-circuited, leaving `_health.healthy = True` even though no model was configured for inference.

**Fix:** The condition was split in `api/services/lmstudio_provider.py::check_health()`: an explicit `if not configured` guard now sets `_health.last_error = "lm_studio_model_not_configured"` and returns False before the model-presence check runs.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_check_health_blank_model_returns_false_and_unhealthy`

---

## active_provider shows lmstudio when cloud fallback is actually serving

**Symptom:** `/llm/health` returns `active_provider: lmstudio` even though LM Studio is unhealthy and `LLM_FALLBACK_ENABLED=true` is routing all calls to a cloud provider (e.g. Groq). The dashboard therefore shows "Local GPU: Active" while a cloud provider is silently handling requests.

**Root cause:** `api/routes/llm_health.py` computed `active_provider` as `LM_STUDIO_PROVIDER if lm_snap.lm_studio_healthy else provider`. When `LLM_PROVIDER=lmstudio` and LM Studio is unhealthy, `provider` evaluates to `"lmstudio"`, not the actual cloud fallback that `call_llm()` selects via `_find_cloud_fallback()`.

**Fix:** When LM Studio is unhealthy and `provider == "lmstudio"` with `LLM_FALLBACK_ENABLED=true`, the endpoint now calls `_find_cloud_fallback()` to determine the actual serving provider and exposes that as `active_provider`.

**Regression test:** `tests/api/test_llm_health.py::test_active_provider_is_cloud_fallback_when_lmstudio_primary_is_down`

---

## LM Studio cooldown bypassed when LLM_PROVIDER=lmstudio (P1 + P2 refinement)

**Symptom:** After LM Studio becomes unavailable, every subsequent call blocks for `LM_STUDIO_TIMEOUT_SECONDS` before routing to the cloud fallback (with `LLM_FALLBACK_ENABLED=true`). The 60-second cooldown intended by `should_try_local()` is never respected.

**Root cause:** `use_lmstudio` was computed as `lm_primary OR (LM_STUDIO_ENABLED AND should_try_local())`. The `OR` short-circuited whenever `LLM_PROVIDER=lmstudio`, so `should_try_local()` was never evaluated when LM Studio was the primary provider.

**Fix:** `use_lmstudio` is now computed as `(lm_primary AND NOT _cloud_available) OR ((lm_primary OR LM_STUDIO_ENABLED) AND should_try_local())`, where `_cloud_available = LLM_FALLBACK_ENABLED AND bool(_find_cloud_fallback())`. This means:
- A live cloud path exists (fallback enabled + cloud API key configured): cooldown is honoured — during the 60-second window requests route directly to cloud without touching LM Studio.
- No usable cloud path (fallback disabled OR no cloud API key): cooldown is **bypassed** — suppressing retries just extends the outage with no benefit. LM Studio is always tried; the caller sees the real failure rather than a synthetic "cooldown" error.

Both `call_llm` and `call_llm_with_system` are fixed.

**Regression tests:**
- `tests/api/test_llm_health.py::test_call_llm_lmstudio_primary_respects_cooldown_fallback_enabled`
- `tests/api/test_llm_health.py::test_call_llm_lmstudio_primary_cooldown_no_fallback_raises`
- `tests/api/test_llm_health.py::test_call_llm_lmstudio_primary_no_cloud_key_bypasses_cooldown`

---

## Startup LM Studio probe skipped when LLM_PROVIDER=lmstudio + LM_STUDIO_ENABLED=False

**Symptom:** With `LLM_PROVIDER=lmstudio` and `LM_STUDIO_ENABLED=False` the startup health probe was silently skipped, leaving a misconfigured primary LM Studio provider undetected at boot.

**Root cause:** `api/main.py` lifespan gated the LM Studio startup probe on `settings.LM_STUDIO_ENABLED` only. `LLM_PROVIDER=lmstudio` implicitly enables LM Studio as the primary provider, so the probe should fire even when the explicit flag is off.

**Fix:** The startup condition was changed from `if settings.LM_STUDIO_ENABLED:` to `if _is_lmstudio_effectively_enabled():`, which returns `True` when either `LM_STUDIO_ENABLED=True` or `LLM_PROVIDER=lmstudio`.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_is_lmstudio_effectively_enabled_true_when_primary`

---

## LM_STUDIO_BASE_URL credentials logged in startup config

**Symptom:** Structured logs from the startup `lmstudio_config` event include userinfo (`user:pass@`) and/or query tokens from `LM_STUDIO_BASE_URL` despite the docstring saying "Never logs secrets."

**Root cause:** `log_startup_config()` passed `get_lm_studio_base_url()` raw to `log_structured`, exposing credentials in authenticated-tunnel or proxy URLs.

**Fix:** Added `_redact_url()` in `api/services/lmstudio_provider.py` which strips userinfo and query string via `urlunparse`, logging only scheme/host/port/path.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_log_startup_config_redacts_url_credentials`

---

## Invalid LM_STUDIO_BASE_URL port crashes startup with ValueError (P1)

**Symptom:** Setting `LM_STUDIO_BASE_URL=http://localhost:notaport/v1` causes an unhandled `ValueError` during startup or health probe, crashing the app rather than entering degraded mode.

**Root cause:** `urllib.parse.urlparse` accepts invalid port strings without raising, but accessing `parsed.port` raises `ValueError`. `validate_lm_studio_config()` only caught `RuntimeError`, so the `ValueError` escaped past `check_health()`'s exception handler.

**Fix:** Wrapped the `parsed.hostname` / `parsed.port` access in `validate_lm_studio_config()` with a `try/except ValueError` that re-raises as `RuntimeError`. `check_health()` already catches `RuntimeError` and returns `False` (degraded), so no further changes were needed.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_validate_config_invalid_port_raises_runtime_error`

---

## Stale available_models reported after check_health() failure (P2)

**Symptom:** `GET /llm/health` returns a non-empty `available_models` list even when LM Studio is unhealthy (mismatch error, config error, or network failure), misleading fallback/debug decisions.

**Root cause:** `_health.available_models` was only written on the successful `/v1/models` probe path. After one successful probe, any subsequent failure (mismatch detection, config validation error, network exception) left the stale model list in the health state.

**Fix:** Added `_health.available_models = []` to all three failure return paths in `check_health()`: the remote-localhost mismatch branch, the `validate_lm_studio_config()` exception branch, and the final `except Exception` network-failure branch.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_check_health_clears_available_models_on_mismatch`

---

## get_lm_studio_base_url corrupts URLs with query/fragment components (P2)

**Symptom:** Setting `LM_STUDIO_BASE_URL=http://host:1234/path?token=abc` causes both health probes and inference calls to target `http://host:1234/path?token=abc/v1` — an invalid endpoint — even though the original URL was correct.

**Root cause:** `get_lm_studio_base_url()` appended `/v1` to the raw string after `rstrip("/")`. When the URL contained a query string, the path check `not base_url.endswith("/v1")` evaluated against the query tail (`"abc"`), so `/v1` was appended after the query rather than after the path.

**Fix:** Use `urlparse` to decompose the URL, append `/v1` to `parsed.path` only, then recompose with `urlunparse` (dropping query and fragment, which have no meaning for an API base URL).

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_get_lm_studio_base_url_with_query_string`

---

## "Client Disconnected" errors on long Qwen3.5-9B inference over Tailscale (Pillar 1)

**Symptom:** Production logs show `Client Disconnected` errors mid-inference. LM Studio at ~12 tok/s takes ~65s for 800 tokens; the Tailscale SOCKS5 proxy closes idle TCP connections before inference completes.

**Root cause:** `call_lmstudio()` used a one-shot `completions.create()` call. No data was sent over the TCP connection until the full response arrived, so the proxy treated the connection as idle and closed it.

**Fix:** `call_lmstudio()` now calls `completions.create(stream=True)` via `_collect_streaming_response()`. Streaming sends TCP data packets continuously as tokens arrive, keeping the connection alive. On any mid-stream exception (excluding `APITimeoutError`/`APIConnectionError`, which re-raise immediately) the call retries once with the non-streaming path.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_uses_streaming`

---

## Token waste on routine PRICE_UPDATE signals (Pillar 2)

**Symptom:** Every market tick consumed 1500 tokens even for simple hold decisions, exhausting Qwen3.5-9B's context window and increasing latency unnecessarily.

**Root cause:** `call_lmstudio()` used a single fixed `LLM_MAX_TOKENS_LMSTUDIO=1500` budget regardless of signal strength or task type.

**Fix:** Added `_get_task_params(task_type, ...)` that maps `LLM_TASK_PRICE_ANALYSIS` → 1024 tokens, `LLM_TASK_TRADE_EXECUTION` → 2048 tokens, `LLM_TASK_HEALTH_CHECK` → 256 tokens (all env-overridable via `LM_STUDIO_MAX_TOKENS_*` settings). `ReasoningAgent._call_llm()` classifies each signal: strong signals (`STRONG` in type or `composite_score >= 0.75`) get `trade_execution`; others get `price_analysis`. Default behaviour (`task_type=None`) is unchanged at 1500 tokens.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_task_type_price_analysis_uses_analysis_tokens`

---

## Verbose reasoning prefixes waste tokens and break JSON extraction (Pillar 3)

**Symptom:** Qwen3.5-9B prepended reasoning text like `"Thinking Process: ..."` or markdown code fences before the JSON object, causing `_extract_json_from_text` to scan through many tokens before finding the payload.

**Root cause:** `ADAPTIVE_TRADING_SYSTEM_PROMPT` had no explicit JSON-only output constraint, and the model was not given stop sequences to terminate generation at natural break points.

**Fix:** Added explicit "CRITICAL OUTPUT RULES" to `ADAPTIVE_TRADING_SYSTEM_PROMPT` in `api/services/agents/prompts.py` prohibiting preamble and markdown fences. Added `_STOP_SEQUENCES = ["\n\n\n", "```", "Thinking Process:"]` passed to every `completions.create()` call so generation halts at these patterns before they accumulate.

---

## Migration from Qwen3 to Llama 3.1 instruct — Qwen3 hacks break Llama inference

**Symptom:** After switching `LM_STUDIO_MODEL` to `meta-llama-3.1-8b-instruct` (or any non-thinking instruct model), the system prompt contains `/no_think` which becomes literal prompt noise, and the provider attempts to read `reasoning_content` from the completion message — a field that Llama 3.1 never populates.

**Root cause:** The previous implementation targeted Qwen3 in thinking mode, which required:
- Appending `/no_think` to the system prompt to suppress the chain-of-thought preamble
- Reading `message.reasoning_content` as a fallback when `message.content` was empty

Neither mechanism applies to instruct models (Llama, Mistral, Phi, etc.) that do not have a thinking mode. The `/no_think` token becomes noise that degrades instruction-following on strict JSON tasks.

**Fix:** Removed `/no_think` entirely from `lmstudio_provider.py`. The provider now reads `message.content` only — `reasoning_content` is logged for observability but never used as a content source. `enable_thinking: False` is passed in `extra_body` on every call to explicitly suppress thinking mode if the model supports it, without affecting instruct models that don't.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_success`

---

## Non-dict JSON triggers AttributeError instead of HOLD fallback

**Symptom:** When the model returns syntactically valid JSON that is not an object — e.g. `[]`, `null`, `"a string"`, or `42` — the provider raises `LMStudioUnavailableError` with message `lmstudio_inference_failed: 'list' object has no attribute 'get'` instead of applying the safe HOLD fallback. With `LLM_FALLBACK_ENABLED=false` this becomes a hard inference failure.

**Root cause:** After a successful `json.loads(text)`, the code called `parsed.get(FieldName.ACTION, "")` unconditionally. If `parsed` is a list, string, or `None`, `.get()` raises `AttributeError`, which the outer `except Exception` handler reclassified as `lmstudio_inference_failed`.

**Fix:** Added an `isinstance(candidate, dict)` check immediately after `json.loads`. Non-dict results set `parsed = None`, which triggers the existing fallback path: `_extract_json_from_text` runs as a second chance (an array that happens to contain a `{"action": ...}` object is correctly salvaged), and if nothing usable is found the safe HOLD JSON is returned.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_llm_lmstudio_non_dict_json_returns_hold`

---

## Explicit temperature override silently discarded

**Symptom:** Passing `temperature=0.9` to `call_lmstudio(..., temperature=0.9)` has no effect — the model always runs at `settings.LM_STUDIO_TEMPERATURE` (default 0.0).

**Root cause:** `_get_task_params(task_type, default_max_tokens, default_temperature)` was reading `settings.LM_STUDIO_TEMPERATURE` directly instead of using the `default_temperature` argument. The caller's resolved value was ignored.

**Fix:** `_get_task_params` now uses the `default_temperature` parameter throughout. The caller resolves temperature as `temperature if temperature is not None else settings.LM_STUDIO_TEMPERATURE` before calling `_get_task_params`, which preserves both explicit call-site overrides and the settings default.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_task_type_uses_caller_temperature`

---

## Streaming mode — mid-stream drop fails immediately instead of retrying

**Symptom:** With `LM_STUDIO_STREAM=true`, any mid-stream TCP drop or chunk-iteration error raises `LMStudioUnavailableError` immediately and triggers cloud fallback. A non-streaming retry that would have succeeded in the same condition is never attempted.

**Root cause:** `_collect_streaming_response()` was called without a try/except wrapper. Any exception propagated directly out of `call_lmstudio()` as an infrastructure failure.

**Fix:** The streaming call is now wrapped in a try/except. On any exception, the provider logs `lmstudio_stream_error_retry_nonstreaming` and immediately retries with `stream=False`. Only if the non-streaming retry also fails does the error propagate as `LMStudioUnavailableError`. This restores the reliability of the streaming path — transient drops are invisible to the caller.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_call_lmstudio_streaming_fallback_to_nonstreaming`

---

## `_parse_response` overwrites `fallback=True` from LM Studio HOLD substitution

**Symptom:** When LM Studio returns invalid JSON or an unrecognised action, `call_lmstudio` substitutes a HOLD decision with `"fallback": true`. The router's `_parse_response` then stamps it `"fallback": false`. The `if not parsed.get(FALLBACK)` guard in `call_llm` evaluates as True (success), so `_record_lm_failure` is never called and cloud fallback is never triggered — even when `LLM_FALLBACK_ENABLED=true`.

**Root cause:** `_parse_response` in `llm_router.py` unconditionally set `parsed[FieldName.FALLBACK] = False` on any successful `json.loads`, overwriting the `fallback=True` sentinel already placed by `_hold_fallback_json`.

**Fix:** Changed the assignment to `parsed.setdefault(FieldName.FALLBACK, False)` so that a `fallback=True` already in the response is preserved. Cloud providers that never include the key still get `False` by default.

**Regression test:** `tests/core/test_signal_pipeline.py::TestLLMRouter::test_parse_response_preserves_fallback_true`

---

## `check_health()` model failures don't update `last_failure_at` — retry cooldown bypassed

**Symptom:** After a startup `check_health()` finds LM Studio unhealthy (e.g. no model loaded), `should_try_local()` returns `True` on every subsequent call — the 60s retry cooldown (`_RETRY_INTERVAL_S`) has no effect. Every inference attempt still tries LM Studio immediately, adding a full `LM_STUDIO_TIMEOUT_SECONDS` wait before falling back to cloud.

**Root cause:** `_record_failure()` (which sets `_health.last_failure_at`) was only called inside `call_lmstudio()`, not in `check_health()`. A health-probe failure left `last_failure_at=0.0`. `should_try_local()` computes `monotonic() - 0.0 >= 60` — always `True`.

**Fix:** Added `_health.last_failure_at = time.monotonic()` to each failure exit path inside `check_health()`: remote-localhost mismatch, config validation error, model not configured, configured model not present, and exception during probe.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_check_health_no_model_loaded_updates_last_failure_at`

---

## Streaming retry discards `finish_reason` from fallback non-streaming completion

**Symptom:** When streaming fails and the non-streaming retry succeeds, the log entry `lmstudio_response_received` always shows `finish_reason=None` — the actual `finish_reason` ("stop", "length", etc.) from the retry completion is silently discarded.

**Root cause:** `reasoning_present = False; finish_reason = None` were assigned AFTER the streaming try/except block. The non-streaming retry inside the except block set `raw_content` correctly but did not update `reasoning_present` / `finish_reason` before the code fell through to the log statement at lines 607-608.

**Fix:** Moved the `False`/`None` defaults before the try/except so both paths initialise them. Added explicit extraction of `reasoning_present` and `finish_reason` from the retry completion inside the except block, mirroring the non-streaming success path.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_streaming_retry_captures_finish_reason`
