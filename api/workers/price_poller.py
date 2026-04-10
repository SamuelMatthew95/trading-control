"""Background worker that continuously polls market prices and caches them.

Writes every cycle:
  a) Redis cache  (prices:{symbol})        — for REST endpoint
  b) Redis stream (market_events)          — wakes SIGNAL_AGENT
  c) Redis pub/sub (price_updates)         — for SSE browser streaming
  d) Postgres prices_snapshot              — persistent fallback (batched per cycle)
  e) Postgres system_metrics               — observability (batched per cycle)

Performance notes:
  - Alpaca SDK calls are synchronous; run_in_executor keeps the event loop free.
  - DB writes are batched: one transaction for all symbols per cycle instead of
    one transaction per symbol.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from functools import partial

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest, StockLatestQuoteRequest
from sqlalchemy import text

from api.config import settings
from api.constants import (
    REDIS_KEY_PRICES,
    REDIS_KEY_WORKER_HEARTBEAT,
    REDIS_PRICES_TTL_SECONDS,
    WORKER_HEARTBEAT_TTL_SECONDS,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import is_db_available, get_runtime_store

SYMBOLS = {
    "crypto": ["BTC/USD", "ETH/USD", "SOL/USD"],
    "stocks": ["AAPL", "TSLA", "SPY"],
}

ALL_SYMBOLS = SYMBOLS["crypto"] + SYMBOLS["stocks"]

_POLL_INTERVAL = 5  # seconds between cycles


def _sync_fetch_crypto(client: CryptoHistoricalDataClient, symbols: list[str]) -> dict[str, float]:
    """Synchronous Alpaca crypto fetch — runs in a thread via run_in_executor."""
    request = CryptoLatestQuoteRequest(symbol_or_symbols=symbols)
    quotes = client.get_crypto_latest_quote(request)
    prices: dict[str, float] = {}
    for symbol in symbols:
        if symbol in quotes:
            quote = quotes[symbol]
            price = float(quote.bid_price if quote.bid_price else quote.ask_price)
            if price > 0:
                prices[symbol] = price
    return prices


def _sync_fetch_stocks(client: StockHistoricalDataClient, symbols: list[str]) -> dict[str, float]:
    """Synchronous Alpaca stock fetch — runs in a thread via run_in_executor."""
    request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
    quotes = client.get_stock_latest_quote(request)
    prices: dict[str, float] = {}
    for symbol in symbols:
        if symbol in quotes:
            quote = quotes[symbol]
            price = float(quote.bid_price if quote.bid_price else quote.ask_price)
            if price > 0:
                prices[symbol] = price
    return prices


async def fetch_crypto_prices(
    client: CryptoHistoricalDataClient, symbols: list[str]
) -> dict[str, float]:
    """Fetch latest crypto prices without blocking the event loop."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, partial(_sync_fetch_crypto, client, symbols)),
            timeout=8,
        )
    except TimeoutError:
        log_structured("warning", "alpaca_crypto_timeout", symbols=symbols)
        return {}
    except Exception:
        log_structured("error", "crypto_price_fetch_failed", exc_info=True)
        return {}


async def fetch_stock_prices(
    client: StockHistoricalDataClient, symbols: list[str]
) -> dict[str, float]:
    """Fetch latest stock prices without blocking the event loop."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, partial(_sync_fetch_stocks, client, symbols)),
            timeout=8,
        )
    except TimeoutError:
        log_structured("warning", "alpaca_stocks_timeout", symbols=symbols)
        return {}
    except Exception:
        log_structured("error", "stock_price_fetch_failed", exc_info=True)
        return {}


async def build_symbol_payload(redis_client, symbol: str, current_price: float) -> dict:
    """Compute change/pct from cached previous price, return full payload."""
    prev_raw = await redis_client.get(REDIS_KEY_PRICES.format(symbol=symbol))
    prev_data = json.loads(prev_raw) if prev_raw else None
    prev_price = float(prev_data["price"]) if prev_data else None
    change = round(current_price - prev_price, 4) if prev_price else 0.0
    pct = round((change / prev_price) * 100, 4) if prev_price else 0.0
    return {
        "symbol": symbol,
        "price": current_price,
        "change": change,
        "pct": pct,
        "ts": int(time.time()),
        "trace_id": str(uuid.uuid4()),
    }


async def publish_to_redis(redis_client, payloads: list[dict]) -> None:
    """Write all symbol payloads to Redis cache, stream, and pub/sub."""
    pipe = redis_client.pipeline()
    for p in payloads:
        symbol = p["symbol"]
        cache_val = json.dumps(
            {"price": p["price"], "change": p["change"], "pct": p["pct"], "ts": p["ts"]}
        )
        pipe.set(REDIS_KEY_PRICES.format(symbol=symbol), cache_val, ex=REDIS_PRICES_TTL_SECONDS)
        pipe.xadd(
            "market_events",
            {
                "msg_id": str(uuid.uuid4()),
                "schema_version": "v3",
                "payload": json.dumps(
                    {k: p[k] for k in ("symbol", "price", "change", "pct", "ts", "trace_id")}
                ),
            },
        )
        pipe.publish(
            "price_updates",
            json.dumps(
                {
                    "symbol": symbol,
                    "price": p["price"],
                    "change": p["change"],
                    "pct": p["pct"],
                    "ts": p["ts"],
                }
            ),
        )
    pipe.xtrim("market_events", maxlen=1000, approximate=True)
    await pipe.execute()


async def flush_to_db(payloads: list[dict]) -> None:
    """Batch-write all symbol prices to Postgres in a single transaction."""
    # Skip database entirely if in memory mode (deliberate design choice)
    if not is_db_available():
        log_structured(
            "info",
            "price_poller_memory_mode_active",
            symbols=[p["symbol"] for p in payloads],
            message="Price poller running in deliberate in-memory mode",
        )
        # Store in memory store (primary storage in memory mode)
        store = get_runtime_store()
        for p in payloads:
            store.add_event({
                "type": "price_update",
                "symbol": p["symbol"],
                "price": p["price"],
                "change": p["change"],
                "pct": p["pct"],
                "ts": p["ts"],
            })
        return
    
    max_retries = 3
    retry_delay = 1.0
    
    for attempt in range(max_retries):
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
                                "symbol": p["symbol"],
                                "price": p["price"],
                                "change_amt": p["change"],
                                "change_pct": p["pct"],
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
                                "price": p["price"],
                                "tags": json.dumps({"symbol": p["symbol"], "ts": p["ts"]}),
                            },
                        )
            # If we get here, success - break retry loop
            return
            
        except Exception as e:
            if attempt == max_retries - 1:
                # Final attempt failed, log error and use memory store
                log_structured(
                    "error",
                    "price_poller_db_flush_failed",
                    symbols=[p["symbol"] for p in payloads],
                    attempt=attempt + 1,
                    exc_info=True,
                )
                # Store in memory store (primary storage when DB fails)
                store = get_runtime_store()
                for p in payloads:
                    store.add_event({
                        "type": "price_update",
                        "symbol": p["symbol"],
                        "price": p["price"],
                        "change": p["change"],
                        "pct": p["pct"],
                        "ts": p["ts"],
                    })
            else:
                # Retry with exponential backoff
                log_structured(
                    "warning",
                    "price_poller_db_flush_retry",
                    symbols=[p["symbol"] for p in payloads],
                    attempt=attempt + 1,
                    retry_delay=retry_delay,
                )
                await asyncio.sleep(retry_delay)
                retry_delay *= 2


async def poll_prices() -> None:
    """Main price polling loop — runs for the lifetime of the app."""
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        log_structured(
            "error",
            "alpaca_credentials_missing",
            message="ALPACA_API_KEY and ALPACA_SECRET_KEY are required",
        )
        return

    crypto_client = CryptoHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY, secret_key=settings.ALPACA_SECRET_KEY
    )
    stock_client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY, secret_key=settings.ALPACA_SECRET_KEY
    )

    redis_client = await get_redis()

    log_structured(
        "info", "price_poller_started", symbols=len(ALL_SYMBOLS), interval_secs=_POLL_INTERVAL
    )

    while True:
        cycle_start = time.perf_counter()
        try:
            # Fetch both asset classes concurrently — each runs in a thread, not the event loop
            crypto_prices, stock_prices = await asyncio.gather(
                fetch_crypto_prices(crypto_client, SYMBOLS["crypto"]),
                fetch_stock_prices(stock_client, SYMBOLS["stocks"]),
                return_exceptions=True,
            )

            if isinstance(crypto_prices, Exception):
                log_structured("error", "crypto_gather_exception", exc_info=True)
                crypto_prices = {}
            if isinstance(stock_prices, Exception):
                log_structured("error", "stock_gather_exception", exc_info=True)
                stock_prices = {}

            all_prices: dict[str, float] = {**crypto_prices, **stock_prices}

            if all_prices:
                # Build payloads (reads prev prices from Redis — fast)
                payloads = await asyncio.gather(
                    *[
                        build_symbol_payload(redis_client, sym, price)
                        for sym, price in all_prices.items()
                    ]
                )

                # Write Redis (pipeline — single round-trip) and DB (batched transaction) concurrently
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


if __name__ == "__main__":
    asyncio.run(poll_prices())
