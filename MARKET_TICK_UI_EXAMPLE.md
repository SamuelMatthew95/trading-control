# Market Tick Data - UI Display Example

## 📊 **Market Tick Data Structure**

### **Raw Market Tick Format**
```json
{
  "symbol": "AAPL",
  "price": 178.25,
  "bid": 178.24,
  "ask": 178.26,
  "volume": 5.123,
  "timestamp": "2026-03-25T20:30:00Z",
  "source": "paper"
}
```

## 🎯 **How It Appears in Dashboard**

### **Market Ticks Table**
| Symbol | Price | Bid | Ask | Volume | Timestamp | Source |
|---------|-------|-----|-----|--------|-----------|---------|
| AAPL | 178.25 | 178.24 | 178.26 | 5.123 | 20:30:00 | paper |
| BTC/USD | 67,100.00 | 67,099.50 | 67,100.50 | 1.234 | 20:30:10 | paper |
| ETH/USD | 3,500.75 | 3,500.25 | 3,501.25 | 2.567 | 20:30:20 | paper |
| NVDA | 875.50 | 875.25 | 875.75 | 3.890 | 20:30:30 | paper |

### **Real-time Updates**
```
20:30:00 - New market tick: AAPL $178.25
20:30:10 - New market tick: BTC/USD $67,100.00
20:30:20 - New market tick: ETH/USD $3,500.75
20:30:30 - New market tick: NVDA $875.50
```

## 🔄 **Data Flow to UI**

### **Step 1: Market Ingestor Generates Tick**
```python
# Every 10 seconds, MarketIngestor creates:
tick = {
    "symbol": "AAPL",
    "price": 178.25,
    "bid": 178.24,
    "ask": 178.26,
    "volume": 5.123,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "source": "paper"
}
```

### **Step 2: Published to Redis Stream**
```bash
# Redis stream: market_ticks
redis-cli XADD market_ticks '{
  "symbol": "AAPL",
  "price": 178.25,
  "bid": 178.24,
  "ask": 178.26,
  "volume": 5.123,
  "timestamp": "2026-03-25T20:30:00Z",
  "source": "paper"
}'
```

### **Step 3: SignalGenerator Processes**
```python
# SignalGenerator receives tick and creates signal
if price > 100:
    signal = "BUY"
else:
    signal = "SELL"

# Publishes to signals stream
{
  "symbol": "AAPL",
  "signal": "BUY",
  "confidence": 0.85,
  "reason": "Price above threshold",
  "trace_id": "trace-001"
}
```

### **Step 4: Dashboard Updates**
```javascript
// WebSocket receives update
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'market_tick') {
    updateMarketTicksTable(data.tick);
  }
  
  if (data.type === 'signal') {
    updateSignalsTable(data.signal);
  }
};
```

## 📱 **UI Components**

### **Market Ticks Panel**
```
┌─────────────────────────────────────────┐
│ Market Ticks                            │
├─────────────────────────────────────────┤
│ Symbol    Price     Bid     Ask  Volume │
│ AAPL      178.25   178.24  178.26 5.123 │
│ BTC/USD   67,100   67,099  67,101 1.234 │
│ ETH/USD   3,500.75 3,500  3,501  2.567 │
│ NVDA      875.50   875.25 875.75 3.890 │
└─────────────────────────────────────────┘
```

### **Trading Signals Panel**
```
┌─────────────────────────────────────────┐
│ Trading Signals                         │
├─────────────────────────────────────────┤
│ Symbol   Signal  Confidence  Time       │
│ AAPL     BUY     85%         20:30:01   │
│ BTC/USD  HOLD    92%         20:30:11   │
│ ETH/USD  BUY     78%         20:30:21   │
└─────────────────────────────────────────┘
```

### **Performance Metrics Panel**
```
┌─────────────────────────────────────────┐
│ Performance Metrics                     │
├─────────────────────────────────────────┤
│ Total Trades: 42                        │
│ Win Rate: 68%                          │
│ Avg PnL: $12.50                        │
│ Total PnL: $525.00                     │
└─────────────────────────────────────────┘
```

## 🎯 **Key Data Points**

### **What You'll See Every 10 Seconds**
1. **New market tick** appears in Market Ticks table
2. **Trading signal** generated and appears in Signals table
3. **Order created** (if signal is BUY/SELL)
4. **Execution processed** and appears in Executions table
5. **Performance metrics** updated
6. **Dashboard refreshes** automatically

### **Data Traceability**
- Every tick has unique `trace_id`
- Follow one tick through entire pipeline
- See how market data becomes trading decisions
- Track performance of each signal

## 📊 **Sample Timeline**

```
20:30:00 - Market tick: AAPL $178.25
20:30:01 - Signal: BUY (confidence 85%)
20:30:02 - Order: Buy 100 shares AAPL
20:30:03 - Execution: Filled at $178.26
20:30:04 - Performance: PnL +$10.00
20:30:05 - Grade: SignalGenerator A+
20:30:06 - Reflection: Strategy working well
20:30:07 - Notification: Trade completed
20:30:08 - Dashboard: All tables updated
```

## 🎯 **Summary**

The market tick data will appear in your dashboard as:
- **Clean, structured tables** with real-time updates
- **Professional formatting** with no random elements
- **Clear data flow** from market tick to trading decision
- **Consistent updates** every 10 seconds
- **Full traceability** through the entire pipeline

**No random data, no emojis, no confusing elements - just clean professional market data!**
