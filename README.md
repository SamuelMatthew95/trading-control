# Trading Control System

## Quick Start

### 1. Run Dashboard
```bash
cd trade-dashboard
streamlit run app.py
```

### 2. Run Enterprise Dashboard
```bash
cd trade-dashboard
streamlit run enterprise_dashboard.py
```

### 3. Run Tests
```bash
python test_comprehensive_system.py
```

## Project Structure

```
trading-control-python/
├── trade-dashboard/          # Main dashboard system
├── skills/trade-bot/        # Claude Skills integration
├── docs/                   # All documentation
├── test_comprehensive_system.py  # Test suite
├── multi_agent_orchestrator.py  # Core system
└── [essential core files...]
```

## Key Components

### Multi-Agent System
- 4 Claude API agents (Signal, Consensus, Risk, Sizing)
- Real-time streaming responses
- Complete trade pipeline

### Dashboard Features
- Standard dashboard with agent panels
- Enterprise dashboard with analytics
- Real-time monitoring and learning system

### Security
- All secrets protected in .gitignore
- No hardcoded API keys
- Comprehensive security tests

## Documentation

See `docs/` folder for detailed documentation:
- System architecture
- API reference
- Deployment guides
- Testing procedures

## Requirements

- Python 3.8+
- streamlit
- anthropic
- plotly
- pandas
- numpy

## License

MIT License
