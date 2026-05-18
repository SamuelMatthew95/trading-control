# Local Inference — LM Studio + LM Link

Run your own GPU model alongside the cloud provider.  Every `call_llm()`
and `call_llm_with_system()` tries the local model first; if it fails
(or is disabled) it falls through to the configured cloud provider
transparently.  The app always boots — local inference unavailability is
never fatal.

---

## Architecture

```
call_llm() / call_llm_with_system()
      │
      ▼  LM_STUDIO_ENABLED=true?
  lmstudio_provider.call_lmstudio()
      │  success  →  return result
      │  LMStudioUnavailableError  →  fall through silently
      ▼
  Cloud provider  (LLM_PROVIDER = gemini / groq / anthropic / openai)
```

All LM Studio interaction lives in `api/services/lmstudio_provider.py`.
The provider uses `openai.AsyncOpenAI` pointed at LM Studio's
OpenAI-compatible REST endpoint (`/v1`) — **not the OpenAI cloud service**.
You can load any model LM Studio supports (Llama, Mistral, Phi, Qwen, etc.).
No other file imports the openai client for local inference directly.

---

## Call parameters (shared across all providers)

Defined in `api/constants.py` — change once, applies everywhere:

| Constant | Value | Used in |
|---|---|---|
| `LLM_MAX_TOKENS_TRADING` | 300 | `call_llm()` — JSON trading decision |
| `LLM_TEMPERATURE_TRADING` | 0.0 | `call_llm()` — deterministic JSON |
| `LLM_MAX_TOKENS_ANALYSIS` | 800 | `call_llm_with_system()` — reasoning / reflection |
| `LLM_TEMPERATURE_ANALYSIS` | 0.3 | `call_llm_with_system()` — free-text reasoning |
| `LLM_TIMEOUT_SECONDS` | 90 | Cloud + local inference timeout (from `settings.LLM_TIMEOUT_SECONDS`) |

---

## Env vars — what to set in Render

### Option A — Local LM Studio (same machine as backend)

```
LM_STUDIO_ENABLED=true
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234
LM_STUDIO_MODEL=<exact model id shown in LM Studio>
LM_STUDIO_TIMEOUT_SECONDS=90
LM_LINK_ENABLED=false
```

### Option B — LM Link (home GPU → Render cloud)

LM Link uses **Tailscale** to create an encrypted peer-to-peer mesh between
your home GPU machine and the Render backend — no open ports required.
There is no relay host or bearer token from LM Studio; authentication is
Tailscale identity-based.

Setup steps:
1. Install Tailscale on both the home GPU machine and the Render instance.
2. Log in both devices to the same Tailscale account (`tailscale up`).
3. Find the Tailscale IP or MagicDNS hostname of the GPU machine
   (`tailscale ip` or the Tailscale admin panel).
4. Set `LM_STUDIO_HOST` to that Tailscale IP/hostname and leave
   `LM_STUDIO_PORT` at `1234` (LM Studio's default).

```
LM_STUDIO_ENABLED=true
LM_STUDIO_HOST=<Tailscale IP or hostname of your GPU machine>
LM_STUDIO_PORT=1234
LM_STUDIO_MODEL=<exact model id shown in LM Studio>
LM_STUDIO_TIMEOUT_SECONDS=90
LM_LINK_ENABLED=true
LM_LINK_DEVICE_NAME=my-gpu-rig      # optional — appears in startup logs only
```

`LM_LINK_TOKEN` is only needed if you put a custom authenticating proxy
(e.g. nginx + HTTP basic auth) in front of LM Studio.  LM Studio itself
ignores HTTP `Authorization` headers — leave `LM_LINK_TOKEN` unset for
a plain Tailscale setup.

### Cloud fallback (always required)

The cloud provider is used when local inference fails or is disabled.

```
LLM_PROVIDER=gemini                 # or groq / anthropic / openai
GEMINI_API_KEY=<your key>           # key for whichever provider you chose
```

---

## Full env var reference

| Variable | Default | Required? | Notes |
|---|---|---|---|
| `LM_STUDIO_ENABLED` | `false` | Only for local inference | Master on/off switch |
| `LM_STUDIO_HOST` | `127.0.0.1` | When enabled | IP or hostname of LM Studio server |
| `LM_STUDIO_PORT` | `1234` | When enabled | HTTP port |
| `LM_STUDIO_MODEL` | _(empty)_ | **Yes, when enabled** | Must match exactly what LM Studio shows — blank causes immediate fallback |
| `LM_STUDIO_TIMEOUT_SECONDS` | `90` | No | Per-call timeout before falling back to cloud |
| `LM_LINK_ENABLED` | `false` | Only for remote GPU | Signal that LM Studio is on a remote machine reachable via Tailscale (LM Link); used for log context only |
| `LM_LINK_TOKEN` | _(empty)_ | No | Optional bearer token for a custom authenticating proxy in front of LM Studio; not required for plain Tailscale/LM Link |
| `LM_LINK_DEVICE_NAME` | _(empty)_ | No | Human label; appears in startup logs |
| `LLM_PROVIDER` | `gemini` | Yes | Cloud fallback provider |
| `GEMINI_API_KEY` | _(empty)_ | When provider=gemini | |
| `GROQ_API_KEY` | _(empty)_ | When provider=groq | |
| `ANTHROPIC_API_KEY` | _(empty)_ | When provider=anthropic | |
| `OPENAI_API_KEY` | _(empty)_ | When provider=openai | |
| `LLM_TIMEOUT_SECONDS` | `90` | No | Shared timeout for cloud provider calls |
| `LLM_MAX_RETRIES` | `2` | No | Retry attempts on transient cloud errors |

---

## Verifying it works

Check `/llm/health` after startup:

```json
{
  "status": "live",
  "provider": "gemini",
  "active_provider": "lmstudio",
  "lm_studio_enabled": true,
  "lm_studio_healthy": true,
  "local_model": "lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF",
  "local_latency_ms": 312,
  "local_fallback_count": 0,
  "last_local_error": null
}
```

| Field | Meaning |
|---|---|
| `active_provider` | `"lmstudio"` when local is healthy, cloud name otherwise — what is actually serving requests right now |
| `lm_studio_healthy` | `true` = last probe/call succeeded |
| `local_latency_ms` | round-trip ms for the last successful local call |
| `local_fallback_count` | increments on every failure (including bad JSON output) |
| `last_local_error` | most recent failure reason, e.g. `"timeout"`, `"lm_studio_model_not_configured"` |

---

## Common failure reasons

| `last_local_error` | Fix |
|---|---|
| `lm_studio_model_not_configured` | Set `LM_STUDIO_MODEL` to the exact model id |
| `no_model_loaded` | Load a model in LM Studio before starting the backend |
| `timeout` | LM Studio server is too slow; increase `LM_STUDIO_TIMEOUT_SECONDS` or use a smaller model |
| `lmstudio_connection_failed: ...` | LM Studio server is not running or wrong host/port |
| `connection refused` | LM Studio server is not running or wrong host/port |

See `docs/troubleshooting/lm-studio.md` for full symptom → fix entries.
