"""Background worker that continuously polls market prices and caches them.

Writes every cycle:
  a) Redis cache  (prices:{symbol})        — for REST endpoint
  b) Redis stream (market_events)          — wakes SIGNAL_AGENT
  c) Redis pub/sub (price_updates)         — for SSE browser streaming
  d) Postgres prices_snapshot              — persistent fallback
  e) Postgres system_metrics               — observability
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest, StockLatestQuoteRequest
from sqlalchemy import text

from api.config import settings
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis

SYMBOLS = {
    "crypto": ["BTC/USD", "ETH/USD", "SOL/USD"],
    "stocks": ["AAPL", "TSLA", "SPY"],
}

ALL_SYMBOLS = SYMBOLS["crypto"] + SYMBOLS["stocks"]


async def fetch_crypto_prices(
    client: CryptoHistoricalDataClient, symbols: list[str]
) -> dict[str, float]:
    """Fetch latest crypto prices from Alpaca. Returns {symbol: price}."""
    try:
        async with asyncio.timeout(8):
            request = CryptoLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = client.get_crypto_latest_quote(request)

        prices: dict[str, float] = {}
        for symbol in symbols:
            if symbol in quotes:
                quote = quotes[symbol]
                price = float(quote.bid_price if quote.bid_price else quote.ask_price)
                if price > 0:
                    prices[symbol] = price
                else:
                    log_structured("warning", "crypto zero price", symbol=symbol)
            else:
                log_structured("warning", "crypto_quote_missing", symbol=symbol)

        return prices

    except TimeoutError:
        log_structured("warning", "Alpaca timeout: crypto after 8s — skipping")
        return {}
    except Exception:
        log_structured("error", "crypto_price_fetch_failed", exc_info=True)
        return {}


async def fetch_stock_prices(
    client: StockHistoricalDataClient, symbols: list[str]
) -> dict[str, float]:
    """Fetch latest stock prices from Alpaca. Returns {symbol: price}."""
    try:
        async with asyncio.timeout(8):
            request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = client.get_stock_latest_quote(request)

        prices: dict[str, float] = {}
        for symbol in symbols:
            if symbol in quotes:
                quote = quotes[symbol]
                price = float(quote.bid_price if quote.bid_price else quote.ask_price)
                if price > 0:
                    prices[symbol] = price
                else:
                    log_structured("warning", "stock zero price", symbol=symbol)
            else:
                log_structured("warning", "stock_quote_missing", symbol=symbol)

        return prices

    except TimeoutError:
        log_structured("warning", "Alpaca timeout: stocks after 8s — skipping")
        return {}
    except Exception:
        log_structured("error", "stock_price_fetch_failed", exc_info=True)
        return {}


async def process_symbol(redis_client, symbol: str, current_price: float) -> None:
    """Process a single symbol: calculate change, write to Redis + Postgres."""
    ts = int(time.time())
    trace_id = str(uuid.uuid4())

    # FIX 1: Read previous price from Redis for change calculation
    prev_raw = await redis_client.get(f"prices:{symbol}")
    prev_data = json.loads(prev_raw) if prev_raw else None
    prev_price = prev_data["price"] if prev_data else None
    change = round(current_price - prev_price, 4) if prev_price else 0.0
    pct = round(((current_price - prev_price) / prev_price * 100), 4) if prev_price else 0.0

    price_payload = {
        "price": current_price,
        "change": change,
        "pct": pct,
        "ts": ts,
    }

    # (a) Redis cache write
    await redis_client.set(
        f"prices:{symbol}",
        json.dumps(price_payload),
        ex=30,
    )

    # (b) Redis Stream write — wakes SIGNAL_AGENT
    stream_payload = {
        "symbol": symbol,
        "price": current_price,
        "change": change,
        "pct": pct,
        "ts": ts,
        "trace_id": trace_id,
        "source": "price_poller",
    }
    await redis_client.xadd(
        "market_events",
        {"payload": json.dumps(stream_payload)},
    )
    await redis_client.xtrim("market_events", maxlen=1000, approximate=True)

    # (c) Redis pub/sub publish — for SSE browser streaming
    await redis_client.publish(
        "price_updates",
        json.dumps(
            {
                "symbol": symbol,
                "price": current_price,
                "change": change,
                "pct": pct,
                "ts": ts,
            }
        ),
    )

    # (d) Postgres upsert — persistent fallback
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT INTO prices_snapshot (symbol, price, change_amt, change_pct, updated_at)
                        VALUES (:symbol, :price, :change_amt, :change_pct, NOW())
                        ON CONFLICT (symbol) DO UPDATE SET
                            price = EXCLUDED.price,
                            change_amt = EXCLUDED.change_amt,
                            change_pct = EXCLUDED.change_pct,
                            updated_at = NOW()
                    """),
                    {
                        "symbol": symbol,
                        "price": current_price,
                        "change_amt": change,
                        "change_pct": pct,
                    },
                )

                # (e) Postgres system_metrics insert
                await session.execute(
                    text("""
                        INSERT INTO system_metrics
                            (metric_name, metric_value, metric_unit, tags,
                             schema_version, source, timestamp)
                        VALUES
                            ('price_fetch', :price, 'usd',
                             :tags, 'v3', 'price_poller', NOW())
                    """),
                    {
                        "price": current_price,
                        "tags": json.dumps({"symbol": symbol, "ts": ts}),
                    },
                )
    except Exception:
        log_structured("error", "Postgres write failed", symbol=symbol, exc_info=True)

    log_structured(
        "info",
        f"[price_poller] {symbol}: price={current_price} change={change:+.4f} pct={pct:+.4f}%",
    )


async def poll_prices():
    """Main price polling loop."""
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        log_structured(
            "error",
            "alpaca_credentials_missing",
            message="ALPACA_API_KEY and ALPACA_SECRET_KEY required",
        )
        return

    crypto_client = CryptoHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY, secret_key=settings.ALPACA_SECRET_KEY
    )
    stock_client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY, secret_key=settings.ALPACA_SECRET_KEY
    )

    redis_client = await get_redis()

    # Ensure market_events stream + consumer group exist
    try:
        await redis_client.xgroup_create("market_events", "workers", "$", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            pass  # Consumer group already exists — expected
        else:
            log_structured("error", "failed to create consumer group", exc_info=True)

    log_structured(
        "info",
        "[price_poller] starting: symbols=6 interval=5s",
    )

    while True:
        cycle_start = time.perf_counter()
        try:
            crypto_task = fetch_crypto_prices(crypto_client, SYMBOLS["crypto"])
            stock_task = fetch_stock_prices(stock_client, SYMBOLS["stocks"])

            crypto_prices, stock_prices = await asyncio.gather(
                crypto_task, stock_task, return_exceptions=True
            )

            if isinstance(crypto_prices, Exception):
                log_structured("error", "crypto_prices_exception", exc_info=True)
                crypto_prices = {}
            if isinstance(stock_prices, Exception):
                log_structured("error", "stock_prices_exception", exc_info=True)
                stock_prices = {}

            all_prices = {**crypto_prices, **stock_prices}

            if all_prices:
                for symbol, price in all_prices.items():
                    try:
                        await process_symbol(redis_client, symbol, price)
                    except Exception:
                        log_structured(
                            "error",
                            f"[price_poller] symbol write failed: {symbol}",
                            exc_info=True,
                        )
            else:
                log_structured("warning", "[price_poller] no prices fetched")

            # Worker heartbeat
            await redis_client.set(
                "worker:heartbeat",
                datetime.now(timezone.utc).isoformat(),
                ex=120,
            )

            elapsed_ms = round((time.perf_counter() - cycle_start) * 1000)
            fetched = len(all_prices)
            log_structured(
                "info",
                f"[price_poller] cycle complete: duration_ms={elapsed_ms} symbols={fetched}/6",
            )

        except Exception:
            log_structured("error", "[price_poller] cycle error", exc_info=True)

        # Only sleep: 5s poll interval
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_prices())
