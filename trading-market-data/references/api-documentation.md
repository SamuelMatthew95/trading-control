# API Documentation

## Alpha Vantage API

### Endpoint
```
GET https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={api_key}
```

### Parameters
- `symbol`: Stock ticker symbol (e.g., "AAPL", "MSFT")
- `apikey`: Your Alpha Vantage API key

### Response Format
```json
{
    "Global Quote": {
        "01. symbol": "AAPL",
        "02. open": "175.00",
        "03. high": "176.50",
        "04. low": "174.20",
        "05. price": "175.43",
        "06. volume": "1000000",
        "07. latest trading day": "2024-01-15",
        "08. previous close": "174.18",
        "09. change": "1.25",
        "10. change percent": "0.72%"
    }
}
```

### Rate Limits
- Free tier: 5 requests per minute, 500 requests per day
- Premium: Up to 5 requests per minute

## Yahoo Finance API

### Endpoint
```
GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
```

### Headers
```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
```

### Response Format
```json
{
    "chart": {
        "result": [{
            "meta": {
                "symbol": "AAPL",
                "regularMarketPrice": 175.43,
                "previousClose": 174.18,
                "regularMarketTime": 1705125600
            },
            "indicators": {
                "quote": [{
                    "close": [175.43],
                    "volume": [1000000]
                }]
            }
        }]
    }
}
```

## Error Codes

| Code | Description | Resolution |
|------|-------------|------------|
| 200 | Success | - |
| 400 | Invalid Symbol | Check ticker format |
| 429 | Rate Limited | Wait or use premium key |
| 500 | Server Error | Try fallback source |
