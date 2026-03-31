# Alpaca Trading & Order Execution Memory

## Broker Configuration (CRITICAL)
- **Library**: Use `alpaca-py` v0.8+ only
- **Environment**: ALWAYS `ALPACA_PAPER=true` during development
- **Base URL**: `https://paper-api.alpaca.markets` (NEVER use live URL without explicit confirmation)
- **Error Handling**: Wrap ALL Alpaca calls in try/except for `AlpacaAPIError`
- **Rate Limits**: 200 requests/minute free tier - implement exponential backoff

### Alpaca Client Setup
```python
import alpaca_trade_api as tradeapi

# PAPER TRADING ONLY (development)
api = tradeapi.REST(
    key_id=ALPACA_API_KEY,
    secret_key=ALPACA_SECRET_KEY,
    base_url='https://paper-api.alpaca.markets',  # PAPER ONLY
    api_version='v2'
)

# Live trading requires explicit confirmation:
# if os.getenv("TRADING_MODE") == "LIVE":
#     base_url = 'https://api.alpaca.markets'
```

## Order Execution Rules

### Order Types & Timing
- **Market Hours**: NO market orders after 16:00 ET
- **After Hours**: Use limit orders only with `time_in_force='gtc'`
- **Default Time in Force**: `gtc` (Good Till Canceled)
- **Order Types**: 
  - Market: During regular hours only
  - Limit: Required for after-hours trading
  - Stop: Always use ATR-based stops

### Order Idempotency (MANDATORY)
```python
# EVERY order must have unique client_order_id
def generate_client_order_id(trace_id: str, symbol: str) -> str:
    return f"{symbol}_{trace_id}_{int(time.time())}"

# Order creation pattern
order = api.submit_order(
    symbol=symbol,
    qty=quantity,
    side=side,
    type=order_type,
    time_in_force='gtc',
    client_order_id=generate_client_order_id(trace_id, symbol)  # MANDATORY
)
```

## State Management Rules

### Redis as Source of Truth
- **Open Positions**: Redis `positions:{symbol}` hash is canonical state
- **Order Status**: Redis `orders:{order_id}` hash overrides local agent state
- **Never Trust Local State**: Always verify against Redis before acting
- **Position Updates**: Write to Redis first, then database

### Redis Position Structure
```python
# Position state in Redis
position_key = f"positions:{symbol}"
position_data = {
    "symbol": symbol,
    "quantity": "0.1",  # String for Redis
    "entry_price": "43250.50",
    "unrealized_pnl": "25.30",
    "last_updated": datetime.now(timezone.utc).isoformat(),
    "trace_id": trace_id
}

# Always use Redis transactions for updates
await redis.hset(position_key, mapping=position_data)
```

## Position Sizing & Risk Management

### Portfolio Risk Rules
- **Max per Trade**: 5% of total portfolio value
- **Max per Symbol**: 10% of portfolio exposure
- **Daily Loss Limit**: Stop trading if daily PnL < -2%
- **Correlation Limit**: Max 3 highly correlated positions simultaneously

### Position Sizing Calculation
```python
def calculate_position_size(
    portfolio_value: float, 
    risk_per_trade: float = 0.05,  # 5%
    atr: float = None,
    stop_distance_pct: float = 0.02  # 2% stop
) -> float:
    """Calculate position size based on risk rules."""
    
    # Base position size from portfolio risk
    max_position_value = portfolio_value * risk_per_trade
    
    # Adjust for ATR if available
    if atr:
        # Ensure stop loss is within risk tolerance
        atr_adjusted_size = (portfolio_value * risk_per_trade) / (atr * 2)
        return min(max_position_value / current_price, atr_adjusted_size)
    
    return max_position_value / current_price
```

## Asset Universe & Symbol Mapping

### Supported Assets
```python
# Approved trading symbols
SUPPORTED_SYMBOLS = {
    # Crypto
    "BTC/USD": {"asset_class": "crypto", "min_size": 0.001},
    "ETH/USD": {"asset_class": "crypto", "min_size": 0.01},
    
    # Equities (if enabled)
    "AAPL": {"asset_class": "equity", "min_size": 1},
    "TSLA": {"asset_class": "equity", "min_size": 1},
}

# Symbol validation
def is_symbol_supported(symbol: str) -> bool:
    return symbol in SUPPORTED_SYMBOLS

def get_min_size(symbol: str) -> float:
    return SUPPORTED_SYMBOLS.get(symbol, {}).get("min_size", 0)
```

## Paper Trading Configuration

### Environment Variables
```bash
# REQUIRED for development
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_MODE=PAPER

# Portfolio configuration (paper trading)
PAPER_PORTFOLIO_VALUE=100000.0
MAX_POSITION_SIZE_PCT=0.05
DAILY_LOSS_LIMIT_PCT=0.02
```

### Paper Trading Specifics
- **Starting Capital**: $100,000 (configurable)
- **Commission**: $0.0005 per share (Alpaca paper rates)
- **Slippage**: Model 1-3 bps for crypto, 5-10 bps for equities
- **Execution Delay**: Simulate 100-500ms network latency

## Order Execution Patterns

### SafeWriter Integration
```python
# Always use SafeWriter for order creation
async def place_order(order_data: dict) -> UUID:
    async with get_async_session() as session:
        writer = SafeWriter(session)
        return await writer.write(
            table="orders",
            data={
                **order_data,
                "schema_version": "v3",
                "source": "execution_engine",
                "idempotency_key": f"{order_data['symbol']}_{order_data['strategy_id']}_{int(time.time())}"
            }
        )
```

### Critical Order Rules
- **Idempotency**: Every order needs unique `idempotency_key`
- **Schema Version**: Must be `"v3"` for all order writes
- **Position Limits**: Never exceed 10% of portfolio per symbol
- **Risk Checks**: Validate ATR-based stop losses before execution

## Market Data Handling

### Tick Processing
```python
# SignalGenerator triggers every N ticks
SIGNAL_EVERY_N_TICKS = 10  # Configurable per symbol

# Market tick structure
{
    "symbol": "BTC/USD",
    "price": 43250.50,
    "volume": 1.23,
    "timestamp": "2024-03-31T18:30:00Z",
    "trace_id": "uuid-string"
}
```

### Data Validation
- **Price Sanity**: Reject prices >10% from last tick
- **Timestamp Order**: Ensure chronological tick processing
- **Symbol Format**: Always "BASE/QUOTE" (e.g., "BTC/USD")

## Execution Engine Integration

### Order Lifecycle
1. **Signal** → ReasoningAgent creates decision
2. **Order** → SafeWriter writes to orders table
3. **Execution** → ExecutionEngine submits to Alpaca
4. **Fill** → Updates order status, creates trade_performance record
5. **PnL** → Computed from position snapshots

### Error Handling
```python
# Alpaca API errors
except alpaca.trade_rest.APIError as exc:
    log_structured("error", "alpaca api error", 
                  symbol=order.symbol, 
                  error_code=exc.code,
                  exc_info=True)
    
# Network issues  
except aiohttp.ClientError as exc:
    log_structured("warning", "network error, retrying", 
                  attempt=retry_count,
                  exc_info=True)
    await asyncio.sleep(2 ** retry_count)  # Exponential backoff
```

## Performance Monitoring

### Key Metrics
- **Order Latency**: Signal → Fill time (target: <5 seconds)
- **Fill Rate**: Percentage of orders that execute (target: >95%)
- **Slippage**: Expected vs actual execution price
- **PnL Tracking**: Realized profit/loss per trade

### Redis Stream Events
```python
# Order events
{
    "type": "order_created",
    "data": {"order_id": uuid, "symbol": "BTC/USD", "side": "buy"},
    "trace_id": "uuid-string"
}

# Execution events  
{
    "type": "order_filled",
    "data": {"order_id": uuid, "fill_price": 43251.00, "quantity": 0.1},
    "trace_id": "uuid-string"
}
```
