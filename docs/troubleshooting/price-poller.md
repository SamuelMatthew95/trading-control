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

## Redis connection pool exhaustion — `ConnectionError: Too many connections`

**Symptom:** `ConnectionError: Too many connections` raised from
`build_symbol_payload()` → `redis.asyncio.connection.ConnectionPool.get_connection()`.
Polling cycles fail intermittently under load; the failure rate scales with the
symbol count.

**Root cause:** Each poll cycle built payloads with one Redis `GET` per symbol
(an N+1). At 6 symbols every 5 s that is a steady stream of concurrent
`get_connection()` checkouts; bursts (or a slow Redis) held enough connections
simultaneously to exhaust the pool (`REDIS_MAX_CONNECTIONS`, default 20). The
shared client/pool itself was fine — the problem was the per-symbol fan-out of
reads, amplified by an over-aggressive 5 s cadence.

**Fix:** `api/workers/price_poller.py`
- `build_symbol_payloads()` builds every symbol's payload in one pass.
  `build_symbol_payload()` (single-symbol) is retained for callers/tests and
  shares a pure `_compute_symbol_payload()` helper.
- Cadence is now per asset class and far less aggressive
  (`CRYPTO_POLL_INTERVAL_SECONDS=30`, `STOCK_POLL_INTERVAL_SECONDS=60`), cutting
  baseline Redis traffic ~6–12×.

> **Superseded (see "Every decision `hold`" below):** the previous-price read no
> longer touches Redis at all — `build_symbol_payloads()` now takes an explicit
> in-memory `prev_prices` map (`_PollerState.last_prices`), so a poll cycle does
> **zero** Redis reads for the delta (strictly better than the MGET this entry
> introduced, and it fixes the pct=0 bug that MGET-from-cache caused).

**Regression tests:**
- `tests/core/test_price_poller.py::test_build_symbol_payloads_computes_change_from_prev`
- `tests/core/test_price_poller.py::test_build_symbol_payloads_anchor_is_prev_map_not_redis_cache`

## Every decision is `hold` — no buys/sells ever, learning loop starved (pct pinned to 0)

**Symptom:** The dashboard agent matrix shows the whole downstream pipeline stuck
at 0 events — `GRADE_AGENT`, `IC_UPDATER`, `REFLECTION_AGENT`, `STRATEGY_PROPOSER`,
`CHALLENGER_AGENT`, `PROPOSAL_APPLIER` never increment. Every decision in
`decisions:recent` is `action="hold"` with `confidence=0.30` ("low momentum"),
across *all* symbols (crypto **and** stocks). `executions`, `trade_performance`,
`trade_completed`, `agent_grades`, `reflection_outputs` streams are all empty.
No buy or sell is ever placed even though prices clearly move.

**Root cause:** `pct` (the bar-to-bar % move that *is* the buy/sell/hold decision
in `classify_signal`) was computed against a previous price read back from the
Redis price cache `prices:{symbol}`, written with `ex=REDIS_PRICES_TTL_SECONDS`
(30 s). But the poll interval is **≥** that TTL (crypto 30 s, stocks 60 s) and the
inter-cycle `sleep` happens **after** the write — so the previous entry had always
expired by the next read. `prev_raw` was therefore always `None` → `change=0.0`,
`pct=0.0` every cycle. With `pct=0`, `classify_signal` returns `direction=NEUTRAL`,
`strength=LOW` → `action="hold"` — *unconditionally*, regardless of real price
movement. The momentum (buy/sell) branch was structurally unreachable, so nothing
ever flowed past `decisions` into execution and the entire learning loop starved.
(Stocks made it provable: 60 s interval vs 30 s TTL means the stock prev is *always*
expired, and indeed every SPY/TSLA/AAPL decision was `hold`/0.30.)

**Fix:** `api/workers/price_poller.py` — the poll loop now derives change/pct from
its **own in-memory previous-price anchor** (`_PollerState.last_prices`), advanced
once per cycle, instead of the short-TTL Redis cache. `build_symbol_payloads()` is
now a pure function taking an explicit `prev_prices` map. The consumer-facing cache
TTL is unchanged (still the 30 s freshness contract); only the *delta anchor* was
decoupled from it, so the cache can never again pin pct to 0. First cycle after a
restart still reports pct=0 for one tick (no anchor yet), then real deltas flow.

**Regression test:**
`tests/core/test_price_poller.py::test_run_poll_cycle_pct_survives_expired_cache`

## Stock workers active 24/7 — overnight polling, broadcasts, and SIP 403s

**Symptom:** Stock symbols (AAPL/TSLA/SPY) were polled, broadcast, signalled, and
bootstrapped around the clock — including overnight, weekends, and exchange
holidays when equity prices cannot change. `signal_generator_price_history_bootstrap_failed`
with `403 Forbidden: subscription does not permit querying recent SIP data` recurred
overnight. Wasted Alpaca quota, Redis writes, CPU, and log volume.

**Root cause:** The only market-hours gate lived in `ExecutionEngine._is_market_open()`,
short-circuited to `True` in paper mode, and used holiday-blind ET time math. Nothing
gated the upstream pipeline (poller, signal generation, historical bootstrap), so stock
work ran continuously regardless of session.

**Fix:** New centralized `api/services/market_status.py` (`MarketStatusService`,
holiday- and early-close-aware NYSE/NASDAQ clock, pure-Python, injectable `now`).
Consumed by every stock subsystem:
- `price_poller._due_asset_classes()` skips stocks entirely when `is_open()` is False
  — zero stock Alpaca calls / Redis writes / `market_events` (hence zero stock
  broadcasts and downstream signals) outside the session.
- `signal_generator._bootstrap_price_history()` skips the historical bars fetch for
  stocks when closed (stops the overnight SIP 403s).
- `execution_engine._is_market_open()` delegates to the same service.

**Regression tests:**
- `tests/core/test_market_status.py` (holidays, sessions, early closes, crypto 24/7)
- `tests/core/test_price_poller.py::test_run_poll_cycle_skips_stocks_when_market_closed`
- `tests/core/test_price_poller.py::test_due_classes_crypto_only_when_market_closed`

## Signal flood — a downstream signal per tick, around the clock

**Symptom:** Every market tick produced a signal plus `events`/`grades`/`agent_runs`/`agent_logs`
writes and woke the reasoning→LLM cascade — ~72 signals/min, 24/7, mostly sub-threshold noise.

**Root cause:** `SignalGenerator.process()` published on every tick. The
`SIGNAL_EVERY_N_TICKS` config existed but was wired to nothing.

**Fix:** `api/services/signal_generator._should_publish()` throttles the noise floor:
tradeable moves (`strength != LOW`) always publish; sub-threshold ticks publish only
once every `SIGNAL_EVERY_N_TICKS` ticks (the first tick of a symbol always publishes).
Indicator history stays warm every tick and a throttled tick still heartbeats, so the
agent never ages to STALE.

**Regression test:** `tests/agents/test_signal_generator_throttle.py::test_low_ticks_publish_first_then_every_n`
