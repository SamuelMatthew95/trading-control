# Local Inference — LM Studio + LM Link

Run your own GPU model alongside the cloud provider. The trading-control
backend tries the local model first on every `call_llm()` and
`call_llm_with_system()` call; if it fails or is disabled it falls
through to the cloud provider transparently.

---

## How it works

```
call_llm() / call_llm_with_system()
         │
         ▼  LM_STUDIO_ENABLED=true?
    lmstudio_provider.call_lmstudio()
         │ success → return result
         │ LMStudioUnavailableError (any failure) → fall through
         ▼
    Cloud provider  (LLM_PROVIDER=gemini/groq/anthropic/openai)
```

All LM Studio SDK interaction is isolated in
`api/services/lmstudio_provider.py`. No other module touches the SDK.

---

## Env vars (add these in Render → Environment → Environment Variables)

### Required to enable local inference

| Variable | Example value | Notes |
|---|---|---|
| `LM_STUDIO_ENABLED` | `true` | Master switch — defaults to `false` |
| `LM_STUDIO_HOST` | `127.0.0.1` | LM Studio server IP/hostname |
| `LM_STUDIO_PORT` | `1234` | LM Studio HTTP port (default 1234) |
| `LM_STUDIO_MODEL` | `lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF` | **Must match the model identifier shown in LM Studio** — leave blank and the call is rejected immediately |
| `LM_STUDIO_TIMEOUT_SECONDS` | `20` | Per-call timeout before falling back to cloud |

### Required only when using LM Link (remote GPU)

LM Link lets LM Studio on your home machine accept connections from a
hosted backend (e.g. Render) without opening a port. Enable these **in
addition to** the vars above.

| Variable | Example value | Notes |
|---|---|---|
| `LM_LINK_ENABLED` | `true` | Must be `true` for the token to be used |
| `LM_LINK_TOKEN` | `lmlink_abc123…` | The token shown in LM Studio → LM Link panel |
| `LM_LINK_DEVICE_NAME` | `home-rtx4090` | Human label for logs — optional |
| `LM_STUDIO_HOST` | `relay.lmlink.io` | Replace with the LM Link relay host |
| `LM_STUDIO_PORT` | `443` | Replace with the LM Link relay port |

> The token is passed to the SDK as `api_key` and is **never logged**.

### Cloud fallback (unchanged — already required)

| Variable | Notes |
|---|---|
| `LLM_PROVIDER` | `gemini` / `groq` / `anthropic` / `openai` — used when local inference fails |
| `GEMINI_API_KEY` / `GROQ_API_KEY` / … | API key for the chosen cloud provider |

---

## Quick-start: local LM Studio (same machine as backend)

```bash
# .env or Render env vars
LM_STUDIO_ENABLED=true
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234
LM_STUDIO_MODEL=lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF
LM_STUDIO_TIMEOUT_SECONDS=20
# LM Link not needed for local
LM_LINK_ENABLED=false
```

Make sure LM Studio is running with the server enabled and the model is
loaded before starting the backend.

---

## Quick-start: LM Link (home GPU → Render)

1. Open LM Studio → LM Link panel → copy the relay host, port, and token.
2. Load the model you want to serve.
3. In Render, set:

```bash
LM_STUDIO_ENABLED=true
LM_STUDIO_HOST=<relay host from LM Link panel>
LM_STUDIO_PORT=<relay port from LM Link panel>
LM_STUDIO_MODEL=<exact model id>
LM_STUDIO_TIMEOUT_SECONDS=30    # higher for remote latency
LM_LINK_ENABLED=true
LM_LINK_TOKEN=<token from LM Link panel>
LM_LINK_DEVICE_NAME=my-gpu      # optional label
```

---

## Health check

The `/llm/health` endpoint shows the local inference state:

```json
{
  "status": "live",
  "provider": "gemini",
  "lm_studio_enabled": true,
  "lm_studio_healthy": true,
  "local_model": "lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF",
  "local_fallback_count": 0,
  "last_local_error": null
}
```

`lm_studio_healthy` goes `false` when the last probe or call failed;
`local_fallback_count` increments on every failure (including malformed
output); `last_local_error` holds the most recent failure reason.

---

## Troubleshooting

See `docs/troubleshooting/lm-studio.md` for known failure modes and fixes.
