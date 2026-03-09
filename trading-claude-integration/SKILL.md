---
name: trading-claude-integration
description: Claude Code template integration for production trading system orchestration. Use when you need to integrate trading system with Claude Code for development workflow automation, slash commands, and MCP integrations like "analyze-trading AAPL" or "validate-market-data --source=alpha_vantage".
---

# Trading Claude Integration

Claude Code template integration for production trading system with slash commands, MCP integrations, and automated workflows.

## Quick Start
```bash
# Install the trading system template
npx claude-code-templates@latest --agent trading-system-orchestrator --yes

# Test the integration
/analyze-trading AAPL --indicators=RSI,MACD,BB
/portfolio-health --detailed
```

## Claude Code Integration

### Agent Definition
```json
{
  "name": "Trading System Orchestrator",
  "capabilities": [
    "Real-time market data analysis",
    "Multi-source data validation", 
    "Technical indicator calculations",
    "Risk assessment and signaling"
  ],
  "skills": [
    "trading-market-data",
    "trading-data-validation", 
    "trading-agent-orchestration",
    "trading-system-monitoring"
  ]
}
```

### Custom Commands

#### Market Analysis
```bash
# Comprehensive technical analysis
/analyze-trading AAPL --indicators=RSI,MACD,BB --timeframe=1d

# Quick analysis with default indicators
/analyze-trading TSLA

# Multiple symbols analysis
/analyze-trading AAPL,MSFT,GOOGL --indicators=RSI
```

#### Data Validation
```bash
# Validate data quality from specific source
/validate-market-data --source=alpha_vantage --symbol=AAPL

# Batch validation
/validate-market-data --source=yahoo_finance --symbols=AAPL,MSFT
```

#### System Health
```bash
# Quick health check
/portfolio-health

# Detailed system metrics
/portfolio-health --detailed
```

## MCP Integrations

### Market Data MCP
```json
{
  "name": "trading-data-mcp",
  "endpoints": [
    "alpha_vantage_market_data",
    "yahoo_finance_stream",
    "polygon_realtime"
  ],
  "rate_limits": {
    "requests_per_minute": 100
  }
}
```

### Portfolio Database MCP
```json
{
  "name": "portfolio-database-mcp",
  "provider": "postgresql",
  "tables": ["trades", "positions", "market_data", "signals"]
}
```

### Notification MCP
```json
{
  "name": "notification-mcp",
  "channels": ["slack", "email", "telegram"],
  "templates": ["trade_alert", "risk_warning"]
}
```

## Automation Hooks

### Pre-Trade Validation
```yaml
trigger: before_trade_execution
action: validate_trade_conditions
checks:
  - position_size
  - correlation
  - liquidity
```

### Post-Analysis Notifications
```yaml
trigger: after_analysis_completion
action: send_analysis_alert
conditions:
  - strong_signals
  - high_risk
  - anomalies
```

### System Health Monitoring
```yaml
trigger: periodic
schedule: "*/5 * * * *"  # Every 5 minutes
action: health_check_and_alert
```

## Configuration Settings

### Performance Optimization
```json
{
  "timeout_ms": 30000,
  "memory_limit_mb": 2048,
  "concurrent_requests": 5,
  "cache_strategy": "lru_with_ttl"
}
```

### Trading Defaults
```json
{
  "default_indicators": ["RSI", "MACD", "BollingerBands"],
  "risk_tolerance": "medium",
  "analysis_timeframe": "1d",
  "data_sources": ["alpha_vantage", "yahoo_finance"]
}
```

## Development Workflow

### 1. Template Installation
```bash
# Install complete trading stack
npx claude-code-templates@latest --agent trading-system-orchestrator --command trading/analyze --mcp trading-data --yes

# Interactive installation
npx claude-code-templates@latest
```

### 2. Environment Setup
```bash
# Required environment variables
export CLAUDE_API_KEY="your-claude-api-key"
export ALPHA_VANTAGE_API_KEY="your-alpha-vantage-key"
export TRADING_DB_URL="postgresql://user:pass@localhost/trading"
export NOTIFICATION_WEBHOOK_URL="https://hooks.slack.com/..."
```

### 3. Daily Trading Workflow
```bash
# Morning market check
/portfolio-health --detailed

# Analyze watchlist
/analyze-trading AAPL,MSFT,GOOGL,TSLA --indicators=RSI,MACD,BB

# Validate data sources
/validate-market-data --source=alpha_vantage --symbols=AAPL,MSFT

# Risk assessment
/portfolio-risk --sector=technology --threshold=medium
```

## Production Integration

### API Endpoints
```python
# Claude Code can call these endpoints automatically
POST /api/v1/analyze/{symbol}
POST /api/v1/validate-data
GET /api/v1/health/status
POST /api/v1/portfolio/optimize
```

### Real-time Monitoring
```python
# Claude Code monitors these metrics
- Market data latency
- Analysis execution time
- System health scores
- Error rates and alerts
```

## Advanced Features

### Multi-Agent Coordination
```bash
# Claude Code orchestrates multiple agents
/coordinate-analysis --symbols=AAPL,MSFT --agents=market_data,validation,analysis
```

### Portfolio Optimization
```bash
# Optimize portfolio based on analysis
/optimize-portfolio --risk-tolerance=medium --sector-balance=true
```

### Backtesting Integration
```bash
# Test strategies against historical data
/backtest-strategy --strategy=RSI_MACD --period=6m --symbols=AAPL
```

## Troubleshooting

### Common Issues
```bash
# Check Claude Code integration status
/claude-health-check --trading-integration

# Verify MCP connections
/test-mcp --name=trading-data-mcp

# Validate configuration
/validate-config --section=trading-settings
```

### Performance Optimization
```bash
# Clear cache and restart
/clear-cache --trading-data
/restart-trading-services

# Monitor performance
/performance-monitor --trading-workflows
```

## Security and Compliance

### API Key Management
```bash
# Rotate API keys securely
/rotate-api-keys --service=alpha_vantage

# Audit access permissions
/audit-permissions --trading-system
```

### Trade Validation
```bash
# Validate trade compliance
/validate-trade --symbol=AAPL --size=100 --type=market

# Check regulatory compliance
/compliance-check --jurisdiction=US --trade-type=equity
```

---
*See [references/claude-integration.md](references/claude-integration.md) for detailed integration guide and [references/mcp-setup.md](references/mcp-setup.md) for MCP configuration.*
