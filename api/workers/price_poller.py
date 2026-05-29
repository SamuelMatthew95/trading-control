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
  - Graceful degradation: stale cached prices remain in Redis (TTL 30 s)
    during outages; dashboard shows last-known prices rather than blanks.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
import uuid
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

SYMBOLS = {
    FieldName.CRYPTO: ["BTC/USD", "ETH/USD", "SOL/USD"],
    FieldName.STOCKS: ["AAPL", "TSLA", "SPY"],
}

ALL_SYMBOLS = SYMBOLS[FieldName.CRYPTO] + SYMBOLS[FieldName.STOCKS]

_POLL_INTERVAL = 5  # seconds between cycles


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


async def _fetch_crypto(client: httpx.AsyncClient, symbols: list[str]) -> dict[str, float]:
    """Fetch latest crypto quotes from Alpaca data API.

    Response keys "quotes", "bp", "ap" are Alpaca API contract strings —
    not internal FieldName payload keys.
    """
    resp = await client.get(
        "/v1beta3/crypto/us/latest/quotes",
        params={"symbols": ",".join(symbols)},
    )
    resp.raise_for_status()
    data = resp.json()
    prices: dict[str, float] = {}
    for symbol in symbols:
        quote = data.get("quotes", {}).get(symbol, {})
        bid = float(quote.get("bp", 0) or 0)
        ask = float(quote.get("ap", 0) or 0)
        price = bid if bid > 0 else ask
        if price > 0:
            prices[symbol] = price
    return prices


async def _fetch_stocks(client: httpx.AsyncClient, symbols: list[str]) -> dict[str, float]:
    """Fetch latest stock quotes from Alpaca data API.

    Response keys "quotes", "bp", "ap" are Alpaca API contract strings —
    not internal FieldName payload keys.
    """
    resp = await client.get(
        "/v2/stocks/quotes/latest",
        params={"symbols": ",".join(symbols)},
    )
    resp.raise_for_status()
    data = resp.json()
    prices: dict[str, float] = {}
    for symbol in symbols:
        quote = data.get("quotes", {}).get(symbol, {})
        bid = float(quote.get("bp", 0) or 0)
        ask = float(quote.get("ap", 0) or 0)
        price = bid if bid > 0 else ask
        if price > 0:
            prices[symbol] = price
    return prices


async def build_symbol_payload(redis_client, symbol: str, current_price: float) -> dict:
    """Compute change/pct from cached previous price, return full payload."""
    prev_raw = await redis_client.get(REDIS_KEY_PRICES.format(symbol=symbol))
    prev_data = json.loads(prev_raw) if prev_raw else None
    prev_price = float(prev_data[FieldName.PRICE]) if prev_data else None
    change = round(current_price - prev_price, 4) if prev_price else 0.0
    pct = round((change / prev_price) * 100, 4) if prev_price else 0.0
    return {
        FieldName.SYMBOL: symbol,
        FieldName.PRICE: current_price,
        "change": change,
        FieldName.PCT: pct,
        FieldName.TS: int(time.time()),
        FieldName.TRACE_ID: str(uuid.uuid4()),
    }


async def publish_to_redis(redis_client, payloads: list[dict]) -> None:
    """Write all symbol payloads to Redis cache, stream, and pub/sub."""
    pipe = redis_client.pipeline()
    for p in payloads:
        symbol = p[FieldName.SYMBOL]
        cache_val = json.dumps(
            {
                FieldName.PRICE: p[FieldName.PRICE],
                "change": p[FieldName.CHANGE],
                FieldName.PCT: p[FieldName.PCT],
                FieldName.TS: p[FieldName.TS],
            }
        )
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


async def poll_prices() -> None:
    """Main price polling loop — runs for the lifetime of the app."""
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        log_structured(
            "error",
            "alpaca_credentials_missing",
            message="ALPACA_API_KEY and ALPACA_SECRET_KEY are required",
        )
        return

    redis_client = await get_redis()
    client = _create_alpaca_client()
    consecutive_failures = 0
    circuit_open_until = 0.0

    log_structured(
        "info", "price_poller_started", symbols=len(ALL_SYMBOLS), interval_secs=_POLL_INTERVAL
    )

    try:
        while True:
            # --- Circuit breaker check ---
            now = time.monotonic()
            if now < circuit_open_until:
                remaining = round(circuit_open_until - now, 1)
                log_structured(
                    "warning",
                    "alpaca_circuit_open_skipping_poll",
                    remaining_seconds=remaining,
                )
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            cycle_start = time.perf_counter()
            try:
                # Fetch both asset classes concurrently — native async, no thread executor
                crypto_prices, stock_prices = await asyncio.gather(
                    _fetch_crypto(client, SYMBOLS[FieldName.CRYPTO]),
                    _fetch_stocks(client, SYMBOLS[FieldName.STOCKS]),
                    return_exceptions=True,
                )

                # --- Error triage: detect SSL EOF specifically ---
                ssl_eof_seen = False
                for label, result in (("crypto", crypto_prices), ("stocks", stock_prices)):
                    if not isinstance(result, Exception):
                        continue
                    if _is_ssl_eof(result):
                        ssl_eof_seen = True
                        log_structured(
                            "error",
                            "alpaca_ssl_eof_detected",
                            asset_class=label,
                            consecutive_failures=consecutive_failures + 1,
                        )
                    elif isinstance(result, httpx.TimeoutException):
                        log_structured("warning", f"alpaca_{label}_timeout")
                    else:
                        log_structured("error", f"alpaca_{label}_fetch_failed", exc_info=True)

                if ssl_eof_seen:
                    consecutive_failures += 1
                    # Close and recreate client to evict poisoned connections from the pool.
                    # This is the primary fix: a new client starts with a fresh connection pool,
                    # eliminating any stale TCP sockets that caused the EOF.
                    await client.aclose()
                    client = _create_alpaca_client()
                    log_structured(
                        "warning",
                        "alpaca_ssl_eof_client_recreated",
                        consecutive_failures=consecutive_failures,
                    )
                    if consecutive_failures >= ALPACA_CIRCUIT_BREAKER_THRESHOLD:
                        circuit_open_until = time.monotonic() + ALPACA_CIRCUIT_BREAKER_RESET_SECONDS
                        log_structured(
                            "error",
                            "alpaca_circuit_breaker_open",
                            consecutive_failures=consecutive_failures,
                            cooldown_seconds=ALPACA_CIRCUIT_BREAKER_RESET_SECONDS,
                        )
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                # Non-SSL errors still count toward circuit breaker
                if isinstance(crypto_prices, Exception) and isinstance(stock_prices, Exception):
                    consecutive_failures += 1
                    if consecutive_failures >= ALPACA_CIRCUIT_BREAKER_THRESHOLD:
                        circuit_open_until = time.monotonic() + ALPACA_CIRCUIT_BREAKER_RESET_SECONDS
                        log_structured(
                            "error",
                            "alpaca_circuit_breaker_open",
                            consecutive_failures=consecutive_failures,
                            cooldown_seconds=ALPACA_CIRCUIT_BREAKER_RESET_SECONDS,
                        )

                # Build price map from whichever fetches succeeded (partial results OK)
                all_prices: dict[str, float] = {}
                if not isinstance(crypto_prices, Exception):
                    all_prices.update(crypto_prices)
                if not isinstance(stock_prices, Exception):
                    all_prices.update(stock_prices)

                if all_prices:
                    consecutive_failures = 0  # any success resets the counter

                    payloads = await asyncio.gather(
                        *[
                            build_symbol_payload(redis_client, sym, price)
                            for sym, price in all_prices.items()
                        ]
                    )

                    await asyncio.gather(
                        publish_to_redis(redis_client, payloads),
                        flush_to_db(payloads),
                    )

                    await redis_client.set(
                        REDIS_KEY_WORKER_HEARTBEAT,
                        datetime.now(timezone.utc).isoformat(),
                        ex=WORKER_HEARTBEAT_TTL_SECONDS,
                    )

                    elapsed_ms = round((time.perf_counter() - cycle_start) * 1000)
                    log_structured(
                        "info",
                        "price_poller_cycle_complete",
                        symbols=len(all_prices),
                        total=len(ALL_SYMBOLS),
                        duration_ms=elapsed_ms,
                    )
                else:
                    log_structured("warning", "price_poller_no_prices_fetched")

            except Exception:
                log_structured("error", "price_poller_cycle_error", exc_info=True)

            await asyncio.sleep(_POLL_INTERVAL)

    finally:
        await client.aclose()
