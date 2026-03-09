# Claude Integration Guide

## Production Trading System with Claude Code

This guide explains how to integrate the production trading system with Claude Code for development workflow automation, slash commands, and MCP integrations.

## Installation and Setup

### 1. Install Claude Code Template
```bash
# Install the complete trading system template
npx claude-code-templates@latest --agent trading-system-orchestrator --command trading/analyze --mcp trading-data --yes

# Interactive installation with specific components
npx claude-code-templates@latest
```

### 2. Environment Configuration
```bash
# Required environment variables
export CLAUDE_API_KEY="your-claude-api-key"
export ALPHA_VANTAGE_API_KEY="your-alpha-vantage-key"
export TRADING_DB_URL="postgresql://user:pass@localhost/trading"
export NOTIFICATION_WEBHOOK_URL="https://hooks.slack.com/..."

# Optional performance settings
export TRADING_TIMEOUT_MS="30000"
export TRADING_MEMORY_LIMIT_MB="2048"
export TRADING_CACHE_TTL="3600"
```

### 3. Initialize Integration
```python
from trading_claude_integration.scripts.claude_integration import create_claude_integration

# Create integration instance
integration = create_claude_integration()
await integration.initialize()
```

## Slash Commands

### Market Analysis Commands

#### Basic Analysis
```bash
# Analyze single symbol with default indicators
/analyze-trading AAPL

# Specify indicators and timeframe
/analyze-trading TSLA --indicators=RSI,MACD,BB --timeframe=1d

# Multiple symbols
/analyze-trading AAPL,MSFT,GOOGL --indicators=RSI,MACD
```

#### Advanced Analysis
```bash
# Comprehensive analysis with all indicators
/analyze-trading NVDA --indicators=RSI,MACD,BB,ATR,OBV --timeframe=4h

# Analysis with custom parameters
/analyze-trading AMD --indicators=RSI --period=14 --threshold=70
```

### Data Validation Commands

#### Single Source Validation
```bash
# Validate data from Alpha Vantage
/validate-market-data --source=alpha_vantage --symbol=AAPL

# Validate from Yahoo Finance
/validate-market-data --source=yahoo_finance --symbol=MSFT
```

#### Batch Validation
```bash
# Validate multiple symbols
/validate-market-data --source=alpha_vantage --symbols=AAPL,MSFT,GOOGL

# Cross-source validation
/validate-market-data --sources=alpha_vantage,yahoo_finance --symbol=AAPL
```

### System Health Commands

#### Basic Health Check
```bash
# Quick system status
/portfolio-health

# Detailed health metrics
/portfolio-health --detailed

# Component-specific health
/portfolio-health --components=database,api,memory
```

### Risk Assessment Commands

#### Portfolio Risk Analysis
```bash
# Basic risk assessment
/risk-assessment --portfolio=my_portfolio.json

# Risk with tolerance level
/risk-assessment --portfolio=my_portfolio.json --risk_tolerance=low

# Detailed risk analysis
/risk-assessment --portfolio=my_portfolio.json --detailed --recommendations
```

## MCP Integrations

### Trading Data MCP
```python
# Configure trading data MCP
{
  "name": "trading-data-mcp",
  "endpoints": {
    "alpha_vantage": {
      "url": "https://www.alphavantage.co/query",
      "api_key": "${ALPHA_VANTAGE_API_KEY}",
      "rate_limit": 5  # requests per minute
    },
    "yahoo_finance": {
      "url": "https://query1.finance.yahoo.com/v8/finance/chart",
      "rate_limit": 100  # requests per minute
    }
  }
}
```

### Portfolio Database MCP
```python
# Configure portfolio database MCP
{
  "name": "portfolio-database-mcp",
  "database": {
    "provider": "postgresql",
    "connection_url": "${TRADING_DB_URL}",
    "connection_pool_size": 10,
    "tables": {
      "trades": "id, symbol, quantity, price, timestamp",
      "positions": "id, symbol, shares, average_cost, current_value",
      "market_data": "id, symbol, price, volume, timestamp",
      "signals": "id, symbol, signal, confidence, timestamp"
    }
  }
}
```

### Notification MCP
```python
# Configure notification MCP
{
  "name": "notification-mcp",
  "channels": {
    "slack": {
      "webhook_url": "${NOTIFICATION_WEBHOOK_URL}",
      "channel": "#trading-alerts"
    },
    "email": {
      "smtp_server": "smtp.gmail.com",
      "recipients": ["trader@example.com"]
    },
    "telegram": {
      "bot_token": "${TELEGRAM_BOT_TOKEN}",
      "chat_id": "${TELEGRAM_CHAT_ID}"
    }
  }
}
```

## Automation Hooks

### Pre-Trade Validation Hook
```yaml
# Configuration for pre-trade validation
name: "pre-trade-validation"
trigger: "before_trade_execution"
action: "validate_trade_conditions"
configuration:
  risk_checks:
    - position_size: "max_position_size = 10000"
    - correlation: "max_correlation = 0.7"
    - liquidity: "min_daily_volume = 1000000"
  market_conditions:
    - volatility: "max_volatility = 0.05"
    - volume: "min_volume = 500000"
    - spread: "max_spread = 0.01"
```

### Post-Analysis Notification Hook
```yaml
# Configuration for post-analysis notifications
name: "post-analysis-notification"
trigger: "after_analysis_completion"
action: "send_analysis_alert"
configuration:
  alert_conditions:
    - strong_signals: "confidence > 0.8"
    - high_risk: "risk_score > 70"
    - anomalies: "price_change > 5%"
  notification_channels: ["slack", "email"]
  report_format: "detailed_summary"
```

### System Health Monitoring Hook
```yaml
# Configuration for system health monitoring
name: "system-health-monitor"
trigger: "periodic"
schedule: "*/5 * * * *"  # Every 5 minutes
action: "health_check_and_alert"
configuration:
  checks:
    - api_connectivity: "timeout = 5000ms"
    - data_quality: "min_quality_score = 80"
    - performance: "max_response_time = 2000ms"
  alert_threshold: "warning"
```

## API Integration

### Claude Code to Trading System API
```python
# Claude Code can call these endpoints
import requests

# Analyze symbol
response = requests.post(
    "http://localhost:8000/api/v1/analyze/AAPL",
    json={"analysis_type": "comprehensive_analysis"}
)

# Validate data
response = requests.post(
    "http://localhost:8000/api/v1/validate-data",
    json={"source": "alpha_vantage", "symbol": "AAPL"}
)

# Health check
response = requests.get("http://localhost:8000/api/v1/health/status")
```

### Real-time Data Streaming
```python
# WebSocket integration for real-time data
import websocket

def on_message(ws, message):
    data = json.loads(message)
    # Process real-time market data
    if data["type"] == "market_data":
        # Trigger Claude Code analysis
        claude_integration.handle_real_time_data(data)

ws = websocket.WebSocketApp("ws://localhost:8000/ws/market-data")
ws.on_message = on_message
ws.run_forever()
```

## Performance Optimization

### Caching Strategy
```python
# Configure caching for Claude Code integration
{
  "cache_settings": {
    "market_data": {
      "ttl": 60,  # seconds
      "max_size": 1000
    },
    "analysis_results": {
      "ttl": 300,  # seconds
      "max_size": 500
    },
    "validation_results": {
      "ttl": 120,  # seconds
      "max_size": 200
    }
  }
}
```

### Rate Limiting
```python
# Configure rate limiting for API calls
{
  "rate_limits": {
    "analyze_trading": {
      "requests_per_minute": 10,
      "burst_limit": 3
    },
    "validate_market_data": {
      "requests_per_minute": 20,
      "burst_limit": 5
    },
    "portfolio_health": {
      "requests_per_minute": 5,
      "burst_limit": 2
    }
  }
}
```

## Error Handling and Troubleshooting

### Common Error Scenarios
```python
# Handle API errors gracefully
try:
    result = await integration.handle_analyze_command(params)
except Exception as e:
    error_response = {
        "status": "error",
        "error": str(e),
        "claude_context": {
            "command": "/analyze-trading",
            "error_occurred": True,
            "troubleshooting": {
                "check_api_key": "Verify CLAUDE_API_KEY is set",
                "check_connectivity": "Verify trading system is running",
                "check_parameters": "Verify command parameters are correct"
            }
        }
    }
```

### Debug Mode
```bash
# Enable debug logging
export CLAUDE_DEBUG=true
export TRADING_DEBUG=true

# Run with verbose output
/analyze-trading AAPL --debug --verbose
```

### Health Check Commands
```bash
# Check Claude Code integration
/claude-health-check --trading-integration

# Test MCP connections
/test-mcp --name=trading-data-mcp

# Validate configuration
/validate-config --section=trading-settings
```

## Security and Compliance

### API Key Management
```python
# Secure API key handling
import os
from cryptography.fernet import Fernet

def encrypt_api_key(api_key: str) -> str:
    key = os.environ.get("ENCRYPTION_KEY")
    f = Fernet(key)
    return f.encrypt(api_key.encode()).decode()

def decrypt_api_key(encrypted_key: str) -> str:
    key = os.environ.get("ENCRYPTION_KEY")
    f = Fernet(key)
    return f.decrypt(encrypted_key.encode()).decode()
```

### Trade Validation
```python
# Validate trades before execution
def validate_trade(symbol: str, quantity: int, order_type: str) -> bool:
    checks = [
        validate_symbol(symbol),
        validate_quantity(quantity),
        validate_order_type(order_type),
        validate_risk_limits(symbol, quantity),
        validate_compliance(symbol, order_type)
    ]
    return all(checks)
```

## Monitoring and Analytics

### Claude Code Usage Analytics
```python
# Track Claude Code command usage
analytics = {
    "command_usage": {
        "analyze-trading": 150,
        "validate-market-data": 75,
        "portfolio-health": 30
    },
    "success_rates": {
        "analyze-trading": 0.95,
        "validate-market-data": 0.98,
        "portfolio-health": 1.0
    },
    "average_response_times": {
        "analyze-trading": 2500,  # ms
        "validate-market-data": 800,
        "portfolio-health": 500
    }
}
```

### Performance Metrics
```python
# Monitor system performance
metrics = {
    "cpu_usage": 45.2,  # percent
    "memory_usage": 1024,  # MB
    "active_connections": 12,
    "request_rate": 25.5,  # requests per second
    "error_rate": 0.02  # percent
}
```

## Advanced Features

### Multi-Agent Coordination
```python
# Coordinate multiple Claude Code agents
async def coordinate_analysis(symbols: List[str]):
    tasks = []
    for symbol in symbols:
        task = integration.handle_analyze_command({"symbol": symbol})
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    return aggregate_results(results)
```

### Portfolio Optimization
```python
# Optimize portfolio based on Claude Code analysis
def optimize_portfolio(analysis_results: List[Dict]) -> Dict[str, Any]:
    # Implement portfolio optimization algorithm
    return {
        "optimal_allocation": {...},
        "expected_return": 0.12,
        "risk_score": 35.5,
        "recommendations": [...]
    }
```

### Backtesting Integration
```python
# Backtest strategies against historical data
async def backtest_strategy(strategy: str, period: str) -> Dict[str, Any]:
    # Implement backtesting logic
    return {
        "total_return": 0.25,
        "sharpe_ratio": 1.5,
        "max_drawdown": -0.08,
        "win_rate": 0.65
    }
```

## Best Practices

### Command Usage
1. **Start with health checks**: Always run `/portfolio-health` before trading
2. **Validate data first**: Use `/validate-market-data` before analysis
3. **Monitor performance**: Track command success rates and response times
4. **Use appropriate indicators**: Select relevant indicators for your strategy

### MCP Integration
1. **Secure credentials**: Use environment variables for API keys
2. **Monitor rate limits**: Track API usage to avoid limits
3. **Handle failures**: Implement retry logic for MCP requests
4. **Cache responses**: Cache frequently accessed data

### Automation Hooks
1. **Test hooks thoroughly**: Validate hook logic before deployment
2. **Monitor hook execution**: Track hook success rates and performance
3. **Handle hook failures**: Implement fallback mechanisms
4. **Log hook activities**: Maintain audit trails for compliance

This integration provides a seamless bridge between Claude Code and the production trading system, enabling powerful workflow automation while maintaining enterprise-grade reliability and security.
