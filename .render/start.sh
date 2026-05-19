#!/usr/bin/env bash
# Render start script — starts Tailscale userspace networking then the app.
#
# Tailscale configuration for LM Studio over Tailscale:
#   LM_STUDIO_HOST       = Tailscale IP of the Mac running LM Studio (e.g. 100.112.224.78)
#   LM_STUDIO_PORT       = 1234  (LM Studio default)
#   LM_STUDIO_PROXY_URL  = http://127.0.0.1:1055  (HTTP CONNECT proxy below)
#
# tailscaled is started with two proxy listeners on localhost:1055:
#   --socks5-server             SOCKS5 proxy (for non-httpx clients)
#   --outbound-http-proxy-listen HTTP CONNECT proxy (used by httpx via LM_STUDIO_PROXY_URL)
#
# TAILSCALE_AUTHKEY must be set in Render env vars (use a reusable/ephemeral key).
set -euo pipefail

if [[ -f .render/bin/tailscaled ]]; then
    .render/bin/tailscaled \
        --tun=userspace-networking \
        --socks5-server=localhost:1055 \
        --outbound-http-proxy-listen=localhost:1055 \
        --state=/tmp/tailscale.state \
        &

    # Give tailscaled time to initialise before connecting.
    sleep 5

    .render/bin/tailscale up \
        --authkey="${TAILSCALE_AUTHKEY}" \
        --hostname="${RENDER_SERVICE_NAME:-trading-control}"

    echo "Tailscale connected. Starting app."
else
    echo "Tailscale binaries not found — skipping Tailscale startup."
fi

exec gunicorn api.main:app \
    -w 1 \
    -k uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:${PORT}"
