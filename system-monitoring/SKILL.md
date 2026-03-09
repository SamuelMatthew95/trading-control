---
name: System Monitoring
description: Health monitoring and performance metrics for trading system reliability
---

# System Monitoring Skill

## Overview
The System Monitoring skill provides comprehensive health checking, performance monitoring, and alerting capabilities for the OpenClaw Trading Platform infrastructure.

## Capabilities

### Level 1: High-Level Overview
- System health status monitoring
- Component-level performance tracking
- Automated alert generation
- Historical health trend analysis

### Level 2: Implementation Details
- **Core Component**: `HealthChecker` class
- **Component Checks**: Database, API, Memory, CPU monitoring
- **Alert System**: Multi-level alerts (warning, critical, error)
- **History Tracking**: Rolling 100-check history with trend analysis

### Level 3: Technical Specifications

#### Health Score Calculation
```python
# Component health checks
checks = {
    "database": {"score": 95, "status": "healthy"},
    "api": {"score": 88, "status": "healthy"}, 
    "memory": {"score": 82, "status": "healthy"},
    "cpu": {"score": 79, "status": "degraded"}
}

# Overall health score
overall_score = sum(check["score"] for check in checks.values()) / len(checks)
health_status = "healthy" if overall_score >= 80 else "degraded" if overall_score >= 60 else "unhealthy"
```

#### Alert Generation
```python
alerts = [
    {
        "type": "warning",
        "component": "cpu", 
        "message": "Cpu health degraded: 79%",
        "score": 79
    }
]
```

#### Health History Tracking
```python
{
    "timestamp": "2024-01-15T10:00:00",
    "overall_score": 86,
    "status": "healthy", 
    "checks": {...},
    "alerts": [...]
}
```

## Usage Examples

### Basic Health Check
```python
from system_monitoring.scripts.health_checker import HealthChecker

health_checker = HealthChecker()
health_status = await health_checker.check_system_health()

print(f"Overall Score: {health_status['overall_score']}")
print(f"Status: {health_status['status']}")
print(f"Alerts: {len(health_status['alerts'])}")
```

### Health Summary
```python
summary = health_checker.get_health_summary()
print(f"Current Status: {summary['current_status']}")
print(f"Trend: {summary['recent_trend']}")
print(f"Average Score: {summary['average_score']}")
```

### Alert Monitoring
```python
health_status = await health_checker.check_system_health()
if health_status['alerts']:
    for alert in health_status['alerts']:
        if alert['type'] == 'critical':
            print(f"CRITICAL: {alert['message']}")
        elif alert['type'] == 'warning':
            print(f"WARNING: {alert['message']}")
```

## Component Checks

### Database Health
- Connection pool status
- Response time monitoring
- Query performance metrics

### API Health  
- Endpoint availability
- Response time tracking
- Success rate monitoring

### Memory Health
- Usage percentage
- Available memory
- Memory leak detection

### CPU Health
- Usage percentage
- Load average tracking
- Performance bottlenecks

## Dependencies
- `asyncio` for asynchronous health checks
- `datetime` for timestamp management
- `typing` for type annotations
- `logging` for structured logging

## Performance Characteristics
- **Check Frequency**: Configurable intervals (default: real-time)
- **History Retention**: Last 100 health checks
- **Memory Usage**: Efficient circular buffer for history
- **Response Time**: <50ms for complete health check

## Alert Thresholds
- **Healthy**: Score ≥ 80
- **Degraded**: 60 ≤ Score < 80  
- **Unhealthy**: Score < 60
- **Critical**: Component score < 50

## Integration Points
- **Monitoring Dashboards**: Real-time health visualization
- **Alert Systems**: Email, Slack, PagerDuty integration
- **Logging Systems**: Structured health event logging
- **Auto-scaling**: Health-based scaling decisions

## Configuration
Health check parameters can be customized:
- Check intervals
- Alert thresholds
- Component weights
- History retention policies
