#!/usr/bin/env bash
# Render start script — starts Tailscale userspace networking then the app.
#
# Tailscale configuration for LM Studio over Tailscale:
#   LM_STUDIO_HOST       = Tailscale IP of the Mac running LM Studio (e.g. 100.112.224.78)
#   LM_STUDIO_PORT       = 1234  (LM Studio default)
#   LM_STUDIO_PROXY_URL  = http://127.0.0.1:1055  (HTTP CONNECT proxy below)
#
# tailscaled is started with two proxy listeners on SEPARATE ports so HTTP
# CONNECT traffic never lands on the SOCKS5 handler (a shared port made
# tailscaled log "socks5: ... incompatible SOCKS version" on every LM Studio call):
#   --socks5-server=localhost:1056              SOCKS5 proxy (for non-httpx clients)
#   --outbound-http-proxy-listen=localhost:1055 HTTP CONNECT proxy (httpx via LM_STUDIO_PROXY_URL)
#
# TAILSCALE_AUTHKEY must be set in Render env vars (use a reusable/ephemeral key).
# Tailscale startup is skipped when TAILSCALE_AUTHKEY is absent or empty so that
# deployments without LM Studio/Tailscale still start normally.
set -euo pipefail

# Use ${VAR:-} (default-empty) so set -u doesn't abort when the key is unset.
_ts_authkey="${TAILSCALE_AUTHKEY:-}"

if [[ -f .render/bin/tailscaled && -n "${_ts_authkey}" ]]; then
    # SOCKS5 (1056) and HTTP CONNECT (1055) MUST stay on different ports.
    # httpx sends HTTP CONNECT to 1055 (LM_STUDIO_PROXY_URL); when SOCKS5 also
    # bound 1055 those bytes hit the SOCKS handler → "incompatible SOCKS
    # version" spam. HTTP CONNECT stays on 1055 so the env var is unchanged.
    .render/bin/tailscaled \
        --tun=userspace-networking \
        --socks5-server=localhost:1056 \
        --outbound-http-proxy-listen=localhost:1055 \
        --state=/tmp/tailscale.state \
        &

    # Give tailscaled time to initialise before connecting.
    sleep 5

    .render/bin/tailscale up \
        --authkey="${_ts_authkey}" \
        --hostname="${RENDER_SERVICE_NAME:-trading-control}"

    echo "Tailscale connected. Starting app."
    # Boot diagnostics: make the proxy topology + LM Studio target visible in
    # deploy logs so any future tailscaled "incompatible SOCKS version" /
    # "peerapi unknown peer" noise is traceable to a port/target in seconds.
    # No secrets are printed (LM_LINK_TOKEN is never echoed).
    echo "tailscale_proxy_topology socks5=localhost:1056 http_connect=localhost:1055"
    echo "lmstudio_target host=${LM_STUDIO_HOST:-unset} port=${LM_STUDIO_PORT:-unset} proxy=${LM_STUDIO_PROXY_URL:-unset}"
else
    echo "Tailscale binaries not found or TAILSCALE_AUTHKEY not set — skipping Tailscale startup."
fi

exec gunicorn api.main:app \
    -w 1 \
    -k uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:${PORT}"
