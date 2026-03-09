---
name: Market Analysis
description: Real-time market data collection and analysis for trading intelligence
---

# Market Analysis Skill

## Overview
The Market Analysis skill provides real-time stock quotes, market data, and technical indicators for the OpenClaw Trading Control Platform.

## Capabilities

### Level 1: High-Level Overview
- Real-time stock price fetching
- Multiple data source integration (Alpha Vantage, Yahoo Finance)
- Market data validation and normalization

### Level 2: Implementation Details
- **Primary Tool**: `GetStockQuote` class
- **Data Sources**: Alpha Vantage API (primary), Yahoo Finance (fallback)
- **Error Handling**: Graceful degradation between data sources
- **Rate Limiting**: Built-in API rate limiting and timeout handling

### Level 3: Technical Specifications

#### API Integration
```python
# Alpha Vantage API
url = "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={api_key}"

# Yahoo Finance API  
url = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
```

#### Data Structure
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

## Usage Examples

### Basic Stock Quote
```python
from market_analysis.scripts.market_data import GetStockQuote

quote_tool = GetStockQuote()
result = await quote_tool.execute("AAPL")
print(result["price"])  # 175.43
```

### Error Handling
```python
result = await quote_tool.execute("INVALID")
if "error" in result:
    print(f"Error: {result['error']}")
```

## Dependencies
- `aiohttp` for HTTP requests
- `os` for environment variables
- `datetime` for timestamp handling

## Configuration
Required environment variables:
- `ALPHA_VANTAGE_API_KEY` (optional, for Alpha Vantage API)

## Monitoring
- Request success/failure tracking
- Response time monitoring
- Data source fallback tracking
