---
name: trading-system-monitoring
description: Health monitoring and performance metrics for trading system reliability. Use when you need to check system health, monitor performance, or track system status like "check system health" or "how is the trading system performing".
---

# Trading System Monitoring

Comprehensive health checking and performance monitoring for trading infrastructure.

## Quick Start
```python
from trading_system_monitoring.scripts.health_checker import HealthChecker

health_checker = HealthChecker()
health_status = await health_checker.check_system_health()

print(f"Overall Score: {health_status['overall_score']}")
print(f"Status: {health_status['status']}")
if health_status['alerts']:
    print(f"Alerts: {len(health_status['alerts'])}")
```

## Features
- **Component health checking** (database, API, memory, CPU)
- **Automated alerting** with multi-level severity
- **Historical tracking** with trend analysis
- **Performance metrics** collection

## Health Score Calculation
- **Healthy**: Score greater than or equal to 80
- **Degraded**: 60 less than or equal to Score less than 80  
- **Unhealthy**: Score less than 60
- **Critical**: Component score less than 50

## Monitored Components
- **Database**: Connection pool, response time, query performance
- **API**: Endpoint availability, success rate, response times
- **Memory**: Usage percentage, available memory, leak detection
- **CPU**: Usage percentage, load average, bottlenecks

## Output Format
```python
{
    "timestamp": "2024-01-15T10:00:00",
    "overall_score": 86,
    "status": "healthy",
    "checks": {
        "database": {"score": 95, "status": "healthy"},
        "api": {"score": 88, "status": "healthy"},
        "memory": {"score": 82, "status": "healthy"},
        "cpu": {"score": 79, "status": "degraded"}
    },
    "alerts": [...]
}
```

## Alert Types
- **Critical**: Immediate attention required
- **Warning**: Monitor closely
- **Info**: Informational only

## Performance Tracking
- **History**: Last 100 health checks
- **Trends**: Improving, declining, or stable
- **Baselines**: Performance comparison over time

---
*See [references/monitoring-specs.md](references/monitoring-specs.md) for detailed monitoring specifications.*
