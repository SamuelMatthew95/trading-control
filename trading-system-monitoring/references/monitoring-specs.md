# Monitoring Specifications

## Health Check Implementation

### Database Monitoring
```python
async def _check_database_health(self) -> Dict[str, Any]:
    """Check database connectivity and performance"""
    # Connection pool metrics
    active_connections = get_active_connections()
    total_connections = get_total_connections()
    idle_connections = total_connections - active_connections
    
    # Query performance
    response_time = measure_query_time("SELECT 1")
    
    # Calculate health score
    score = min(100, max(0, 100 - (response_time - 25) * 2))
    
    return {
        "score": score,
        "status": "healthy" if score >= 80 else "degraded" if score >= 60 else "unhealthy",
        "response_time_ms": response_time,
        "connection_pool": {
            "active": active_connections,
            "idle": idle_connections,
            "total": total_connections
        }
    }
```

### API Monitoring
```python
async def _check_api_health(self) -> Dict[str, Any]:
    """Check API endpoints and response times"""
    endpoints = [
        "/api/health",
        "/api/data/status",
        "/api/agents/status"
    ]
    
    total_response_time = 0
    successful_endpoints = 0
    
    for endpoint in endpoints:
        start_time = time.time()
        try:
            response = await make_request("GET", endpoint)
            if response.status == 200:
                successful_endpoints += 1
            total_response_time += (time.time() - start_time) * 1000
        except Exception:
            pass
    
    avg_response_time = total_response_time / len(endpoints)
    success_rate = successful_endpoints / len(endpoints)
    
    score = min(100, max(0, 100 - (avg_response_time - 100) * 0.5))
    
    return {
        "score": score,
        "status": "healthy" if score >= 80 else "degraded" if score >= 60 else "unhealthy",
        "response_time_ms": avg_response_time,
        "endpoints_checked": len(endpoints),
        "success_rate": success_rate
    }
```

### Memory Monitoring
```python
async def _check_memory_health(self) -> Dict[str, Any]:
    """Check memory usage and availability"""
    import psutil
    
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    usage_percent = memory.percent
    available_gb = memory.available / (1024**3)
    total_gb = memory.total / (1024**3)
    
    # Score based on usage percentage
    if usage_percent < 70:
        score = 100
    elif usage_percent < 85:
        score = 100 - (usage_percent - 70) * 2
    else:
        score = 50 - (usage_percent - 85) * 3
    
    return {
        "score": max(0, score),
        "status": "healthy" if score >= 80 else "degraded" if score >= 60 else "unhealthy",
        "usage_percent": usage_percent,
        "available_gb": round(available_gb, 2),
        "total_gb": round(total_gb, 2),
        "swap_usage_percent": swap.percent
    }
```

### CPU Monitoring
```python
async def _check_cpu_health(self) -> Dict[str, Any]:
    """Check CPU usage and performance"""
    import psutil
    
    cpu_percent = psutil.cpu_percent(interval=1)
    load_avg = psutil.getloadavg()
    
    # Score based on CPU usage
    if cpu_percent < 60:
        score = 100
    elif cpu_percent < 80:
        score = 100 - (cpu_percent - 60) * 2
    else:
        score = 60 - (cpu_percent - 80) * 2
    
    return {
        "score": max(0, score),
        "status": "healthy" if score >= 80 else "degraded" if score >= 60 else "unhealthy",
        "usage_percent": cpu_percent,
        "load_average": list(load_avg),
        "core_count": psutil.cpu_count()
    }
```

## Alert Generation Logic

### Alert Classification
```python
def _generate_alerts(self, checks: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate alerts based on health check results"""
    alerts = []
    
    for component, check in checks.items():
        score = check["score"]
        
        if score < 50:
            alert_type = "critical"
            message = f"{component.title()} critical: {score}%"
        elif score < 70:
            alert_type = "warning"
            message = f"{component.title()} degraded: {score}%"
        elif score < 85:
            alert_type = "info"
            message = f"{component.title()} attention: {score}%"
        else:
            continue
        
        alerts.append({
            "type": alert_type,
            "component": component,
            "message": message,
            "score": score,
            "timestamp": datetime.now().isoformat()
        })
    
    return alerts
```

## Performance Metrics

### Response Time Benchmarks
| Component | Target | Warning | Critical |
|-----------|--------|---------|----------|
| Database | <25ms | 25-50ms | >50ms |
| API | <100ms | 100-200ms | >200ms |
| Memory | <70% | 70-85% | >85% |
| CPU | <60% | 60-80% | >80% |

### History Management
```python
class HealthHistory:
    def __init__(self, max_size: int = 100):
        self.history: List[Dict[str, Any]] = []
        self.max_size = max_size
    
    def add_check(self, health_result: Dict[str, Any]):
        """Add health check result to history"""
        self.history.append(health_result)
        if len(self.history) > self.max_size:
            self.history.pop(0)
    
    def get_trend(self, window_size: int = 10) -> str:
        """Calculate trend over recent window"""
        if len(self.history) < window_size:
            return "insufficient_data"
        
        recent_scores = [check["overall_score"] for check in self.history[-window_size:]]
        first_avg = sum(recent_scores[:3]) / 3
        last_avg = sum(recent_scores[-3:]) / 3
        
        if last_avg > first_avg + 5:
            return "improving"
        elif last_avg < first_avg - 5:
            return "declining"
        else:
            return "stable"
```

## Configuration Options

### Check Intervals
```python
monitoring_config = {
    "health_check_interval": 30,  # seconds
    "alert_cooldown": 300,       # seconds
    "history_retention": 100,     # checks
    "performance_thresholds": {
        "database": {"target": 25, "warning": 50, "critical": 100},
        "api": {"target": 100, "warning": 200, "critical": 500},
        "memory": {"target": 70, "warning": 85, "critical": 95},
        "cpu": {"target": 60, "warning": 80, "critical": 90}
    }
}
```

### Alert Routing
```python
alert_config = {
    "critical": ["email", "slack", "pagerduty"],
    "warning": ["email", "slack"],
    "info": ["slack"]
}
```
