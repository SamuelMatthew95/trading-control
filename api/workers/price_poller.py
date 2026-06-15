"""Background worker that continuously polls market prices and caches them.

Writes every cycle:
  a) Redis cache  (prices:{symbol})        — for REST endpoint
  b) Redis stream (market_events)          — wakes SIGNAL_AGENT
  c) Redis pub/sub (price_updates)         — for SSE browser streaming
  d) Postgres prices_snapshot              — persistent fallback (batched per cycle)
  e) Postgres system_metrics               — observability (batched per cycle)

Transport / reliability:
  - httpx.AsyncClient replaces alpaca-py SDK for REST price fetching.
    Native async eliminates run_in_executor threadpool starvation risk.
  - Explicit connect (5 s) + read (10 s) timeouts on every request.
  - keepalive_expiry=20 s drops idle connections before Render NAT (~60 s)
    silently kills them — this is the direct fix for SSLZeroReturnError(6)
    EOF caused by urllib3 reusing a dead keepalive socket.
  - _is_ssl_eof(): traverses the exception chain to detect ssl.SSLError
    (superclass of SSLZeroReturnError) through httpx's wrapping layers.
  - On SSL EOF: client is closed and recreated to flush poisoned connections.
  - Circuit breaker: ALPACA_CIRCUIT_BREAKER_THRESHOLD consecutive failures
    → ALPACA_CIRCUIT_BREAKER_RESET_SECONDS cooldown before resuming.
  - Graceful degradation: cached prices remain in Redis for
    REDIS_PRICES_TTL_SECONDS (150 s) during a brief outage, so the dashboard
    shows last-known prices rather than blanks; a longer outage lets them
    expire, and readers additionally drop any price too old to be a live quote.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from api.config import settings
from api.constants import (
    ALPACA_CIRCUIT_BREAKER_RESET_SECONDS,
    ALPACA_CIRCUIT_BREAKER_THRESHOLD,
    ALPACA_DATA_BASE_URL,
    ALPACA_HTTP_CONNECT_TIMEOUT_SECONDS,
    ALPACA_HTTP_KEEPALIVE_EXPIRY_SECONDS,
    ALPACA_HTTP_READ_TIMEOUT_SECONDS,
    REDIS_KEY_PRICES,
    REDIS_KEY_WORKER_HEARTBEAT,
    REDIS_PRICES_TTL_SECONDS,
    REDIS_PUBSUB_PRICE_UPDATES,
    STREAM_MARKET_EVENTS,
    WORKER_HEARTBEAT_TTL_SECONDS,
    FieldName,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available
from api.services.market_status import get_market_status

SYMBOLS = {
    FieldName.CRYPTO: ["BTC/USD", "ETH/USD", "SOL/USD"],
    FieldName.STOCKS: ["AAPL", "TSLA", "SPY"],
}

ALL_SYMBOLS = SYMBOLS[FieldName.CRYPTO] + SYMBOLS[FieldName.STOCKS]


def _create_alpaca_client() -> httpx.AsyncClient:
    """Return a hardened httpx.AsyncClient for the Alpaca data REST API.

    keepalive_expiry is set below Render's NAT idle timeout so connections are
    preemptively closed rather than silently dropped by the NAT table.  Without
    this, urllib3 (used by the alpaca-py SDK) reuses a dead socket and the TLS
    layer raises SSLZeroReturnError(6) 'TLS/SSL connection has been closed (EOF)'.
    """
    limits = httpx.Limits(
        max_keepalive_connections=2,  # one per asset class (crypto + stocks)
        max_connections=4,
        keepalive_expiry=ALPACA_HTTP_KEEPALIVE_EXPIRY_SECONDS,
    )
    timeout = httpx.Timeout(
        connect=float(ALPACA_HTTP_CONNECT_TIMEOUT_SECONDS),
        read=float(ALPACA_HTTP_READ_TIMEOUT_SECONDS),
        write=5.0,
        pool=5.0,
    )
    return httpx.AsyncClient(
        base_url=ALPACA_DATA_BASE_URL,
        headers={
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
        },
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
    )


def _is_ssl_eof(exc: BaseException) -> bool:
    """Return True if exc or any chained cause is an ssl.SSLError.

    ssl.SSLZeroReturnError is a subclass of ssl.SSLError, so this catches the
    exact EOF pattern.  httpx wraps the raw ssl error in ConnectError or
    RemoteProtocolError; we walk the full __cause__/__context__ chain.
    """
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _parse_quotes(data: dict, symbols: list[str]) -> dict[str, dict[str, float]]:
    """Parse an Alpaca latest-quotes response into per-symbol L1 quotes.

    Returns ``{symbol: {price, bid, ask}}`` — the real best bid/ask are kept
    (previously they were parsed and then discarded) so the dashboard can show
    a true Level-1 quote. Response keys "quotes", "bp", "ap" are Alpaca API
    contract strings — not internal FieldName payload keys.
    """
    quotes: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        quote = data.get("quotes", {}).get(symbol, {})
        bid = float(quote.get("bp", 0) or 0)
        ask = float(quote.get("ap", 0) or 0)
        price = bid if bid > 0 else ask
        if price > 0:
            quotes[symbol] = {FieldName.PRICE: price, FieldName.BID: bid, FieldName.ASK: ask}
    return quotes


async def _fetch_crypto(
    client: httpx.AsyncClient, symbols: list[str]
) -> dict[str, dict[str, float]]:
    """Fetch latest crypto L1 quotes ({price, bid, ask} per symbol) from Alpaca."""
    resp = await client.get(
        "/v1beta3/crypto/us/latest/quotes",
        params={"symbols": ",".join(symbols)},
    )
    resp.raise_for_status()
    return _parse_quotes(resp.json(), symbols)


async def _fetch_stocks(
    client: httpx.AsyncClient, symbols: list[str]
) -> dict[str, dict[str, float]]:
    """Fetch latest stock L1 quotes ({price, bid, ask} per symbol) from Alpaca."""
    resp = await client.get(
        "/v2/stocks/quotes/latest",
        params={"symbols": ",".join(symbols)},
    )
    resp.raise_for_status()
    return _parse_quotes(resp.json(), symbols)


def _compute_symbol_payload(symbol: str, current_price: float, prev_data: dict | None) -> dict:
    """Pure: build a price payload, deriving change/pct from a prior snapshot."""
    prev_price = float(prev_data[FieldName.PRICE]) if prev_data else None
    change = round(current_price - prev_price, 4) if prev_price else 0.0
    pct = round((change / prev_price) * 100, 4) if prev_price else 0.0
    return {
        FieldName.SYMBOL: symbol,
        FieldName.PRICE: current_price,
        FieldName.CHANGE: change,
        FieldName.PCT: pct,
        FieldName.TS: int(time.time()),
        FieldName.TRACE_ID: str(uuid.uuid4()),
    }


async def build_symbol_payload(redis_client, symbol: str, current_price: float) -> dict:
    """Single-symbol payload for ad-hoc/direct lookups (one GET against the cache).

    Retained for direct callers/tests only. The poll loop does NOT use this — it
    computes change/pct from its own in-memory previous-price anchor
    (``_PollerState.last_prices``) via :func:`build_symbol_payloads`, because the
    Redis price cache TTL is shorter than the poll interval and so always misses.
    """
    prev_raw = await redis_client.get(REDIS_KEY_PRICES.format(symbol=symbol))
    prev_data = json.loads(prev_raw) if prev_raw else None
    return _compute_symbol_payload(symbol, current_price, prev_data)


def build_symbol_payloads(
    prices: dict[str, float],
    prev_prices: dict[str, float],
    quotes: dict[str, dict[str, float]] | None = None,
) -> list[dict]:
    """Build a payload per symbol for a poll cycle, deriving change/pct from ``prev_prices``.

    ``prev_prices`` is the poll loop's own in-memory previous-price map
    (``_PollerState.last_prices``) — NOT the Redis price cache. The delta is
    taken from this anchor so a poll cycle reads Redis zero times for it (pure,
    no MGET) and change/pct never depends on the cache. Historically the prev was
    read from the cache, and when the cache TTL was shorter than the poll
    interval the entry had expired by the next read — pinning pct to 0.0 and
    starving the momentum signal (every move looked flat → NEUTRAL/LOW → hold →
    no buys). An in-memory anchor removes that dependency entirely.

    ``quotes`` (optional) carries the real L1 best bid/ask per symbol; a payload
    gains bid/ask only when the quote is two-sided (both > 0) — a one-sided or
    missing quote must never render a fake $0.00 side on the dashboard.
    """
    if not prices:
        return []
    payloads: list[dict] = []
    for symbol, current_price in prices.items():
        prev = prev_prices.get(symbol)
        prev_data = {FieldName.PRICE: prev} if prev else None
        payload = _compute_symbol_payload(symbol, current_price, prev_data)
        quote = (quotes or {}).get(symbol)
        if quote:
            bid = float(quote.get(FieldName.BID, 0) or 0)
            ask = float(quote.get(FieldName.ASK, 0) or 0)
            if bid > 0 and ask > 0:
                payload[FieldName.BID] = bid
                payload[FieldName.ASK] = ask
        payloads.append(payload)
    return payloads


async def publish_to_redis(redis_client, payloads: list[dict]) -> None:
    """Write all symbol payloads to Redis cache, stream, and pub/sub."""
    pipe = redis_client.pipeline()
    for p in payloads:
        symbol = p[FieldName.SYMBOL]
        cache_payload = {
            FieldName.PRICE: p[FieldName.PRICE],
            "change": p[FieldName.CHANGE],
            FieldName.PCT: p[FieldName.PCT],
            FieldName.TS: p[FieldName.TS],
        }
        # Real L1 best bid/ask ride along in the REST cache only — the agent
        # stream/pub-sub contracts below are deliberately unchanged.
        if FieldName.BID in p and FieldName.ASK in p:
            cache_payload[FieldName.BID] = p[FieldName.BID]
            cache_payload[FieldName.ASK] = p[FieldName.ASK]
        cache_val = json.dumps(cache_payload)
        pipe.set(REDIS_KEY_PRICES.format(symbol=symbol), cache_val, ex=REDIS_PRICES_TTL_SECONDS)
        pipe.xadd(
            STREAM_MARKET_EVENTS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SCHEMA_VERSION: "v3",
                FieldName.PAYLOAD: json.dumps(
                    {
                        k: p[k]
                        for k in (
                            FieldName.SYMBOL,
                            FieldName.PRICE,
                            "change",
                            FieldName.PCT,
                            FieldName.TS,
                            FieldName.TRACE_ID,
                        )
                    }
                ),
            },
        )
        pipe.publish(
            REDIS_PUBSUB_PRICE_UPDATES,
            json.dumps(
                {
                    FieldName.SYMBOL: symbol,
                    FieldName.PRICE: p[FieldName.PRICE],
                    "change": p[FieldName.CHANGE],
                    FieldName.PCT: p[FieldName.PCT],
                    FieldName.TS: p[FieldName.TS],
                }
            ),
        )
    pipe.xtrim(STREAM_MARKET_EVENTS, maxlen=1000, approximate=True)
    await pipe.execute()


async def flush_to_db(payloads: list[dict]) -> None:
    """Persist symbol prices: memory store always; Postgres when DB is available."""
    symbols = [p[FieldName.SYMBOL] for p in payloads]

    # Always write to memory store so dashboard has current prices
    store = get_runtime_store()
    for p in payloads:
        store.add_event(
            {
                FieldName.TYPE: "price_update",
                FieldName.SYMBOL: p[FieldName.SYMBOL],
                FieldName.PRICE: p[FieldName.PRICE],
                "change": p[FieldName.CHANGE],
                FieldName.PCT: p[FieldName.PCT],
                FieldName.TS: p[FieldName.TS],
            }
        )

    if not is_db_available():
        log_structured("debug", "price_poller_memory_mode", symbols=symbols)
        return

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                for p in payloads:
                    await session.execute(
                        text("""
                            INSERT INTO prices_snapshot
                                (symbol, price, change_amt, change_pct, updated_at)
                            VALUES (:symbol, :price, :change_amt, :change_pct, NOW())
                            ON CONFLICT (symbol) DO UPDATE SET
                                price       = EXCLUDED.price,
                                change_amt  = EXCLUDED.change_amt,
                                change_pct  = EXCLUDED.change_pct,
                                updated_at  = NOW()
                        """),
                        {
                            "symbol": p[FieldName.SYMBOL],
                            "price": p[FieldName.PRICE],
                            FieldName.CHANGE_AMT: p[FieldName.CHANGE],
                            FieldName.CHANGE_PCT: p[FieldName.PCT],
                        },
                    )
                    await session.execute(
                        text("""
                            INSERT INTO system_metrics
                                (metric_name, metric_value, metric_unit, tags,
                                 schema_version, source, timestamp)
                            VALUES ('price_fetch', :price, 'usd',
                                    :tags, 'v3', 'price_poller', NOW())
                        """),
                        {
                            "price": p[FieldName.PRICE],
                            FieldName.TAGS: json.dumps(
                                {
                                    FieldName.SYMBOL: p[FieldName.SYMBOL],
                                    FieldName.TS: p[FieldName.TS],
                                }
                            ),
                        },
                    )
    except Exception:
        log_structured("error", "price_poller_db_flush_failed", symbols=symbols, exc_info=True)


def _due_asset_classes(
    now: float,
    last_fetch: dict[str, float],
    crypto_interval: float,
    stock_interval: float,
    stocks_open: bool,
) -> list[str]:
    """Asset classes due to fetch this cycle.

    Crypto polls on its own interval 24/7. Stocks poll on their interval ONLY
    while the equity session is open — when closed they are never due, so the
    poller issues zero stock Alpaca/Redis traffic overnight, on weekends, and on
    exchange holidays.
    """
    due: list[str] = []
    if now - last_fetch[FieldName.CRYPTO] >= crypto_interval:
        due.append(FieldName.CRYPTO)
    if stocks_open and now - last_fetch[FieldName.STOCKS] >= stock_interval:
        due.append(FieldName.STOCKS)
    return due


def _open_circuit(consecutive_failures: int) -> float:
    """Log + return the monotonic deadline until which polling is suspended."""
    log_structured(
        "error",
        "alpaca_circuit_breaker_open",
        consecutive_failures=consecutive_failures,
        cooldown_seconds=ALPACA_CIRCUIT_BREAKER_RESET_SECONDS,
    )
    return time.monotonic() + ALPACA_CIRCUIT_BREAKER_RESET_SECONDS


@dataclass
class _PollerState:
    """Mutable state carried across poll cycles (client + circuit breaker).

    ``last_prices`` is the poll loop's authoritative previous-price map, used as
    the delta anchor for change/pct. It deliberately does NOT come from the Redis
    price cache: an in-memory anchor keeps each cycle's delta Redis-free and
    independent of the cache (TTL REDIS_PRICES_TTL_SECONDS = 150s, refreshed on
    every write). A cache-derived prev was a bug back when the TTL was shorter
    than the poll interval (crypto 30s, stocks 60s) — the prev expired before the
    next read, pinning pct to 0.0, classifying every signal NEUTRAL/LOW, and
    making the momentum (buy/sell) path unreachable. This anchor lives for the
    whole process.
    """

    client: httpx.AsyncClient
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    last_fetch: dict[str, float] = field(
        default_factory=lambda: {FieldName.CRYPTO: 0.0, FieldName.STOCKS: 0.0}
    )
    last_prices: dict[str, float] = field(default_factory=dict)


async def _run_poll_cycle(
    state: _PollerState,
    redis_client,
    market_status,
    crypto_interval: float,
    stock_interval: float,
) -> None:
    """Run exactly one poll cycle. Linear, no internal sleeps — the driver paces.

    Returns early (does no work) when the circuit breaker is open or nothing is
    due. All cross-cycle state lives on ``state`` so this is directly testable.
    """
    now = time.monotonic()

    if now < state.circuit_open_until:
        log_structured(
            "warning",
            "alpaca_circuit_open_skipping_poll",
            remaining_seconds=round(state.circuit_open_until - now, 1),
        )
        return

    # Stocks are skipped entirely when the equity session is closed: no Alpaca
    # call, no Redis write, no broadcast, no overnight SIP 403s.
    due = _due_asset_classes(
        now, state.last_fetch, crypto_interval, stock_interval, market_status.is_open()
    )
    if not due:
        return

    fetch_for = {
        FieldName.CRYPTO: lambda: _fetch_crypto(state.client, SYMBOLS[FieldName.CRYPTO]),
        FieldName.STOCKS: lambda: _fetch_stocks(state.client, SYMBOLS[FieldName.STOCKS]),
    }
    cycle_start = time.perf_counter()
    results = await asyncio.gather(*[fetch_for[label]() for label in due], return_exceptions=True)
    results_by_label = dict(zip(due, results, strict=False))

    # --- Error triage: detect SSL EOF specifically ---
    ssl_eof_seen = False
    for label, result in results_by_label.items():
        if not isinstance(result, Exception):
            continue
        if _is_ssl_eof(result):
            ssl_eof_seen = True
            log_structured(
                "error",
                "alpaca_ssl_eof_detected",
                asset_class=label,
                consecutive_failures=state.consecutive_failures + 1,
            )
        elif isinstance(result, httpx.TimeoutException):
            log_structured("warning", f"alpaca_{label}_timeout")
        else:
            log_structured(
                "error", f"alpaca_{label}_fetch_failed", error_type=type(result).__name__
            )

    if ssl_eof_seen:
        state.consecutive_failures += 1
        # Recreate the client to evict poisoned connections — a fresh client has
        # clean TCP sockets, fixing the SSLZeroReturnError(6) EOF. last_fetch is
        # intentionally NOT advanced so the class retries on the next cycle.
        await state.client.aclose()
        state.client = _create_alpaca_client()
        log_structured(
            "warning",
            "alpaca_ssl_eof_client_recreated",
            consecutive_failures=state.consecutive_failures,
        )
        if state.consecutive_failures >= ALPACA_CIRCUIT_BREAKER_THRESHOLD:
            state.circuit_open_until = _open_circuit(state.consecutive_failures)
        return

    # Attempt recorded — wait the full interval before retrying each class (no
    # tight retry loop on a persistent failure like a 403).
    for label in due:
        state.last_fetch[label] = now

    # Every attempted fetch failed → count toward the circuit breaker.
    if all(isinstance(r, Exception) for r in results):
        state.consecutive_failures += 1
        if state.consecutive_failures >= ALPACA_CIRCUIT_BREAKER_THRESHOLD:
            state.circuit_open_until = _open_circuit(state.consecutive_failures)

    # Build the quote map from whichever fetches succeeded (partial results OK).
    all_quotes: dict[str, dict[str, float]] = {}
    for result in results_by_label.values():
        if not isinstance(result, Exception):
            all_quotes.update(result)

    if not all_quotes:
        log_structured("warning", "price_poller_no_prices_fetched")
        return

    state.consecutive_failures = 0  # any success resets the counter

    # Scalar last-price view of the quotes — the momentum anchor and the
    # stream/pub-sub payloads stay exactly as before; bid/ask only enrich the
    # REST cache via build_symbol_payloads(quotes=...).
    all_prices: dict[str, float] = {sym: float(q[FieldName.PRICE]) for sym, q in all_quotes.items()}

    # Derive change/pct against the poller's OWN previous-price memory, not the
    # Redis price cache: the delta stays Redis-free (no MGET) and independent of
    # the cache TTL (REDIS_PRICES_TTL_SECONDS = 150s). A cache-derived prev was a
    # bug back when the TTL was shorter than the poll interval (crypto 30s /
    # stocks 60s) — it expired before the next read → pct pinned to 0.0 → every
    # signal NEUTRAL/LOW → hold → no buys. The in-memory anchor lives for the
    # whole process, so deltas are correct from the second cycle on.
    payloads = build_symbol_payloads(all_prices, state.last_prices, all_quotes)
    await asyncio.gather(
        publish_to_redis(redis_client, payloads),
        flush_to_db(payloads),
    )
    # Advance the anchor ONLY after the publish succeeds. publish_to_redis raises on
    # failure (flush_to_db swallows its own errors), so a failed market_events write
    # leaves last_prices untouched and the unpublished move is re-measured next cycle
    # instead of being silently erased. The next cycle's delta is then measured
    # against this cycle's (published) price.
    state.last_prices.update(all_prices)
    await redis_client.set(
        REDIS_KEY_WORKER_HEARTBEAT,
        datetime.now(timezone.utc).isoformat(),
        ex=WORKER_HEARTBEAT_TTL_SECONDS,
    )
    log_structured(
        "info",
        "price_poller_cycle_complete",
        symbols=len(all_prices),
        asset_classes=",".join(due),
        duration_ms=round((time.perf_counter() - cycle_start) * 1000),
    )


async def poll_prices() -> None:
    """Run the price poller for the lifetime of the app.

    Thin driver: tick at ``base_interval``, run one cycle, repeat — cancellation
    by the lifespan stops it. Cadence is per asset class
    (CRYPTO_POLL_INTERVAL_SECONDS / STOCK_POLL_INTERVAL_SECONDS); stock fetches
    are gated behind the MarketStatusService, so the equity path goes fully idle
    overnight/weekends/holidays while crypto keeps polling 24/7.
    """
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        log_structured(
            "error",
            "alpaca_credentials_missing",
            message="ALPACA_API_KEY and ALPACA_SECRET_KEY are required",
        )
        return

    redis_client = await get_redis()
    market_status = get_market_status()
    state = _PollerState(client=_create_alpaca_client())

    crypto_interval = float(settings.CRYPTO_POLL_INTERVAL_SECONDS)
    stock_interval = float(settings.STOCK_POLL_INTERVAL_SECONDS)
    base_interval = max(1.0, min(crypto_interval, stock_interval))

    log_structured(
        "info",
        "price_poller_started",
        crypto_interval_secs=crypto_interval,
        stock_interval_secs=stock_interval,
        base_interval_secs=base_interval,
    )

    try:
        while True:
            try:
                await _run_poll_cycle(
                    state, redis_client, market_status, crypto_interval, stock_interval
                )
            except Exception:
                log_structured("error", "price_poller_cycle_error", exc_info=True)
            await asyncio.sleep(base_interval)
    finally:
        await state.client.aclose()
