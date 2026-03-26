# Post-Deployment Testing Guide

## Quick Health Check (30 seconds)

```bash
# 1. Check API is up
curl https://your-app.render.com/api/health

# 2. Check Redis debug endpoints work
curl https://your-app.render.com/api/debug/health
curl https://your-app.render.com/api/debug/ws
```

## Full Test Sequence (5 minutes)

### Step 1: Verify Debug Endpoints
```bash
BASE_URL="https://your-app.render.com"

# List all streams
curl $BASE_URL/api/debug/streams | jq .

# Check WebSocket status
curl $BASE_URL/api/debug/ws | jq .

# Check pipeline health
curl $BASE_URL/api/debug/pipeline | jq .
```

### Step 2: Publish Test Event
```bash
# Publish to market_ticks stream
curl -X POST $BASE_URL/api/debug/publish/market_ticks \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "TEST",
    "price": 150.25,
    "volume": 1000,
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

### Step 3: Verify Event in Stream
```bash
# Check the event was published
curl $BASE_URL/api/debug/streams/market_ticks | jq .

# Check consumer lag
curl $BASE_URL/api/debug/lag | jq .
```

### Step 4: WebSocket Test (Browser Console)
```javascript
// Open browser console on your deployed app
const ws = new WebSocket('wss://your-app.render.com/ws');

ws.onopen = () => console.log('✅ WebSocket connected');
ws.onmessage = (e) => console.log('📨 Received:', JSON.parse(e.data));
ws.onerror = (e) => console.log('❌ Error:', e);
ws.onclose = () => console.log('🔌 Closed');
```

### Step 5: Verify End-to-End Flow
```bash
# 1. Check pending messages (should decrease after broadcast)
curl $BASE_URL/api/debug/pending/market_ticks | jq '.pending_count'

# 2. Tail stream for real-time view
curl $BASE_URL/api/debug/tail/market_ticks?count=5 | jq .
```

## Automated Test Script

Save this as `test_deployed.sh`:

```bash
#!/bin/bash
set -e

BASE_URL=${1:-"https://your-app.render.com"}

echo "🧪 Testing deployed app: $BASE_URL"

# Health check
echo "1️⃣ Health check..."
curl -sf $BASE_URL/api/health > /dev/null && echo "✅ API healthy"

# Debug endpoints
echo "2️⃣ Debug endpoints..."
curl -sf $BASE_URL/api/debug/health > /dev/null && echo "✅ Debug health OK"
curl -sf $BASE_URL/api/debug/ws > /dev/null && echo "✅ WebSocket debug OK"

# Publish test event
echo "3️⃣ Publishing test event..."
RESPONSE=$(curl -sf -X POST $BASE_URL/api/debug/publish/market_ticks \
  -H "Content-Type: application/json" \
  -d '{"symbol":"TEST","price":150.25}')
echo "✅ Published: $(echo $RESPONSE | jq -r '.message_id')"

# Verify in stream
echo "4️⃣ Verifying in stream..."
curl -sf $BASE_URL/api/debug/streams/market_ticks > /dev/null && echo "✅ Stream accessible"

# Pipeline health
echo "5️⃣ Pipeline health..."
curl -sf $BASE_URL/api/debug/pipeline | jq '.healthy' && echo "✅ Pipeline healthy"

echo ""
echo "🎉 All tests passed!"
```

Run: `chmod +x test_deployed.sh && ./test_deployed.sh https://your-app.render.com`

## Manual UI Verification

1. **Open your deployed app** in browser
2. **Open DevTools** → Network tab
3. **Look for WebSocket connection** (ws:// or wss://)
4. **Check for incoming messages** in console:
   - `type: "dashboard_update"` - from snapshot loop
   - `type: "event"` - from real-time stream

## Log Verification (Render Dashboard)

```bash
# Check these log patterns in Render dashboard:
[STARTUP] Redis connected              # API started
stream_consumer_started                # Background consumer running
event_consumed                         # Reading from Redis
ws_event_sent                          # Broadcast success
stream_batch_processed                 # Batch visibility
```

## Troubleshooting

### WebSocket not connecting
```bash
# Check wss:// vs ws:// (must match HTTPS/HTTP)
curl -I $BASE_URL/ws  # Should upgrade to WebSocket
```

### No events received
```bash
# Check consumer lag - should be 0
curl $BASE_URL/api/debug/lag | jq '.streams[].lag'

# Check if messages stuck in pending
curl $BASE_URL/api/debug/pending/market_ticks | jq '.messages'
```

### Redis connection issues
```bash
# Check Redis health
curl $BASE_URL/api/debug/health | jq '.streams.healthy'
```

## Expected Response Examples

**Stream Health:**
```json
{
  "status": "healthy",
  "streams": {
    "healthy": 9,
    "unhealthy": 0
  }
}
```

**WebSocket Status:**
```json
{
  "connections": 1,
  "status": "active"
}
```

**Pipeline Health:**
```json
{
  "healthy": true,
  "api": "up",
  "redis": "connected",
  "websocket": "active"
}
```
