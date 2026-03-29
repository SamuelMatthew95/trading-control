"""Background worker that continuously polls market prices and caches them."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame

from api.config import settings
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis

SYMBOLS = {
    "crypto": ["BTC/USD", "ETH/USD", "SOL/USD"],
    "stocks": ["AAPL", "TSLA", "SPY"]
}

# Map symbol names to Alpaca format
ALPACA_SYMBOL_MAP = {
    "BTC/USD": "BTC/USD",
    "ETH/USD": "ETH/USD", 
    "SOL/USD": "SOL/USD",
    "AAPL": "AAPL",
    "TSLA": "TSLA",
    "SPY": "SPY"
}


async def fetch_crypto_prices(client: CryptoHistoricalDataClient, symbols: list[str]) -> dict[str, dict]:
    """Fetch latest crypto prices from Alpaca with rate limit protection."""
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            # Add 8-second timeout to API call
            request = CryptoLatestQuoteRequest(symbols=symbols)
            quotes = await asyncio.wait_for(
                client.get_crypto_latest_quote(request),
                timeout=8.0
            )
            
            prices = {}
            for symbol in symbols:
                if symbol in quotes:
                    quote = quotes[symbol]
                    prices[symbol] = {
                        "price": str(quote.bid_price if quote.bid_price else quote.ask_price),
                        "bid": str(quote.bid_price),
                        "ask": str(quote.ask_price),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "alpaca"
                    }
                else:
                    log_structured("warning", "crypto_quote_missing", symbol=symbol)
                    
            return prices
            
        except asyncio.TimeoutError:
            log_structured("warning", "alpaca_timeout", symbol=symbols, attempt=attempt + 1, timeout="8s")
            if attempt == max_retries - 1:
                log_structured("error", "crypto_price_fetch_timeout", exc_info=True, attempt=attempt + 1)
                return {}
            await asyncio.sleep(1.0)  # Wait longer on timeout
            continue
            
        except Exception as e:
            if attempt == max_retries - 1:
                log_structured("error", "crypto_price_fetch_failed", exc_info=True, attempt=attempt + 1)
                return {}
            
            # Check if it's a rate limit error
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "429" in error_msg or "too many requests" in error_msg:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                log_structured("warning", "rate_limit_hit", delay=delay, attempt=attempt + 1)
                await asyncio.sleep(delay)
            else:
                # For other errors, retry with shorter delay
                await asyncio.sleep(0.5)
        
    return {}


async def fetch_stock_prices(client: StockHistoricalDataClient, symbols: list[str]) -> dict[str, dict]:
    """Fetch latest stock prices from Alpaca with rate limit protection."""
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            # Add 8-second timeout to API call
            request = StockLatestQuoteRequest(symbols=symbols)
            quotes = await asyncio.wait_for(
                client.get_stock_latest_quote(request),
                timeout=8.0
            )
            
            prices = {}
            for symbol in symbols:
                if symbol in quotes:
                    quote = quotes[symbol]
                    prices[symbol] = {
                        "price": str(quote.bid_price if quote.bid_price else quote.ask_price),
                        "bid": str(quote.bid_price),
                        "ask": str(quote.ask_price),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "alpaca"
                    }
                else:
                    log_structured("warning", "stock_quote_missing", symbol=symbol)
                    
            return prices
            
        except asyncio.TimeoutError:
            log_structured("warning", "alpaca_timeout", symbol=symbols, attempt=attempt + 1, timeout="8s")
            if attempt == max_retries - 1:
                log_structured("error", "stock_price_fetch_timeout", exc_info=True, attempt=attempt + 1)
                return {}
            await asyncio.sleep(1.0)  # Wait longer on timeout
            continue
            
        except Exception as e:
            if attempt == max_retries - 1:
                log_structured("error", "stock_price_fetch_failed", exc_info=True, attempt=attempt + 1)
                return {}
            
            # Check if it's a rate limit error
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "429" in error_msg or "too many requests" in error_msg:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                log_structured("warning", "rate_limit_hit", delay=delay, attempt=attempt + 1)
                await asyncio.sleep(delay)
            else:
                # For other errors, retry with shorter delay
                await asyncio.sleep(0.5)
        
    return {}


async def cache_prices(redis_client, prices: dict[str, dict]) -> None:
    """Cache prices in Redis, publish updates, write to streams, and persist to Postgres."""
    pipe = redis_client.pipeline()
    
    for symbol, price_data in prices.items():
        # Extract numeric values
        current_price = float(price_data["price"])
        timestamp = int(time.time())
        
        # Get previous price from Redis to calculate change
        cache_key = f"prices:{symbol}"
        previous_data = await redis_client.get(cache_key)
        
        if previous_data:
            try:
                prev_json = json.loads(previous_data)
                prev_price = prev_json.get("price", current_price)
                change = current_price - prev_price
                change_pct = (change / prev_price * 100) if prev_price != 0 else 0.0
            except (json.JSONDecodeError, KeyError, TypeError):
                change = 0.0
                change_pct = 0.0
        else:
            # First time seeing this symbol
            change = 0.0
            change_pct = 0.0
        
        # 1. Write to Redis cache (for instant REST endpoint responses)
        cache_payload = {
            "price": current_price,
            "change": change,
            "pct": change_pct,
            "ts": timestamp
        }
        pipe.set(cache_key, json.dumps(cache_payload), ex=30)
        
        # 2. Write to Redis Stream (this is what wakes up SIGNAL_AGENT)
        stream_payload = {
            "payload": json.dumps({
                "symbol": symbol,
                "price": current_price,
                "change": change,
                "pct": change_pct,
                "ts": timestamp,
                "source": "price_poller"
            })
        }
        pipe.xadd("market_events", stream_payload)
        
        # 3. Publish to Redis pub/sub channel (for SSE streaming to browsers)
        pub_payload = {
            "symbol": symbol,
            "price": current_price,
            "change": change,
            "pct": change_pct,
            "ts": timestamp
        }
        pipe.publish("price_updates", json.dumps(pub_payload))
    
    # 4. Trim the stream to last 1000 entries
    pipe.xtrim("market_events", maxlen=1000, approximate=True)
    
    # 5. Add worker heartbeat
    pipe.set("worker:heartbeat", datetime.now(timezone.utc).isoformat(), ex=120)
    
    await pipe.execute()
    
    # 6. Upsert to Postgres prices_snapshot table (persistent fallback)
    await persist_prices_to_postgres(prices)
    
    # 7. Write system metrics
    await write_system_metrics(prices)
    
    log_structured("info", "prices_cached", symbol_count=len(prices))


async def persist_prices_to_postgres(prices: dict[str, dict]) -> None:
    """Persist prices to Postgres prices_snapshot table."""
    async with AsyncSessionFactory() as session:
        for symbol, price_data in prices.items():
            current_price = float(price_data["price"])
            # Get previous price from Postgres to calculate change
            result = await session.execute(
                "SELECT price FROM prices_snapshot WHERE symbol = %s",
                (symbol,)
            )
            row = result.fetchone()
            
            if row and row[0]:
                prev_price = float(row[0])
                change_amt = current_price - prev_price
                change_pct = (change_amt / prev_price * 100) if prev_price != 0 else 0.0
            else:
                # First time seeing this symbol
                change_amt = 0.0
                change_pct = 0.0
            
            await session.execute(
                """
                INSERT INTO prices_snapshot (symbol, price, change_amt, change_pct, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                  price = EXCLUDED.price,
                  change_amt = EXCLUDED.change_amt,
                  change_pct = EXCLUDED.change_pct,
                  updated_at = EXCLUDED.updated_at
                """,
                (symbol, current_price, change_amt, change_pct)
            )
        await session.commit()
    log_structured("info", "prices_persisted_postgres", symbol_count=len(prices))


async def write_system_metrics(prices: dict[str, dict]) -> None:
    """Write system metrics for monitoring."""
    async with AsyncSessionFactory() as session:
        for symbol, price_data in prices.items():
            await session.execute(
                """
                INSERT INTO system_metrics (metric_name, metric_value, metric_unit, tags,
                                            schema_version, source, timestamp)
                VALUES ('price_fetch_latency_ms', 0, 'ms',
                        '{"symbol": "%s"}', 'v2', 'price_poller', NOW())
                """ % symbol
            )
        await session.commit()
    log_structured("info", "system_metrics_written", symbol_count=len(prices))


async def poll_prices():
    """Main price polling loop."""
    log_structured("info", "[poller] Trading price poller starting up...")
    log_structured("info", f"[poller] Symbols: {SYMBOLS['crypto'] + SYMBOLS['stocks']}")
    log_structured("info", "[poller] Poll interval: 5 seconds")
    
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        log_structured("error", "alpaca_credentials_missing", 
                       message="ALPACA_API_KEY and ALPACA_SECRET_KEY required")
        return
    
    # Initialize Alpaca clients
    crypto_client = CryptoHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY
    )
    stock_client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY
    )
    
    redis_client = await get_redis()
    log_structured("info", "[poller] Price poller started successfully")
    
    while True:
        try:
            cycle_start_time = time.time()
            
            # Fetch prices concurrently
            crypto_prices_task = fetch_crypto_prices(crypto_client, SYMBOLS["crypto"])
            stock_prices_task = fetch_stock_prices(stock_client, SYMBOLS["stocks"])
            
            crypto_prices, stock_prices = await asyncio.gather(
                crypto_prices_task,
                stock_prices_task,
                return_exceptions=True
            )
            
            # Handle exceptions
            if isinstance(crypto_prices, Exception):
                log_structured("error", "crypto_prices_exception", exc_info=crypto_prices)
                crypto_prices = {}
            
            if isinstance(stock_prices, Exception):
                log_structured("error", "stock_prices_exception", exc_info=stock_prices)
                stock_prices = {}
            
            # Combine all prices
            all_prices = {**crypto_prices, **stock_prices}
            
            if all_prices:
                await cache_prices(redis_client, all_prices)
                
                # Log each symbol's price
                for symbol, price_data in all_prices.items():
                    price = float(price_data["price"])
                    # Get change from cache for logging
                    cache_key = f"prices:{symbol}"
                    cached = await redis_client.get(cache_key)
                    if cached:
                        try:
                            cached_data = json.loads(cached)
                            change = cached_data.get("change", 0)
                            pct = cached_data.get("pct", 0)
                            log_structured("info", f"[poller] {symbol}=${price:.2f} chg={change:+.2f} ({pct:+.2f}%) ts={int(time.time())}")
                        except:
                            log_structured("info", f"[poller] {symbol}=${price:.2f}")
                    else:
                        log_structured("info", f"[poller] {symbol}=${price:.2f}")
                
                cycle_time = (time.time() - cycle_start_time) * 1000
                log_structured("info", f"[poller] cycle complete — {len(all_prices)} symbols updated at {datetime.now(timezone.utc).isoformat()} ({cycle_time:.1f}ms)")
            else:
                log_structured("warning", "[poller] no prices fetched")
            
            # Wait 5 seconds before next poll
            await asyncio.sleep(5)
            
        except Exception as e:
            log_structured("error", "[poller] price poller error", exc_info=True)
            await asyncio.sleep(10)  # Wait longer on error


if __name__ == "__main__":
    asyncio.run(poll_prices())
