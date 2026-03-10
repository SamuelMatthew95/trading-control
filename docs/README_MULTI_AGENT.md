# Multi-Agent Trade Bot - Complete System

## Overview
Production-ready multi-agent trading system with real Claude API calls, comprehensive error handling, and full logging.

## Files Created

### Core System
- `multi_agent_orchestrator.py` - Complete orchestrator with real Claude API calls
- `trade_bot.py` - Simple version (all agents in one file)

### Testing
- `test_multi_agent.py` - Comprehensive test suite covering all scenarios

### Demo & Examples
- `demo_trade_bot.py` - Complete usage examples and batch analysis

## Key Features

### ✅ Real Claude API Integration
- Each agent is a separate Claude API call
- Proper error handling for API failures
- JSON parsing with validation
- Required field checking

### ✅ Multi-Agent Pipeline
- **SIGNAL_AGENT** → Collect and normalize signals
- **CONSENSUS_AGENT** → Build consensus (60% threshold)
- **RISK_AGENT** → Risk management (can veto)
- **SIZING_AGENT** → Kelly criterion position sizing

### ✅ Error Handling & Logging
- Comprehensive error handling for each agent
- Detailed logging to `trade-bot.log`
- Trade history saved to `trade-log.json`
- Performance statistics tracking

### ✅ Production Features
- Risk veto stops pipeline immediately
- Low consensus stops pipeline
- Agent call tracking and audit trail
- Performance metrics and statistics

## Quick Start

### 1. Set API Key
```bash
export ANTHROPIC_API_KEY='your-anthropic-api-key'
```

### 2. Basic Usage
```python
from multi_agent_orchestrator import MultiAgentOrchestrator

orchestrator = MultiAgentOrchestrator(api_key="your-key")
result = orchestrator.analyze_trade("AAPL", "1D", portfolio)
print(result)
```

### 3. Run Demo
```bash
python demo_trade_bot.py
```

### 4. Run Tests
```bash
python test_multi_agent.py
```

## Output Format

Every trade decision returns exactly this format:
```
DECISION: [LONG / SHORT / FLAT / VETO]
ASSET: [ticker]
SIZE: [units] ([% of portfolio])
ENTRY: [price or MARKET]
STOP: [price]
TARGET: [price]
R/R RATIO: [X:1]
CONFIDENCE: [HIGH / MEDIUM / LOW]

SIGNAL SUMMARY:
- Signal Agent: 3 signals collected
- Consensus Agent: 80% agreement for LONG
- Risk Agent: Approved with 1.0x multiplier
- Sizing Agent: Kelly criterion applied

RISK FLAGS:
- [flag]: [action taken]

RATIONALE:
[2-3 sentences on why this trade makes sense]

INVALIDATION:
[What price or condition proves this trade wrong]
```

## Agent Pipeline Rules

1. **Always run in order**: SIGNAL → CONSENSUS → RISK → SIZING
2. **Risk veto is absolute**: If RISK_AGENT returns veto=true, STOP
3. **Low consensus stop**: If CONSENSUS_AGENT returns agreement < 0.50, STOP
4. **Never skip agents**: All agents must complete in order
5. **Complete logging**: Every agent call is logged and tracked

## Testing Coverage

### Unit Tests
- Agent initialization
- JSON parsing validation
- Error handling scenarios
- Decision formatting
- Performance statistics

### Integration Tests
- Complete pipeline success
- Low consensus handling
- Risk veto scenarios
- End-to-end workflow

### Error Scenarios
- API key failures
- JSON parsing errors
- Missing required fields
- Network timeouts

## Performance Metrics

The system tracks:
- Total trades analyzed
- Long/Short/VETO/Flat counts
- Agent success rates
- Trade execution rate
- Error frequency

## Risk Management

### Risk Agent Veto Conditions
- Drawdown > 15%
- Position size > 10% of portfolio
- Insufficient liquidity
- High volatility
- Correlation risks

### Position Sizing
- Kelly criterion with 25% fractional Kelly
- Risk-adjusted position multipliers
- Stop-loss and take-profit calculation
- Risk/reward ratio validation

## Architecture Benefits

### Claude Code Friendly
- Clean, simple structure
- All agents in orchestrator file
- Easy to understand and modify
- No confusing folder hierarchies

### Production Ready
- Real API integration
- Comprehensive error handling
- Full audit trail
- Performance monitoring

### Extensible
- Easy to add new agents
- Simple to modify agent logic
- Clear separation of concerns
- Standardized interfaces

## Next Steps

1. **Set up API key**: Get your Anthropic API key
2. **Run the demo**: See the system in action
3. **Review logs**: Check trade-bot.log for detailed logging
4. **Run tests**: Verify all functionality works
5. **Customize agents**: Modify agent prompts for your strategy

## Support

- Check `trade-bot.log` for detailed system logs
- Review `trade-log.json` for complete trade history
- Run `test_multi_agent.py` for comprehensive testing
- Use `demo_trade_bot.py` for usage examples

**Ready for production trading with Claude multi-agent coordination!** 🚀
