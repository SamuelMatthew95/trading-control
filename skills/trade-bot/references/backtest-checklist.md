# Backtest Checklist

## Pre-Backtest Preparation

### Data Quality Checklist
- [ ] Historical data covers minimum 2 years
- [ ] Data includes OHLCV (Open, High, Low, Close, Volume)
- [ ] No gaps in data series
- [ ] Adjusted for splits and dividends
- [ ] Timezone consistency maintained
- [ ] Data format validated

### Strategy Definition
- [ ] Entry rules clearly defined
- [ ] Exit rules clearly defined
- [ ] Position sizing rules defined
- [ ] Risk management rules defined
- [ ] Stop loss rules defined
- [ ] Take profit rules defined

## Backtest Execution

### Parameter Settings
- [ ] Initial capital defined (e.g., $100,000)
- [ ] Commission/slippage costs included
- [ ] Position size limits set
- [ ] Maximum drawdown limits set
- [ ] Time period defined (start/end dates)
- [ ] Benchmark selected (e.g., S&P 500)

### Execution Rules
- [ ] Trade execution timing defined (open/close)
- [ ] Order type specified (market/limit)
- [ ] Partial fills considered
- [ ] Liquidity constraints applied
- [ ] Realistic slippage applied (0.05-0.1%)
- [ ] Commission costs applied ($0.005/share)

## Performance Metrics

### Return Metrics
- [ ] Total return calculated
- [ ] Annualized return calculated
- [ ] Monthly returns analyzed
- [ ] Rolling returns analyzed
- [ ] Benchmark comparison
- [ ] Alpha generation measured

### Risk Metrics
- [ ] Maximum drawdown calculated
- [ ] Sharpe ratio calculated
- [ ] Sortino ratio calculated
- [ ] Calmar ratio calculated
- [ ] Volatility measured
- [ ] Beta calculated

### Trade Metrics
- [ ] Total number of trades
- [ ] Win rate calculated
- [ ] Average win/loss calculated
- [ ] Profit factor calculated
- [ ] Average holding period
- [ ] Trade frequency analysis

## Validation Tests

### Statistical Significance
- [ ] Sufficient sample size (>100 trades)
- [ ] P-value calculations
- [ ] Confidence intervals
- [ ] Monte Carlo simulation
- [ ] Bootstrap analysis
- [ ] Outlier impact analysis

### Robustness Tests
- [ ] Parameter sensitivity analysis
- [ ] Walk-forward optimization
- [ ] Out-of-sample testing
- [ ] Different market regimes tested
- [ ] Stress testing scenarios
- [ ] Monte Carlo risk simulation

## Risk Analysis

### Drawdown Analysis
- [ ] Maximum drawdown identified
- [ ] Drawdown duration measured
- [ ] Recovery time calculated
- [ ] Drawdown frequency analyzed
- [ ] Correlation with market drawdowns
- [ ] Stress scenario drawdowns

### Risk-Adjusted Performance
- [ ] Risk-adjusted returns calculated
- [ ] Risk per trade measured
- [ ] Portfolio risk analyzed
- [ ] Correlation with market
- [ ] Value at Risk (VaR) calculated
- [ ] Expected Shortfall measured

## Reporting Requirements

### Performance Report
- [ ] Equity curve chart
- [ ] Drawdown chart
- [ ] Monthly returns heatmap
- [ ] Trade distribution analysis
- [ ] Risk-return scatter plot
- [ ] Benchmark comparison chart

### Statistics Summary
- [ ] Key performance metrics table
- [ ] Risk metrics summary
- [ ] Trade statistics summary
- [ ] Monthly performance table
- [ ] Annual performance table
- [ ] Regime-specific performance

## Validation Criteria

### Minimum Performance Standards
- [ ] Sharpe ratio > 1.0
- [ ] Maximum drawdown < 25%
- [ ] Win rate > 45%
- [ ] Profit factor > 1.5
- [ ] Annualized return > 10%
- [ ] Positive alpha vs benchmark

### Risk Limits
- [ ] No single loss > 10% of portfolio
- [ ] Maximum drawdown < 25%
- [ ] Daily VaR < 5%
- [ ] Correlation with market < 0.8
- [ ] Maximum position size < 20%
- [ ] Sector concentration < 30%

## Common Pitfalls to Avoid

### Data Issues
- [ ] No look-ahead bias
- [ ] No survivorship bias
- [ ] No data snooping
- [ ] Proper out-of-sample testing
- [ ] Realistic transaction costs
- [ ] Proper handling of corporate actions

### Strategy Issues
- [ ] No overfitting to historical data
- [ ] No curve fitting parameters
- [ ] Robust to parameter changes
- [ ] Works across market regimes
- [ ] Reasonable number of trades
- [ ] No excessive complexity

## Post-Backtest Actions

### Implementation Planning
- [ ] Paper trading plan created
- [ ] Live trading criteria defined
- [ ] Monitoring systems set up
- [ ] Alert thresholds established
- [ ] Review schedule defined
- [ ] Performance tracking system

### Documentation
- [ ] Strategy documentation complete
- [ ] Backtest methodology documented
- [ ] Risk management procedures documented
- [ ] Performance attribution analysis
- [ ] Lessons learned documented
- [ ] Future improvement plan

## Final Validation

### Go/No-Go Criteria
- [ ] All performance criteria met
- [ ] Risk limits respected
- [ ] Statistical significance confirmed
- [ ] Robustness tests passed
- [ ] Implementation feasibility confirmed
- [ ] Risk management validated

### Approval Checklist
- [ ] Strategy approved by risk team
- [ ] Backtest reviewed by quant team
- [ ] Implementation plan approved
- [ ] Monitoring systems tested
- [ ] Documentation complete
- [ ] Go-live decision made
