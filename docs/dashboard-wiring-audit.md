# Dashboard Wiring Audit — is it actually plugged into the bot?

**Date:** 2026-05-30

**Question that prompted this:** the deployed dashboard "looked like bullshit /
not plugged in" and inconsistent across pages. Is every page actually wired to
the live trading bot, or is any of it mock UI?

## Verdict

**Every page is wired to real backend data. None of it is a UI mock or demo.**
The frontend polls real REST endpoints (every 5–15s) plus a live WebSocket;
there is **no hardcoded sample/seed data** in the dashboard components. What
looked "dead" was a real, fully-wired system that was *starved of data* by two
root causes (below) — both now addressed.

## Page → data-source map

| Page (route) | Renders | Backend source |
|---|---|---|
| `/`, `/dashboard` | overview tiles | `GET /dashboard/state`, WebSocket |
| `/dashboard/agents` | live reasoning, LLM health, tool governance, decisions, notifications | `/dashboard/prompt-os`, `/llm/health`, `/dashboard/tools`, `/decisions`, `/decisions/stats`, `/notifications` |
| `/dashboard/learning` | grades, proposals, loss attribution, challenger shadows | `/learning/*`, `/dashboard/learning/*`, `/dashboard/challengers` |
| `/dashboard/proposals` | voteable proposals | `/dashboard/proposals` |
| `/dashboard/system` | health, stream lag, backtest, move distribution | `/dashboard/system-health`, `/system/*`, `/backtest/*` |
| `/dashboard/trading` | orders, positions, equity curve, P&L | `GET /dashboard/state`, `/dashboard/performance-trends` |

All 20 backend route files are mounted in `api/main.py` (both at root and under
`/api`). The most "real" panel is **Backtest — Strategy Comparison**: it replays
the production `classify_signal` → `trade_scorer` pipeline over real Alpaca
history.

## Why it looked dead — two root causes

### 1. The LLM brain was offline (operator/config — not a code bug)
`LLM_PROVIDER=lmstudio` pointed at a local GPU (Tailscale `100.112.224.78`) that
was unreachable, with `LLM_FALLBACK_ENABLED=false` and no cloud key set. So when
the local link dropped, the ReasoningAgent had nothing to fall back to and
emitted degraded `fallback:skip_reasoning` decisions (the "Fallback BUY ×172"
notifications). This cascaded into: tools "registered but never exercised",
idle challengers, and a 0% LLM success rate.

The multi-provider fallback chain (Groq → Gemini → Anthropic → OpenAI) **already
exists** in `api/services/llm_router.py`; it just had no key and was disabled.

**Operator fix (Render environment, no code):**
```
GROQ_API_KEY=<free key from console.groq.com>
LLM_FALLBACK_ENABLED=true
```
Then verify on `/llm/health` that `active_provider` flips `lmstudio → groq` and
`status` goes `live`.

### 2. The signal trigger never fired (code bug — FIXED)
`classify_signal` used fixed per-bar thresholds (1.5% / 3.0%) while the live
feed delivers ~0.01–0.3% per-bar moves, so it sat in `hold` forever → no
signals → idle challengers and an empty learning loop. Fixed by switching to a
volatility-normalized trigger (`move > k·sigma`). See
[troubleshooting/signal-generation.md](troubleshooting/signal-generation.md).

## "Seeded" vs "live" — the one nuance
- **Tool Governance α-scores** start as *seeded illustrative priors* in
  `tool_registry.default_tools()` and are overwritten by live EMA telemetry once
  the ReasoningAgent actually exercises each tool (which needs the LLM up).
- **Recent Decisions `Total`** is the all-time `decisions:recent` list (capped
  at 500); `Buys/Sells/Holds` are last-hour. These are now explicitly labelled
  in the panel so they aren't misread as one running total.

## After both root causes are resolved
With the Groq key set and the signal fix deployed, expect: real buy/sell
decisions flowing, tools getting exercised (α-scores updating off priors),
challengers accumulating fills, closed trades feeding grades, and the learning
loop producing proposals — the same panels, now fed.
