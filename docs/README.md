# Trading System

Production-grade trading system with intelligent agents, stateful logging, and collaborative learning.

## Project Structure

```
trading-control-python/
├── src/                          # Main source code
│   ├── core/                      # Core utilities and logging
│   │   ├── stateful_logging_system.py
│   │   ├── config.py
│   │   ├── logger.py
│   │   ├── models.py
│   │   └── main.py
│   ├── agents/                    # Agent implementations
│   │   ├── deterministic_trading_system.py
│   │   └── intelligent_learning_system.py
│   ├── system/                    # System orchestration
│   │   ├── professional_trading_orchestrator.py
│   │   ├── production_trading_system.py
│   │   └── claude_code_template.py
│   └── tests/                     # Test suite
│       └── test_trading_system.py
├── trading-*/                      # Skills (Claude Code integration)
│   ├── trading-market-data/
│   ├── trading-data-validation/
│   ├── trading-agent-orchestration/
│   ├── trading-system-monitoring/
│   ├── trading-professional-orchestrator/
│   ├── trading-deterministic-system/
│   ├── trading-claude-integration/
│   └── trading-intelligent-learning/
├── tests/                          # Test documentation
│   └── test_guide.md
├── AGENTS.md                       # Agent governance
├── README.md                       # Project documentation
└── pyproject.toml                  # Project configuration
```

## Quick Start

### Core System
```python
from src.core import create_stateful_logging_system
from src.system import create_professional_orchestrator
from src.agents import create_intelligent_learning_system

# Initialize logging
db_manager, logger, test_manager = create_stateful_logging_system()

# Create orchestrator
orchestrator = create_professional_orchestrator()

# Create learning system
learning_manager, team_manager, database = create_intelligent_learning_system()
```

### Production API
```python
from src.system import ProductionTradingAPI

# Initialize production system
api = ProductionTradingAPI(claude_api_key="your-key")
await api.initialize()

# Execute analysis
result = await api.analyze_symbol("AAPL", "comprehensive_analysis")
```

### Agent System
```python
from src.agents import create_deterministic_trading_system

# Create agent system
system = create_deterministic_trading_system()

# Register and execute agents
result = await system.execute_agent_task("data_analyst", "analyze", {"symbol": "AAPL"})
```

## Architecture

### Core Components
- **Stateful Logging**: Database-backed logging with enums and history tables
- **Agent System**: Deterministic agents with learning and communication
- **Orchestration**: State-machine-based professional orchestrator
- **Production API**: Claude SDK integration for production deployment

### Skills Integration
- **Trading Skills**: Modular skills for Claude Code integration
- **Learning Skills**: Intelligent learning and mistake analysis
- **Professional Skills**: State-machine orchestration patterns

### Testing
- **Comprehensive Tests**: Full test coverage with database persistence
- **Integration Tests**: End-to-end workflow testing
- **Performance Tests**: Load and stress testing

## Development

### Running Tests
```bash
# Run all tests
python -m pytest src/tests/

# Run with coverage
python -m pytest src/tests/ --cov=src

# Run specific test class
python -m pytest src/tests/test_trading_system.py::TestStatefulLoggingSystem
```

### Development Setup
```bash
# Install development dependencies
pip install -e .

# Run with development configuration
export TRADING_ENV=development
python -m src.core.main
```

## Documentation

- **[AGENTS.md](AGENTS.md)**: Agent governance constitution
- **[tests/test_guide.md](tests/test_guide.md)**: Comprehensive test guide
- **Trading Skills**: Each `trading-*/SKILL.md` contains skill documentation

## Production Deployment

### Environment Setup
```bash
export CLAUDE_API_KEY="your-claude-api-key"
export ALPHA_VANTAGE_API_KEY="your-alpha-vantage-key"
export TRADING_DB_PATH="/path/to/production.db"
export TRADING_ENV="production"
```

### Docker Deployment
```dockerfile
FROM python:3.11-slim
COPY . /app
WORKDIR /app
RUN pip install -e .
CMD ["python", "-m", "src.system.production_trading_system"]
```

## Architecture Principles

1. **Stateful Design**: All state persisted in database tables
2. **Enum-Based Measurements**: No magic numbers, use enums for all metrics
3. **Deterministic Behavior**: No randomness, predictable outcomes
4. **Intelligent Learning**: Agents understand mistakes and collaborate
5. **Professional Orchestration**: State-machine based with safety protocols

## License

MIT License - see LICENSE file for details.
