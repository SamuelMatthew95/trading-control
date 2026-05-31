# Troubleshooting

Each file covers one subsystem. When a bug is found and fixed, add it to the right file here **in the same commit as the fix** — no separate step, no prompt needed.

| File | Covers |
|---|---|
| [notifications.md](notifications.md) | Buy/sell notification pipeline, WebSocket delivery, dedup |
| [execution-engine.md](execution-engine.md) | Score parsing, fill publishing, decisions backlog |
| [system-routes.md](system-routes.md) | Stream lag endpoint, trading-mode status, memory-mode guards |
| [ci-cd.md](ci-cd.md) | CI lint failures, ruff version pinning, GitHub Actions config |
| [frontend.md](frontend.md) | Dashboard UI bugs: stat tiles, P&L display, win-rate fallback |
| [lm-studio.md](lm-studio.md) | LM Studio / LM Link local inference: startup, timeout, fallback, secrets |
| [backtest.md](backtest.md) | Strategy-comparison harness: eligibility gates, NO SIGNALS vs 0.00, verdict honesty |
| [signal-generation.md](signal-generation.md) | Live SignalGenerator trigger: volatility-normalized vs fixed-% thresholds, idle-bot / "no signals" |
| [tailscale.md](tailscale.md) | tailscaled proxy noise: SOCKS5 vs HTTP-CONNECT port split, peerAPI "unknown peer" diagnosis |

New subsystem → create `docs/troubleshooting/<subsystem>.md` and add a row above.

---

## Entry format

Every entry must have all four fields:

```markdown
## <Short title — what broke>

**Symptom:** What the operator or developer observed.

**Root cause:** Why it happened.

**Fix:** What changed and where.

**Regression test:** `tests/path/test_file.py::test_function_name`
```

No regression test = entry is incomplete. The test is what proves the bug won't silently return.
