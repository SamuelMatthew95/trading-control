"""Background worker that continuously polls market prices and caches them."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest, StockLatestQuoteRequest

from api.config import settings
from api.observability import log_structured
from api.redis_client import get_redis

SYMBOLS = {
    "crypto": ["BTC/USD", "ETH/USD", "SOL/USD"],
    "stocks": ["AAPL", "TSLA", "SPY"],
}

# Map symbol names to Alpaca format
ALPACA_SYMBOL_MAP = {
    "BTC/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "AAPL": "AAPL",
    "TSLA": "TSLA",
    "SPY": "SPY",
}


async def fetch_crypto_prices(
    client: CryptoHistoricalDataClient, symbols: list[str]
) -> dict[str, dict]:
    """Fetch latest crypto prices from Alpaca with rate limit protection."""
    max_retries = 3
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            request = CryptoLatestQuoteRequest(symbols=symbols)
            quotes = client.get_crypto_latest_quote(request)

            prices = {}
            for symbol in symbols:
                if symbol in quotes:
                    quote = quotes[symbol]
                    prices[symbol] = {
                        "price": str(
                            quote.bid_price if quote.bid_price else quote.ask_price
                        ),
                        "bid": str(quote.bid_price),
                        "ask": str(quote.ask_price),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "alpaca",
                    }
                else:
                    log_structured("warning", "crypto_quote_missing", symbol=symbol)

            return prices

        except Exception as e:
            if attempt == max_retries - 1:
                log_structured(
                    "error",
                    "crypto_price_fetch_failed",
                    exc_info=True,
                    attempt=attempt + 1,
                )
                return {}

            # Check if it's a rate limit error
            error_msg = str(e).lower()
            if (
                "rate limit" in error_msg
                or "429" in error_msg
                or "too many requests" in error_msg
            ):
                delay = base_delay * (
                    2**attempt
                )  # Exponential backoff for rate limits - allowed
                log_structured(
                    "warning", "rate_limit_hit", delay=delay, attempt=attempt + 1
                )
                await asyncio.sleep(delay)
            else:
                # For other errors, short retry delay - allowed
                await asyncio.sleep(0.5)

    return {}


async def fetch_stock_prices(
    client: StockHistoricalDataClient, symbols: list[str]
) -> dict[str, dict]:
    """Fetch latest stock prices from Alpaca with rate limit protection."""
    max_retries = 3
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            request = StockLatestQuoteRequest(symbols=symbols)
            quotes = client.get_stock_latest_quote(request)

            prices = {}
            for symbol in symbols:
                if symbol in quotes:
                    quote = quotes[symbol]
                    prices[symbol] = {
                        "price": str(
                            quote.bid_price if quote.bid_price else quote.ask_price
                        ),
                        "bid": str(quote.bid_price),
                        "ask": str(quote.ask_price),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "alpaca",
                    }
                else:
                    log_structured("warning", "stock_quote_missing", symbol=symbol)

            return prices

        except Exception as e:
            if attempt == max_retries - 1:
                log_structured(
                    "error",
                    "stock_price_fetch_failed",
                    exc_info=True,
                    attempt=attempt + 1,
                )
                return {}

            # Check if it's a rate limit error
            error_msg = str(e).lower()
            if (
                "rate limit" in error_msg
                or "429" in error_msg
                or "too many requests" in error_msg
            ):
                delay = base_delay * (
                    2**attempt
                )  # Exponential backoff for rate limits - allowed
                log_structured(
                    "warning", "rate_limit_hit", delay=delay, attempt=attempt + 1
                )
                await asyncio.sleep(delay)
            else:
                # For other errors, short retry delay - allowed
                await asyncio.sleep(0.5)

    return {}


async def cache_prices(redis_client, prices: dict[str, dict]) -> None:
    """Cache prices in Redis and publish updates."""
    pipe = redis_client.pipeline()

    for symbol, price_data in prices.items():
        # Atomic SET with EX to prevent orphaned keys
        cache_key = f"prices:{symbol}"
        pipe.set(cache_key, json.dumps(price_data), ex=60)

        # Publish to WebSocket channel
        message = {
            "type": "price_update",
            "symbol": symbol,
            "timestamp": price_data["timestamp"],
            **price_data,
        }
        pipe.publish("prices", json.dumps(message))

    # Add worker heartbeat
    pipe.set("worker:heartbeat", datetime.now(timezone.utc).isoformat(), ex=120)

    await pipe.execute()
    log_structured("info", "prices_cached", symbol_count=len(prices))


async def poll_prices():
    """Main price polling loop."""
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        log_structured(
            "error",
            "alpaca_credentials_missing",
            message="ALPACA_API_KEY and ALPACA_SECRET_KEY required",
        )
        return

    # Initialize Alpaca clients
    crypto_client = CryptoHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY, secret_key=settings.ALPACA_SECRET_KEY
    )
    stock_client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY, secret_key=settings.ALPACA_SECRET_KEY
    )

    redis_client = await get_redis()
    log_structured(
        "info",
        "price_poller_started",
        crypto_symbols=SYMBOLS["crypto"],
        stock_symbols=SYMBOLS["stocks"],
    )

    while True:
        try:
            # Fetch prices concurrently
            crypto_prices_task = fetch_crypto_prices(crypto_client, SYMBOLS["crypto"])
            stock_prices_task = fetch_stock_prices(stock_client, SYMBOLS["stocks"])

            crypto_prices, stock_prices = await asyncio.gather(
                crypto_prices_task, stock_prices_task, return_exceptions=True
            )

            # Handle exceptions
            if isinstance(crypto_prices, Exception):
                log_structured(
                    "error", "crypto_prices_exception", exc_info=crypto_prices
                )
                crypto_prices = {}

            if isinstance(stock_prices, Exception):
                log_structured("error", "stock_prices_exception", exc_info=stock_prices)
                stock_prices = {}

            # Combine all prices
            all_prices = {**crypto_prices, **stock_prices}

            if all_prices:
                await cache_prices(redis_client, all_prices)
            else:
                log_structured("warning", "no_prices_fetched")

            # Wait 5 seconds before next poll
            await asyncio.sleep(5)

        except Exception:
            log_structured("error", "price_poller_error", exc_info=True)
            await asyncio.sleep(10)  # Error recovery delay - allowed


if __name__ == "__main__":
    asyncio.run(poll_prices())
