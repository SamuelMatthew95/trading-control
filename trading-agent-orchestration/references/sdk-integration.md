# SDK Integration Guide

## Production Deployment with Claude Agent SDK

This guide explains how to deploy the trading system using the Claude Agent SDK for production-grade programmatic control.

## SDK vs Skills Architecture

### When to Use SDK
- **Production deployments** requiring programmatic control
- **Automated pipelines** and API integration
- **Scale requirements** beyond manual interaction
- **Custom orchestration** logic specific to your use case

### When to Use Skills
- **End-user interaction** via Claude.ai/Claude Code
- **Manual testing** and iteration
- **Knowledge transfer** and modular instructions
- **Portability** across Claude surfaces

## SDK Integration Steps

### 1. Initialize SDK Client
```python
from production_trading_system import ProductionTradingAPI

# Initialize with Claude API key
api = ProductionTradingAPI(claude_api_key="your-production-api-key")
await api.initialize()
```

### 2. Load Skills via SDK
```python
# Skills are loaded programmatically
skills = await api.trading_system.sdk.load_skill("trading-market-data")
skills = await api.trading_system.sdk.load_skill("trading-data-validation")
```

### 3. Execute Workflows
```python
# Programmatic workflow execution
result = await api.analyze_symbol("AAPL", "comprehensive_analysis")
```

## Production Configuration

### Environment Setup
```bash
# Required environment variables
export CLAUDE_API_KEY="your-production-api-key"
export TRADING_SYSTEM_ENV="production"
export OBSERVABILITY_LEVEL="full"
export AGENT_CEILING="5"
```

### Docker Deployment
```dockerfile
FROM python:3.11-slim

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy production system
COPY production_trading_system.py .
COPY trading-*/ ./trading-*/

# Set environment
ENV CLAUDE_API_KEY=${CLAUDE_API_KEY}
ENV TRADING_SYSTEM_ENV=production

# Run production system
CMD ["python", "production_trading_system.py"]
```

### Kubernetes Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trading-system
spec:
  replicas: 3
  selector:
    matchLabels:
      app: trading-system
  template:
    metadata:
      labels:
        app: trading-system
    spec:
      containers:
      - name: trading-system
        image: trading-system:latest
        env:
        - name: CLAUDE_API_KEY
          valueFrom:
            secretKeyRef:
              name: trading-secrets
              key: claude-api-key
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
```

## API Endpoints

### REST API
```python
from fastapi import FastAPI

app = FastAPI()
trading_api = ProductionTradingAPI()

@app.on_event("startup")
async def startup():
    await trading_api.initialize()

@app.post("/api/v1/analyze/{symbol}")
async def analyze_symbol(symbol: str, analysis_type: str = "basic_analysis"):
    return await trading_api.analyze_symbol(symbol, analysis_type)

@app.get("/api/v1/health")
async def health_check():
    return await trading_api.health_check()

@app.get("/api/v1/metrics")
async def system_metrics():
    return await trading_api.get_system_metrics()
```

### GraphQL API
```python
import strawberry

@strawberry.type
class Query:
    @strawberry.field
    async def analyze_symbol(self, symbol: str, analysis_type: str = "basic_analysis") -> dict:
        return await trading_api.analyze_symbol(symbol, analysis_type)
    
    @strawberry.field
    async def system_health(self) -> dict:
        return await trading_api.health_check()

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def execute_workflow(self, workflow_name: str, parameters: dict) -> dict:
        orchestrator = create_trading_orchestrator()
        return await orchestrator.execute_workflow(workflow_name, parameters)

schema = strawberry.Schema(query=Query, mutation=Mutation)
```

## Monitoring and Observability

### Metrics Collection
```python
from prometheus_client import Counter, Histogram, Gauge

# Define metrics
workflow_counter = Counter('trading_workflows_total', 'Total workflows executed')
workflow_duration = Histogram('trading_workflow_duration_seconds', 'Workflow duration')
active_workflows = Gauge('trading_active_workflows', 'Currently active workflows')

# Use in production
@workflow_duration.time()
async def execute_workflow_with_metrics(workflow_name: str, parameters: dict):
    workflow_counter.inc()
    active_workflows.inc()
    try:
        result = await orchestrator.execute_workflow(workflow_name, parameters)
        return result
    finally:
        active_workflows.dec()
```

### Distributed Tracing
```python
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Setup tracing
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

jaeger_exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=6831,
)

span_processor = BatchSpanProcessor(jaeger_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Use in workflows
with tracer.start_as_current_span("execute_workflow") as span:
    span.set_attribute("workflow.name", workflow_name)
    span.set_attribute("workflow.symbol", parameters.get("symbol"))
    result = await orchestrator.execute_workflow(workflow_name, parameters)
    span.set_attribute("workflow.status", result["status"])
```

## Error Handling and Retries

### Resilience Patterns
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError))
)
async def resilient_workflow_execution(workflow_name: str, parameters: dict):
    try:
        return await orchestrator.execute_workflow(workflow_name, parameters)
    except Exception as e:
        logger.error(f"Workflow {workflow_name} failed: {e}")
        raise

# Circuit breaker pattern
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=30)
async def circuit_breaker_workflow(workflow_name: str, parameters: dict):
    return await orchestrator.execute_workflow(workflow_name, parameters)
```

## Security and Authentication

### API Security
```python
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != os.getenv("API_TOKEN"):
        raise HTTPException(status_code=403, detail="Invalid token")
    return credentials

@app.post("/api/v1/analyze/{symbol}")
async def protected_analyze(
    symbol: str, 
    analysis_type: str,
    credentials: HTTPAuthorizationCredentials = Depends(verify_token)
):
    return await trading_api.analyze_symbol(symbol, analysis_type)
```

### Rate Limiting
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

@app.post("/api/v1/analyze/{symbol}")
@limiter.limit("10/minute")
async def rate_limited_analyze(symbol: str, analysis_type: str):
    return await trading_api.analyze_symbol(symbol, analysis_type)
```

## Performance Optimization

### Connection Pooling
```python
import aiohttp
from aiohttp import ClientSession, TCPConnector

# Optimized HTTP client
connector = TCPConnector(
    limit=100,  # Total connection pool size
    limit_per_host=20,  # Per-host connection limit
    keepalive_timeout=30,
    enable_cleanup_closed=True
)

async with ClientSession(connector=connector) as session:
    # Use session for all API calls
    pass
```

### Caching
```python
from functools import lru_cache
import redis

# Redis cache for market data
redis_client = redis.Redis(host='localhost', port=6379, db=0)

@lru_cache(maxsize=1000)
async def cached_market_data(symbol: str):
    cache_key = f"market_data:{symbol}"
    cached = redis_client.get(cache_key)
    
    if cached:
        return json.loads(cached)
    
    data = await fetch_market_data(symbol)
    redis_client.setex(cache_key, 60, json.dumps(data))  # 60 second TTL
    return data
```

## Testing and Validation

### Integration Tests
```python
import pytest
from production_trading_system import ProductionTradingAPI

@pytest.mark.asyncio
async def test_sdk_workflow_execution():
    api = ProductionTradingAPI(claude_api_key="test-key")
    await api.initialize()
    
    result = await api.analyze_symbol("AAPL", "basic_analysis")
    
    assert result["status"] == "completed"
    assert "workflow_id" in result
    assert "result" in result

@pytest.mark.asyncio
async def test_error_handling():
    api = ProductionTradingAPI(claude_api_key="invalid-key")
    
    with pytest.raises(Exception):
        await api.initialize()
```

### Load Testing
```python
import asyncio
from locust import HttpUser, task, between

class TradingSystemUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        # Initialize system
        asyncio.run(self.client.post("/api/v1/initialize"))
    
    @task
    def analyze_symbol(self):
        self.client.post("/api/v1/analyze/AAPL", json={"analysis_type": "basic_analysis"})
```

## Deployment Checklist

- [ ] Claude API key configured
- [ ] Environment variables set
- [ ] Skills loaded and verified
- [ ] Monitoring endpoints configured
- [ ] Error handling and retries implemented
- [ ] Security and authentication configured
- [ ] Rate limiting enabled
- [ ] Performance optimization applied
- [ ] Integration tests passing
- [ ] Load testing completed
- [ ] Observability tracing enabled
- [ ] Health checks configured
