---
name: trading-agent-orchestration
description: Production-grade agent orchestration using Claude Agent SDK for programmatic control. Use when you need to coordinate multiple trading agents, run collaborative analysis, or manage agent workflows like "coordinate the trading agents" or "run the analysis team" with SDK-level reliability.
---

# Trading Agent Orchestration

Production-grade agent orchestration using Claude Agent SDK principles for programmatic control and scalability.

## Quick Start
```python
from trading_agent_orchestration.scripts.sdk_orchestrator import create_trading_orchestrator

# Create SDK-based orchestrator
orchestrator = create_trading_orchestrator(claude_api_key="your-api-key")

# Execute workflow with programmatic control
result = await orchestrator.execute_workflow("technical_analysis", {
    "symbol": "AAPL",
    "indicators": ["RSI", "MACD", "BB"]
})

print(f"Workflow {result['workflow_id']} completed: {result['status']}")
```

## Architecture

### SDK-Based Approach
- **Programmatic Control**: Uses Claude Agent SDK for production deployments
- **Skills Integration**: Leverages modular Skills architecture for knowledge
- **5-Agent Ceiling**: Enforces scalability limits
- **Stateless Agents**: All intelligence in orchestration, agents are dumb workers

### Available Workflows

#### Market Analysis
```python
result = await orchestrator.execute_workflow("market_analysis", {
    "symbol": "AAPL",
    "data_sources": ["alpha_vantage", "yahoo_finance"]
})
```

#### Technical Analysis  
```python
result = await orchestrator.execute_workflow("technical_analysis", {
    "symbol": "AAPL",
    "indicators": ["RSI", "MACD", "BB"],
    "time_period": 14
})
```

#### System Health Monitoring
```python
result = await orchestrator.execute_workflow("health_monitoring", {
    "components": ["database", "api", "memory", "cpu"]
})
```

## Features
- **Production SDK**: Uses Claude Agent SDK for programmatic control
- **Deterministic Workflows**: No LLM-based decision making in production
- **Full Observability**: Complete trace-based debugging
- **5-Agent Ceiling**: Enforced for scalability
- **Strict I/O Contracts**: Pydantic models for all data exchange

## Output Format
```python
{
    "workflow_id": "uuid",
    "workflow_name": "technical_analysis",
    "status": "completed",
    "result": {
        "symbol": "AAPL",
        "signal": "buy",
        "market_data": {...},
        "validation": {...},
        "analysis": {...}
    },
    "skills_used": ["trading-market-data", "trading-data-validation", "trading-technical-analysis"],
    "executed_at": "2024-01-15T10:00:00"
}
```

## Performance Metrics
- **Workflow Duration**: <5 seconds for technical analysis
- **Agent Ceiling**: Maximum 5 concurrent agents
- **Success Rate**: >95% for market data workflows
- **Observability**: Complete trace for every workflow

## Production Deployment

### API Integration
```python
# REST API endpoint
@app.post("/api/trading/analyze")
async def analyze_trading(symbol: str, analysis_type: str):
    orchestrator = create_trading_orchestrator()
    result = await orchestrator.execute_workflow(analysis_type, {"symbol": symbol})
    return result
```

### Monitoring
```python
# Get system status
status = orchestrator.get_system_status()
print(f"Active workflows: {status['supervisor_status']['active_workflows']}")

# Get workflow trace
trace = orchestrator.get_workflow_trace(workflow_id)
print(f"Workflow steps: {len(trace['tasks'])}")
```

## SDK vs Skills Decision

| Use Case | Approach |
|----------|----------|
| **End-user interaction** | Claude.ai/Claude Code with Skills |
| **Production deployment** | SDK with programmatic control |
| **Automated pipelines** | SDK with API integration |
| **Manual testing** | Skills in Claude Code |
| **Scale requirements** | SDK with orchestration logic |

---
*See [references/agent-architecture.md](references/agent-architecture.md) for detailed agent specifications and [references/sdk-integration.md](references/sdk-integration.md) for SDK deployment guidance.*
