# Trade Bot - Clean Claude Code Structure

## Overview
Simple, clean multi-agent trade bot system designed for Claude Code.

## Files
- `trade_bot.py` - Main orchestrator and all agents in one file
- `skills/trade-bot/` - Claude Skill for user interaction

## Usage

```python
from trade_bot import TradeBotOrchestrator

# Initialize
orchestrator = TradeBotOrchestrator()

# Analyze trade
result = orchestrator.analyze_trade("AAPL", "1D", portfolio_state)
```

## Agent Structure
1. **SignalAgent** - Collect signals
2. **ConsensusAgent** - Build consensus  
3. **RiskAgent** - Risk management
4. **SizingAgent** - Position sizing

## Output Format
Returns exactly the format you specified for consistency.

## Clean Structure Benefits
- No confusing folder hierarchies
- All agents in one file
- Easy to understand and modify
- Claude Code friendly
- No random folders or files
