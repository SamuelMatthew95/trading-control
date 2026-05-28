# Price Poller Troubleshooting

## SSLZeroReturnError(6) EOF — repeated worker failures against data.alpaca.markets

**Symptom:** Repeated log entries:
```
SSLError: SSLZeroReturnError(6, 'TLS/SSL connection has been closed (EOF)')
```
against `/v2/stocks/quotes/latest` and `/v1beta3/crypto/us/latest/quotes`. Workers log
`alpaca_crypto_fetch_failed` / `alpaca_stocks_fetch_failed` every poll cycle. Tailscale
warnings (`stopped`, `warming-up`, `DNS base config unsupported`) appear alongside the SSL errors.

**Root cause:** The alpaca-py SDK's internal `requests.Session` kept a pool of keepalive TCP
connections. Render's NAT table silently drops outbound TCP sockets idle for ~60 s. When the
poller tried to reuse a pooled socket after an idle window (e.g. startup, circuit-breaker
cooldown), the remote server had already torn it down, so the TLS layer received EOF instead
of a handshake response — `SSLZeroReturnError(6)`. urllib3's default retry (`total=0`) did not
retry on SSL errors, so the failure surfaced immediately. Tailscale interference with the DNS
stack was a contributing factor but not the primary cause (DNS failures produce
`ConnectionError`/`socket.gaierror`, not `SSLZeroReturnError`).

Secondary issue: `timeout=None` in the SDK's requests calls meant that a hung TCP connection
would block the thread in `run_in_executor` indefinitely. `asyncio.wait_for` cancelled the
coroutine, but the thread kept running — with two concurrent fetch tasks this could starve the
thread pool.

**Fix:**
- Replaced alpaca-py SDK (`CryptoHistoricalDataClient`, `StockHistoricalDataClient`) with a
  direct `httpx.AsyncClient` in `api/workers/price_poller.py`.
- `httpx.Limits(keepalive_expiry=20.0)`: connections idle for 20 s are proactively closed —
  below Render's NAT timeout, so the stale-socket scenario never arises.
- Explicit `httpx.Timeout(connect=5, read=10)` on every request; `asyncio.wait_for` is no
  longer used (native async, no thread executor).
- `_is_ssl_eof()`: traverses the exception `__cause__`/`__context__` chain to detect
  `ssl.SSLError` (parent of `SSLZeroReturnError`) through httpx's wrapping layers.
- On SSL EOF detection: client is `aclose()`d and recreated to evict any remaining poisoned
  connections from the pool.
- Circuit breaker: 5 consecutive failures → 60 s cooldown (`alpaca_circuit_breaker_open` log),
  after which polls resume automatically.
- Secondary fix: `api/services/execution/brokers/alpaca.py` — all `aiohttp.ClientSession()`
  calls now pass `timeout=_AIOHTTP_TIMEOUT` (connect=5 s, read=10 s, total=60 s).

**Regression tests:**
- `tests/core/test_price_poller.py::test_is_ssl_eof_detects_ssl_zero_return_error`
- `tests/core/test_price_poller.py::test_is_ssl_eof_detects_through_httpx_connect_error`
- `tests/core/test_price_poller.py::test_fetch_crypto_propagates_ssl_eof_error`
- `tests/core/test_price_poller.py::test_create_alpaca_client_returns_async_client`

**httpx vs requests migration note:** Full migration recommended for new Alpaca HTTP code.
The `aiohttp.ClientSession` in `brokers/alpaca.py` should be migrated to a persistent
`httpx.AsyncClient` in a follow-up (the per-request session pattern is functional but
sub-optimal — each order call pays TLS handshake cost).

**Tailscale / DNS note:** The Tailscale warnings (`DNS base config unsupported`) on Render
indicate Tailscale cannot integrate with the host DNS stack. While not the SSL EOF root cause,
DNS instability can produce `ConnectionError` spikes. If Tailscale is only needed for LM Studio
access, confirm `LM_STUDIO_PROXY_URL` is set correctly and that Tailscale is not intercepting
non-LM-Studio traffic.
