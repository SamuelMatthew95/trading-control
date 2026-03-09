# Production Trading System

A production-grade trading system built with Claude Agent SDK integration, featuring high-scale agent architecture, comprehensive observability, and Claude Code template integration.

## Architecture

### Core Components

- **Production Trading System** (`production_trading_system.py`) - Main SDK-based system
- **Agent Orchestration** (`trading-agent-orchestration/`) - Supervisor/worker pattern with 5-agent ceiling
- **Market Data** (`trading-market-data/`) - Real-time market data collection
- **Data Validation** (`trading-data-validation/`) - Field validation and quality checks
- **System Monitoring** (`trading-system-monitoring/`) - Health monitoring and performance metrics
- **Claude Integration** (`trading-claude-integration/`) - Claude Code template integration

### Skills Architecture

The system follows Claude Skills architecture with modular, self-contained skills:

```
trading-market-data/          # Real-time stock quotes
├── SKILL.md                  # Skill definition with YAML frontmatter
├── scripts/market_data.py    # GetStockQuote implementation
├── references/api-documentation.md
└── tests/test_skill.py

trading-data-validation/       # Field validation
├── SKILL.md
├── scripts/field_validator.py
├── references/validation-rules.md
└── tests/test_skill.py

trading-agent-orchestration/   # Multi-agent coordination
├── SKILL.md
├── scripts/
│   ├── agents/               # Stateless worker agents
│   ├── sdk_orchestrator.py   # SDK-based orchestration
│   ├── supervisor_orchestrator.py
│   └── observability.py     # Trace-based monitoring
├── references/agent-architecture.md
└── references/sdk-integration.md

trading-system-monitoring/     # Health monitoring
├── SKILL.md
├── scripts/health_checker.py
├── references/monitoring-specs.md
└── tests/test_skill.py

trading-claude-integration/    # Claude Code templates
├── SKILL.md
├── scripts/claude_integration.py
├── references/claude-integration.md
└── assets/
```

## Quick Start

### Production Deployment
```python
from production_trading_system import ProductionTradingAPI

# Initialize system
api = ProductionTradingAPI(claude_api_key="your-api-key")
await api.initialize()

# Execute analysis
result = await api.analyze_symbol("AAPL", "comprehensive_analysis")
print(f"Analysis completed: {result['workflow_id']}")
```

### Claude Code Integration
```bash
# Install Claude Code template
npx claude-code-templates@latest --agent trading-system-orchestrator --yes

# Use slash commands
/analyze-trading AAPL --indicators=RSI,MACD,BB
/portfolio-health --detailed
```

## Key Features

### Production-Grade Architecture
- **5-Agent Ceiling**: Enforced scalability limits
- **Stateless Agents**: All intelligence in orchestration
- **Strict I/O Contracts**: Pydantic models for all data exchange
- **Trace-Based Observability**: Complete debugging and monitoring

### Claude Agent SDK Integration
- **Programmatic Control**: SDK for production deployments
- **Skills Architecture**: Modular knowledge for portability
- **MCP Integrations**: External service connections
- **Automation Hooks**: Pre/post execution workflows

### Enterprise Compliance
- **AGENTS.md Governance**: Strict compliance rules
- **Security**: API key management and permissions
- **Performance**: Caching, rate limiting, optimization
- **Monitoring**: Real-time metrics and alerting

## Configuration

### Environment Variables
```bash
export CLAUDE_API_KEY="your-claude-api-key"
export ALPHA_VANTAGE_API_KEY="your-alpha-vantage-key"
export TRADING_DB_URL="postgresql://user:pass@localhost/trading"
export NOTIFICATION_WEBHOOK_URL="https://hooks.slack.com/..."
```

### System Settings
```python
# Performance settings
TRADING_TIMEOUT_MS=30000
TRADING_MEMORY_LIMIT_MB=2048
TRADING_CACHE_TTL=3600

# Agent limits
AGENT_CEILING=5
MAX_CONCURRENT_WORKFLOWS=10
```

## Documentation

- **AGENTS.md** - Production-grade agent governance constitution
- **trading-*/SKILL.md** - Individual skill documentation
- **trading-*/references/** - Detailed technical specifications
- **trading-claude-integration/references/claude-integration.md** - Claude Code integration guide

## Development vs Production

| Use Case | Approach |
|----------|----------|
| **End-user interaction** | Claude.ai/Claude Code + Skills |
| **Production deployment** | SDK + Programmatic Control |
| **Automated pipelines** | SDK + API Integration |
| **Manual testing** | Skills in Claude Code |
| **Scale requirements** | SDK with orchestration logic |

## License

MIT License - see LICENSE file for details.
