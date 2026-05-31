"""Guardrail: tailscaled's SOCKS5 and HTTP CONNECT proxy must listen on
DIFFERENT ports in the Render start script.

When both shared ``localhost:1055``, httpx's HTTP CONNECT bytes (``CONNECT…``,
first byte ``'C'`` = 0x43) reached tailscaled's SOCKS5 handler, which read the
method byte as a SOCKS protocol version and logged
``socks5: client connection failed: incompatible SOCKS version`` on every
LM Studio call.

Invariants enforced here:
- The HTTP CONNECT proxy stays on 1055 so ``LM_STUDIO_PROXY_URL=http://127.0.0.1:1055``
  (and the Render env vars) are unchanged.
- SOCKS5 remains configured (functionality not removed) but on its own port.
- The two listeners never share a port.

Regression for: ``.render/start.sh`` launching tailscaled with
``--socks5-server`` and ``--outbound-http-proxy-listen`` on the same port.
"""

from __future__ import annotations

import re
from pathlib import Path

START_SH = Path(__file__).resolve().parents[2] / ".render" / "start.sh"


def _flag_port(script: str, flag: str) -> str | None:
    match = re.search(rf"--{re.escape(flag)}=localhost:(\d+)", script)
    return match.group(1) if match else None


def test_socks_and_http_proxy_on_distinct_ports() -> None:
    script = START_SH.read_text(encoding="utf-8")

    socks_port = _flag_port(script, "socks5-server")
    http_port = _flag_port(script, "outbound-http-proxy-listen")

    # Both proxies must remain configured — the fix splits ports, it does not
    # disable SOCKS or the HTTP proxy.
    assert socks_port is not None, "tailscaled --socks5-server flag missing from .render/start.sh"
    assert http_port is not None, (
        "tailscaled --outbound-http-proxy-listen flag missing from .render/start.sh"
    )

    # The HTTP CONNECT proxy must stay on 1055 — LM_STUDIO_PROXY_URL points here
    # and the Render env vars must not need to change.
    assert http_port == "1055", (
        f"HTTP CONNECT proxy must stay on 1055 (LM_STUDIO_PROXY_URL contract); got {http_port}"
    )

    # Sharing a port routes HTTP CONNECT bytes into the SOCKS5 handler →
    # "incompatible SOCKS version" spam.
    assert socks_port != http_port, (
        f"SOCKS5 and HTTP CONNECT proxy must use different ports; both on {socks_port}"
    )
