---
name: trading-market-data
description: Real-time stock price fetching and market data analysis for trading decisions. Use when you need current stock prices, market quotes, or financial data for symbols like "get AAPL stock price" or "what's the current price of TSLA".
---

# Trading Market Data

Fetches real-time stock quotes and market data from multiple sources with automatic fallback.

## Quick Start
```python
from trading_market_data.scripts.market_data import GetStockQuote

quote_tool = GetStockQuote()
result = await quote_tool.execute("AAPL")
print(f"Price: ${result['price']}")
```

## Features
- **Real-time quotes** from Alpha Vantage and Yahoo Finance
- **Automatic fallback** between data sources
- **Error handling** with graceful degradation
- **Standardized data format** across sources

## Data Sources
- Primary: Alpha Vantage API (requires `ALPHA_VANTAGE_API_KEY`)
- Fallback: Yahoo Finance (unofficial)

## Output Format
```python
{
    "symbol": "AAPL",
    "price": 175.43,
    "change": 1.25,
    "change_percent": 0.72,
    "volume": 1000000,
    "timestamp": "2024-01-15T16:00:00",
    "source": "alpha_vantage"
}
```

## Error Handling
- Returns structured error messages
- Automatic source switching on failures
- Network timeout protection

## Configuration
Set `ALPHA_VANTAGE_API_KEY` environment variable for premium data access.

---
*See [references/api-documentation.md](references/api-documentation.md) for detailed API specifications.*
