# Tailscale / Proxy Troubleshooting

These logs come from the **`tailscaled` binary** (launched by `.render/start.sh`),
not from our Python application. Our code never emits `peerapi:` or `socks5:`
lines — they appear in this repo only as explanatory comments in
`api/services/lmstudio_provider.py`. `tailscaled` exists solely to reach LM Studio
on a developer Mac over Tailscale in userspace-networking mode.

> **Scope note.** Our app does not own the SOCKS5 or peerAPI listeners —
> `tailscaled` does. So protocol sniffing, per-connection PID/stack logging, and
> "reject + log once" cannot be added to those listeners from our code. The real
> fix is to stop generating the bad traffic (port split below) and to make the
> app-side proxy target observable, not to scrape/aggregate `tailscaled` logs.

## tailscaled logs "incompatible SOCKS version" every few seconds

**Symptom:** `socks5: client connection failed: incompatible SOCKS version`
repeats while LM Studio inference / health checks run, even though Tailscale,
Redis, and Alpaca are all healthy.

**Root cause:** `.render/start.sh` launched tailscaled with BOTH
`--socks5-server=localhost:1055` and `--outbound-http-proxy-listen=localhost:1055`
on the **same port**. Our only client of `:1055` is httpx, which uses it as an
**HTTP CONNECT** proxy (`LMStudioProvider._make_client()` →
`httpx.AsyncClient(proxy="http://127.0.0.1:1055", trust_env=False)`). HTTP CONNECT
begins with `CONNECT…`; the SOCKS5 handler read the first byte (`'C'` = 0x43) as a
SOCKS protocol version and rejected it. Nothing in our stack uses SOCKS as a
client (no `socks5://` anywhere), so the SOCKS5 listener on the shared port was
pure liability.

**Fix:** Split the listeners onto distinct ports in `.render/start.sh`. The HTTP
CONNECT proxy stays on **1055** (so `LM_STUDIO_PROXY_URL=http://127.0.0.1:1055`
and the Render env vars are unchanged); SOCKS5 moves to **1056**. HTTP traffic to
`:1055` now reaches only the HTTP proxy handler — the SOCKS errors stop at the
source. SOCKS5 stays available on `:1056` for non-httpx clients (not disabled).
Boot diagnostics echo the proxy topology + LM Studio target so any recurrence is
traceable to a port/target within seconds.

**Regression test:** `tests/core/test_tailscale_proxy_config.py::test_socks_and_http_proxy_on_distinct_ports`

## tailscaled logs "peerapi: unknown peer 127.0.0.1:NNNNN"

**Symptom:** `peerapi: unknown peer 127.0.0.1:NNNNN` repeats for local
(`127.0.0.1`) source connections.

**Root cause (tailscaled-internal, generally benign):** tailscaled's peerAPI
accepts connections only from known tailnet peers; a connection whose source is
`127.0.0.1` is not a peer, so tailscaled rejects it and logs "unknown peer". This
is NOT emitted by our application and does not indicate an app fault. The usual
local sources are (a) a CONNECT through the HTTP proxy whose destination resolves
to the node's OWN Tailscale IP or a loopback — which happens when `LM_STUDIO_HOST`
is mis-pointed at the Render node itself instead of the Mac — or (b) a local
port probe/scan.

**Fix / handling:** Not fixable inside application code (we don't own the peerAPI
listener). The actionable controls on our side are the existing config guards that
forbid `LM_STUDIO_HOST` / `LM_STUDIO_BASE_URL` being a loopback or the `:1055`
proxy endpoint (`_BLOCKED_HOST_PORT`, `validate_lm_studio_config`), plus the new
boot-diagnostic topology line — read it to confirm the CONNECT target is the Mac's
Tailscale IP, not the node itself. If the line is confirmed benign and still
noisy, lower tailscaled's own verbosity; do not aggregate tailscaled logs into app
metrics as a substitute for fixing the target.

**Regression test:** `tests/agents/test_lmstudio_provider.py::test_validate_config_rejects_127_0_0_1_port_1055` (prevents the mis-target that drives self-CONNECT peerAPI churn)
