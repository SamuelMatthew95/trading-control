# Trading Control System Documentation

## Quick Reference

### System Overview
- Multi-agent trading system with Claude API integration
- Real-time dashboard with enterprise monitoring
- Learning system for agent performance tracking

### Key Files
- `trade-dashboard/app.py` - Main dashboard
- `trade-dashboard/orchestrator.py` - Claude API pipeline
- `multi_agent_orchestrator.py` - Core system
- `test_essential_system.py` - Test suite

### Running the System
```bash
# Standard dashboard
cd trade-dashboard && streamlit run app.py

# Enterprise dashboard  
cd trade-dashboard && streamlit run enterprise_dashboard.py

# Tests
python test_essential_system.py
```

### Architecture
- 4 Claude API agents (Signal, Consensus, Risk, Sizing)
- Real-time streaming responses
- Complete trade pipeline with risk management

### Security
- Secrets protected in .gitignore
- No hardcoded API keys
- Comprehensive security tests

## Detailed Documentation

- `README_MULTI_AGENT.md` - Multi-agent system details
- `ENTERPRISE_DASHBOARD.md` - Enterprise dashboard guide
- `AGENT_LEARNING_SYSTEM.md` - Learning system documentation
- `HOW_TO_RUN_DASHBOARD.md` - Setup instructions
- `TEST_RESULTS_AND_CLEANUP.md` - Test results and cleanup
- `architecture.md` - System architecture
- `testing.md` - Testing procedures
