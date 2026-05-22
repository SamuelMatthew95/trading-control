# Local Inference — LM Studio

Run a local GPU model alongside (or instead of) a cloud provider.
The app always boots — local inference unavailability is never fatal.

---

## How it works

```
call_llm()                          call_llm_with_system()
     │                                       │
     ▼                                       ▼
lmstudio_provider.call_lmstudio()   lmstudio_provider.call_lmstudio()
     │  parse_json=True (default)        │  parse_json=False (freeform text)
     │  Returns valid trade JSON OR       │  Returns raw text as-is
     │  safe HOLD fallback JSON           │
     │
     │  LMStudioUnavailableError?
     ▼
  Cloud provider  (LLM_PROVIDER = groq / gemini / anthropic / openai)
  (only if LLM_FALLBACK_ENABLED=true and a cloud API key is configured)
```

All LM Studio interaction is in `api/services/lmstudio_provider.py`.
The provider uses `openai.AsyncOpenAI` against LM Studio's OpenAI-compatible
REST endpoint (`/v1`) — not the OpenAI cloud.  No other module imports the
openai client for local inference.

### When does LM Studio activate?

Either condition triggers LM Studio as the first-try provider:

| Setting | Effect |
|---|---|
| `LLM_PROVIDER=lmstudio` | LM Studio is the primary provider. Cloud fallback only if `LLM_FALLBACK_ENABLED=true`. |
| `LM_STUDIO_ENABLED=true` | LM Studio tried first, cloud provider (`LLM_PROVIDER`) is the fallback. |

**Recommended**: use `LLM_PROVIDER=lmstudio` with `LLM_FALLBACK_ENABLED=false`.
This makes LM Studio the sole inference path with no silent cloud escape hatch.

---

## Inference parameters

LM Studio has its own dedicated env vars — separate from the cloud provider constants.

| Env var | Default | Purpose |
|---|---|---|
| `LM_STUDIO_MODEL` | `meta-llama-3.1-8b-instruct` | Exact model ID shown in LM Studio — must match `/v1/models` |
| `LM_STUDIO_TEMPERATURE` | `0.0` | 0 = fully deterministic; same prompt → same JSON every time |
| `LM_STUDIO_MAX_TOKENS` | `256` | Global token budget; 256 is enough for a clean trading JSON |
| `LM_STUDIO_MAX_TOKENS_ANALYSIS` | `256` | Token budget for price-analysis signals |
| `LM_STUDIO_MAX_TOKENS_EXECUTION` | `256` | Token budget for trade-execution decisions |
| `LM_STUDIO_MAX_TOKENS_HEALTH_CHECK` | `256` | Token budget for health-check calls |
| `LM_STUDIO_STREAM` | `false` | `true` enables streaming; adds resilience on slow/unstable connections but is slower to set up |
| `LM_STUDIO_TIMEOUT_SECONDS` | `30` | Per-call timeout before raising `LMStudioUnavailableError` |

> **Why temperature=0?**  Instruct models like Llama 3.1 produce valid, parseable JSON
> reliably at temperature 0.  Higher values introduce randomness with no benefit for a
> bounded `{"action": "buy/sell/hold"}` decision.

---

## Response validation

`call_lmstudio()` validates every trading-decision response through three gates:

1. **Must parse as JSON** — if not, `_extract_json_from_text` scans the prose for any
   embedded `{...}` block and retries.  Failure → HOLD fallback.
2. **Must be a JSON object (dict)** — `[]`, `null`, `"string"`, `42` are valid JSON but
   not valid decisions.  Non-dict → HOLD fallback.
3. **`action` must be `buy / sell / hold / reject`** — any other value → HOLD fallback.

HOLD fallback JSON is returned directly by the provider; no cloud call is made and
`_health.healthy` stays `True` (infrastructure worked, only the output was unusable).

```json
{
  "action": "hold",
  "confidence": 0.0,
  "primary_edge": "lmstudio_fallback",
  "risk_factors": ["LM Studio returned invalid or empty JSON"],
  "size_pct": 0.0,
  "stop_atr_x": 0.0,
  "rr_ratio": 0.0,
  "latency_ms": 0,
  "cost_usd": 0.0,
  "trace_id": "...",
  "fallback": true
}
```

`LMStudioUnavailableError` is only raised for infrastructure failures (empty response,
timeout, connection refused).  Bad JSON output never raises — it always produces HOLD.

---

## Quickstart — local backend + local LM Studio (same machine)

```bash
# 1. Load meta-llama-3.1-8b-instruct in LM Studio (or any instruct model)
# 2. Start LM Studio's local server on port 1234
# 3. Set these env vars and start the backend:

LLM_PROVIDER=lmstudio
LLM_FALLBACK_ENABLED=false
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=meta-llama-3.1-8b-instruct
LM_STUDIO_TEMPERATURE=0
LM_STUDIO_MAX_TOKENS=128
LM_STUDIO_STREAM=false
```

Verify the model is loaded before starting:

```bash
curl -s http://localhost:1234/v1/models | jq '.data[].id'

# Quick round-trip test:
curl -s http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer lm-studio" \
  -d '{
    "model": "meta-llama-3.1-8b-instruct",
    "messages": [{"role":"user","content":
      "Return only this JSON: {\"action\":\"hold\",\"confidence\":0.5,\"reason\":\"test\"}"}],
    "max_tokens": 128,
    "temperature": 0,
    "stream": false
  }' | jq '.choices[0].message.content'
```

---

## Remote backend + LM Studio via Tailscale

A Render backend cannot reach `localhost:1234` on your laptop.
Use Tailscale to create an encrypted peer-to-peer connection.

```
LLM_PROVIDER=lmstudio
LLM_FALLBACK_ENABLED=false
LM_STUDIO_HOST=<tailscale-ip-of-mac>   # e.g. 100.112.224.78 — NOT 127.0.0.1
LM_STUDIO_PORT=1234
LM_STUDIO_MODEL=meta-llama-3.1-8b-instruct
LM_STUDIO_TIMEOUT_SECONDS=30
LM_STUDIO_PROXY_URL=http://127.0.0.1:1055   # Tailscale HTTP CONNECT proxy
LM_LINK_ENABLED=true
TAILSCALE_AUTHKEY=tskey-auth-...
```

`LM_STUDIO_PROXY_URL` is required when Tailscale runs in userspace-networking mode
(`--tun=userspace-networking`).  Traffic to Tailscale peers must go through the HTTP
CONNECT proxy that `tailscaled` exposes at `localhost:1055`.

**Never** set `LM_STUDIO_HOST=127.0.0.1:1055` — that is the proxy, not LM Studio.
`validate_lm_studio_config()` will catch this and fail fast at startup.

---

## Full env var reference

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Set to `lmstudio` to make LM Studio the primary provider |
| `LLM_FALLBACK_ENABLED` | `true` | Set to `false` to disable cloud fallback entirely |
| `LM_STUDIO_ENABLED` | `false` | Alternative to `LLM_PROVIDER=lmstudio`; used when you want LM Studio as first-try with a cloud fallback |
| `LM_STUDIO_BASE_URL` | _(empty)_ | Full base URL override, e.g. `http://localhost:1234/v1`; takes precedence over HOST+PORT |
| `LM_STUDIO_HOST` | `127.0.0.1` | Ignored when `LM_STUDIO_BASE_URL` is set |
| `LM_STUDIO_PORT` | `1234` | Ignored when `LM_STUDIO_BASE_URL` is set |
| `LM_STUDIO_MODEL` | `meta-llama-3.1-8b-instruct` | Must match exactly what `/v1/models` returns |
| `LM_STUDIO_TEMPERATURE` | `0.0` | Use 0 for deterministic JSON; raise only for freeform creative tasks |
| `LM_STUDIO_MAX_TOKENS` | `256` | Global default; per-task vars override |
| `LM_STUDIO_MAX_TOKENS_ANALYSIS` | `256` | Token budget for price-analysis signals |
| `LM_STUDIO_MAX_TOKENS_EXECUTION` | `256` | Token budget for trade-execution decisions |
| `LM_STUDIO_MAX_TOKENS_HEALTH_CHECK` | `256` | Token budget for health-check calls |
| `LM_STUDIO_STREAM` | `false` | Enable streaming (keeps TCP alive on slow models over Tailscale) |
| `LM_STUDIO_TIMEOUT_SECONDS` | `30` | Per-call timeout in seconds |
| `LM_STUDIO_PROXY_URL` | _(empty)_ | HTTP CONNECT proxy for Tailscale userspace networking, e.g. `http://127.0.0.1:1055` |
| `LM_LINK_ENABLED` | `false` | Cosmetic — appears in startup logs to indicate remote GPU setup |
| `LM_LINK_DEVICE_NAME` | _(empty)_ | Human label in startup logs |
| `LM_LINK_TOKEN` | _(empty)_ | Bearer token for a custom auth proxy in front of LM Studio; not needed for plain Tailscale |

---

## Verifying it works

Check `/llm/health` after startup:

```json
{
  "status": "live",
  "active_provider": "lmstudio",
  "lm_studio_enabled": true,
  "lm_studio_healthy": true,
  "local_model": "meta-llama-3.1-8b-instruct",
  "local_latency_ms": 850,
  "local_fallback_count": 0,
  "last_local_error": null,
  "remote_localhost_mismatch": false
}
```

| Field | Meaning |
|---|---|
| `active_provider` | `"lmstudio"` when local is healthy; cloud provider name when falling back |
| `lm_studio_healthy` | `true` = last probe or call succeeded |
| `local_latency_ms` | round-trip ms for the last successful call |
| `local_fallback_count` | increments on every infrastructure failure |
| `last_local_error` | most recent failure reason |
| `remote_localhost_mismatch` | `true` when backend is remote (Render) but host is localhost — LM Studio is unreachable |

---

## Call capacity

`ReasoningAgent` is the only agent that calls the LLM. It processes one Redis message
at a time (consumer-group model) — **at most one local inference call is in flight at
any moment**. This is a perfect match for LM Studio's single-request default.

| Model | Typical latency | Max calls/min |
|---|---|---|
| Llama-3.1-8B Q4 | 0.5–3 s | 20–120 |
| Llama-3.1-13B Q4 | 2–8 s | 7–30 |
| Llama-3.1-70B Q4 | 15–60 s | 1–4 |

---

## Common failure reasons

| `last_local_error` | Fix |
|---|---|
| `lm_studio_model_not_configured` | Set `LM_STUDIO_MODEL` to the exact model id from `/v1/models` |
| `no_model_loaded` | Load a model in LM Studio before starting the backend |
| `timeout` | Model too slow; reduce `LM_STUDIO_MAX_TOKENS` or use a smaller model |
| `lmstudio_connection_failed` | LM Studio not running, wrong host/port, or Tailscale not connected |
| `lmstudio_empty_response` | Model returned no content — OOM, crashed mid-generation, or the model was just unloaded |
| `lm_studio_model_not_configured` in health but inference worked | Blank or whitespace-only `LM_STUDIO_MODEL` — `.strip()` evaluates to empty |

See `docs/troubleshooting/lm-studio.md` for full symptom → fix entries.
