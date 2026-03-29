#!/bin/bash
# Deployment Verification Script for Trading Control
# Run this after deploying to verify all components are working

set -e

echo "🔍 Trading Control - Deployment Verification"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if required environment variables are set
echo "📋 Checking environment variables..."
if [ -z "$DATABASE_URL" ]; then
    echo -e "${RED}❌ DATABASE_URL not set${NC}"
    exit 1
fi
if [ -z "$REDIS_URL" ]; then
    echo -e "${RED}❌ REDIS_URL not set${NC}"
    exit 1
fi
if [ -z "$ALPACA_API_KEY" ]; then
    echo -e "${RED}❌ ALPACA_API_KEY not set${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Environment variables configured${NC}"

# Check database connection
echo "🗄️ Testing database connection..."
python3 -c "
import asyncio
from api.database import AsyncSessionFactory

async def test_db():
    try:
        async with AsyncSessionFactory() as session:
            await session.execute('SELECT 1')
            print('✅ Database connection successful')
    except Exception as e:
        print(f'❌ Database connection failed: {e}')
        exit(1)

asyncio.run(test_db())
"

# Check Redis connection
echo "🔴 Testing Redis connection..."
python3 -c "
import asyncio
from api.redis_client import get_redis

async def test_redis():
    try:
        redis = await get_redis()
        await redis.ping()
        print('✅ Redis connection successful')
    except Exception as e:
        print(f'❌ Redis connection failed: {e}')
        exit(1)

asyncio.run(test_redis())
"

# Check Alpaca API connection
echo "📈 Testing Alpaca API connection..."
python3 -c "
import asyncio
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from api.config import settings

async def test_alpaca():
    try:
        if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
            print('❌ Alpaca credentials not configured')
            exit(1)
        
        crypto_client = CryptoHistoricalDataClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY
        )
        stock_client = StockHistoricalDataClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY
        )
        
        # Test fetching BTC price
        btc_data = await crypto_client.get_crypto_bars('BTC/USD', '1Min', limit=1)
        if btc_data and len(btc_data) > 0:
            print('✅ Alpaca API connection successful')
        else:
            print('❌ Alpaca API returned no data')
            exit(1)
    except Exception as e:
        print(f'❌ Alpaca API connection failed: {e}')
        exit(1)

asyncio.run(test_alpaca())
"

# Run database migrations
echo "🗃️ Running database migrations..."
alembic upgrade head
echo -e "${GREEN}✅ Database migrations complete${NC}"

# Check if agent pool is seeded
echo "🤖 Checking agent pool seeding..."
python3 -c "
import asyncio
from api.database import AsyncSessionFactory

async def check_agents():
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute('SELECT COUNT(*) FROM agent_pool')
            count = result.scalar()
            if count >= 7:
                print('✅ Agent pool seeded with 7+ agents')
            else:
                print(f'❌ Agent pool has only {count} agents (expected 7+)')
                exit(1)
    except Exception as e:
        print(f'❌ Agent pool check failed: {e}')
        exit(1)

asyncio.run(check_agents())
"

# Test FastAPI endpoints
echo "🌐 Testing FastAPI endpoints..."
echo "   Testing /api/v1/prices..."
curl -s -f http://localhost:8000/api/v1/prices > /dev/null || (echo -e "${RED}❌ Prices endpoint failed${NC}" && exit 1)

echo "   Testing /api/v1/agents/status..."
curl -s -f http://localhost:8000/api/v1/agents/status > /dev/null || (echo -e "${RED}❌ Agent status endpoint failed${NC}" && exit 1)

echo -e "${GREEN}✅ FastAPI endpoints working${NC}"

# Test SSE endpoint
echo "📡 Testing SSE endpoint..."
timeout 10s curl -N -H "Accept: text/event-stream" http://localhost:8000/api/v1/prices/stream | head -5 > /dev/null || echo -e "${YELLOW}⚠️  SSE endpoint may need running price poller${NC}"

# Check Redis keys
echo "🔑 Checking Redis setup..."
python3 -c "
import asyncio
from api.redis_client import get_redis

async def check_redis():
    try:
        redis = await get_redis()
        
        # Check for price keys
        price_keys = await redis.keys('prices:*')
        print(f'📊 Price keys found: {len(price_keys)}')
        
        # Check for agent status keys
        agent_keys = await redis.keys('agent:status:*')
        print(f'🤖 Agent status keys found: {len(agent_keys)}')
        
        # Check stream lengths
        market_events_len = await redis.xlen('market_events')
        signals_len = await redis.xlen('signals')
        print(f'📡 Stream lengths - market_events: {market_events_len}, signals: {signals_len}')
        
        if len(agent_keys) > 0:
            print('✅ Redis appears to be receiving data')
        else:
            print('⚠️  Redis has no agent status data (agents may not be running)')
            
    except Exception as e:
        print(f'❌ Redis check failed: {e}')

asyncio.run(check_redis())
"

# Check stream growth
echo "📈 Checking stream growth..."
COUNT1=$(redis-cli -u $REDIS_URL xlen market_events 2>/dev/null || echo "0")
sleep 8
COUNT2=$(redis-cli -u $REDIS_URL xlen market_events 2>/dev/null || echo "0")
if [ "$COUNT2" -gt "$COUNT1" ]; then
    echo "✅ PASS: market_events growing ($COUNT1 to $COUNT2)"
else
    echo "❌ FAIL: market_events not growing - poller may have crashed"
    FAILED=1
fi

# Check downstream agent streams
echo "🔗 Checking downstream agent streams..."
for STREAM in signals decisions graded_decisions; do
    LEN=$(redis-cli -u $REDIS_URL xlen $STREAM 2>/dev/null || echo "0")
    if [ "$LEN" -gt "0" ]; then
        echo "✅ PASS: $STREAM has $LEN entries"
    else
        echo "⚠️  WARN: $STREAM is empty - check agent pipeline"
        FAILED=1
    fi
done

echo ""
echo "🎉 Deployment verification complete!"
echo ""
echo "📝️  Next steps:"
echo "   1. If all checks passed, the system is ready"
echo "   2. Monitor logs: 'render logs trading-price-poller'"
echo "   3. Monitor logs: 'render logs trading-control'"
echo "   4. Open dashboard to verify live data"
echo ""
echo "🔧  Troubleshooting:"
echo "   - If agents show OFFLINE: Check price poller is running"
echo "   - If prices show '--': Check Redis cache and API endpoints"
echo "   - If SSE fails: Check CORS and firewall settings"
echo ""
