---
name: trade-bot
description: >
  Execute automated trading strategies with risk management when asked to 
  run trading bots, analyze market opportunities, or manage portfolio positions.
  Triggered by phrases like "run trading bot", "automated trading", 
  "portfolio management", or "strategy execution".
---

# Trade Bot

## Purpose
Execute automated trading strategies with comprehensive risk management and performance monitoring.

## Steps

### Step 1: Market Analysis
Analyze current market conditions and identify trading opportunities:
- Scan multiple timeframes for setup patterns
- Validate signal strength across indicators
- Check market regime and volatility conditions
- Assess liquidity and market depth

### Step 2: Risk Assessment
Evaluate risk parameters before position entry:
- Calculate position size using risk calculator
- Verify portfolio risk limits are respected
- Set stop-loss and take-profit levels
- Confirm sufficient liquidity for execution

### Step 3: Signal Execution
Execute trading signals with proper risk management:
- Enter positions according to signal strength
- Implement position sizing from risk calculator
- Set automatic exit rules and stops
- Log all trades with complete context

### Step 4: Performance Monitoring
Track and analyze trading performance:
- Monitor position P&L in real-time
- Calculate risk-adjusted returns
- Track win rate and average win/loss ratios
- Generate performance reports

### Step 5: Portfolio Rebalancing
Maintain optimal portfolio composition:
- Assess current portfolio allocations
- Rebalance based on performance and risk
- Adjust position sizes as needed
- Ensure diversification requirements met

## Expected Output
Claude should provide:
- Trading signal analysis with entry/exit points
- Risk-adjusted position sizing recommendations
- Performance metrics and P&L tracking
- Portfolio allocation and rebalancing advice
- Trade execution logs and performance reports

## Notes
- Always prioritize risk management over profit maximization
- Use the risk calculator script for position sizing
- Reference signal weights for signal strength validation
- Monitor performance metrics continuously
- Default to cash position when uncertain
