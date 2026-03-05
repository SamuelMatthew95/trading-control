# Trading Control Platform - AI Agent Infrastructure

Production-ready AI agent orchestration platform with Mission Control integration, Langfuse observability, and comprehensive monitoring.

## Architecture Overview

This platform integrates **Python AI agents** with **Mission Control** (the open-source agent orchestration dashboard) and **Langfuse** (LLM observability) for complete agent lifecycle management.

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Mission Control  │    │   Python Agents  │    │    Langfuse     │    │   FastAPI       │
│  (Dashboard)      │    │   (Intelligence)  │    │   (Tracing)     │    │   (API)         │
│  (Next.js App)    │    │   (Our Code)     │    │   (External)    │    │   (Gateway)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
         │                   │                   │                   │
         │ 1. Monitor       │ 2. Agent Logic    │ 3. LLM Calls     │ 4. REST API     │
         │ 2. Configure     │ 5. Emit Events    │ 6. Trace Data    │ 7. Task Queue   │
         │ 3. Alert         │ 6. Status Updates │ 7. Evaluation   │ 8. Orchestration │
         │                   │                   │                   │                   │
         └───────────────────┘───────────────────┘───────────────────┘───────────────────┘
```

## What This System Does

### Python Agents
- **TechnicalAnalystAgent**: Technical analysis with RSI, MACD, Bollinger Bands
- **BusinessAnalystAgent**: Fundamental analysis with P/E ratios, DCF valuation
- **SentimentAnalystAgent**: News and social media sentiment analysis

### Mission Control Integration
- **Agent Management**: Monitor agent status, heartbeats, and lifecycle
- **Task Board**: Kanban board with drag-and-drop task management
- **Real-time Monitoring**: Live activity feed and log viewer
- **Cost Tracking**: Token usage and cost analysis from Langfuse
- **Quality Gates**: Task sign-off workflows and review processes

### Langfuse Observability
- **Complete Tracing**: Every agent execution creates a Langfuse trace
- **Token Tracking**: Monitor LLM usage and costs per agent
- **Performance Metrics**: Execution time and success rates
- **Quality Evaluation**: Automated scoring of agent results

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+ (for Mission Control)
- pnpm package manager

### 1. Setup Mission Control
```bash
# Clone Mission Control
git clone https://github.com/builderz-labs/mission-control.git
cd mission-control

# Install dependencies
npm install -g pnpm
pnpm install

# Configure environment
cp .env.example .env
# Edit .env with your values

# Start Mission Control
pnpm dev
# Runs on http://localhost:3000
```

### 2. Setup Python Platform
```bash
# Clone this repository
git clone <repository-url>
cd trading-control-python

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Mission Control and Langfuse keys

# Start the platform
python main.py
# Runs on http://localhost:8000
```

### 3. Verify Integration
```bash
# Check Mission Control dashboard
open http://localhost:3000
# You should see Python agents in the Agents panel

# Check Python API
curl http://localhost:8000/health
curl http://localhost:8000/
```

## Configuration

### Environment Variables
```bash
# Application Settings
HOST=0.0.0.0
PORT=8000
DEBUG=true
ENVIRONMENT=development

# Mission Control Integration
MISSION_CONTROL_HOST=localhost
MISSION_CONTROL_PORT=3000
MISSION_CONTROL_API_KEY=your_mission_control_api_key

# Langfuse Integration
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com

# Agent Configuration
AGENT_REGISTRY_PATH=/agents
AGENT_TIMEOUT_SECONDS=300
MAX_CONCURRENT_AGENTS=10

# Observability
EVENT_BATCH_SIZE=100
METRICS_RETENTION_DAYS=30
TRACE_SAMPLE_RATE=1.0
```

### Mission Control Setup
In Mission Control's `.env`:
```bash
# Gateway Configuration
OPENCLAW_GATEWAY_HOST=localhost
OPENCLAW_GATEWAY_PORT=8000
OPENCLAW_GATEWAY_TOKEN=your_gateway_token

# Agent Memory Directory
OPENCLAW_MEMORY_DIR=/path/to/agents

# Authentication
AUTH_USER=admin
AUTH_PASS=your_secure_password
API_KEY=your_api_key
```

## API Endpoints

### Core Platform Endpoints
```bash
GET  /health                    # Health check
GET  /                         # System information
GET  /docs                     # API documentation
```

### Gateway Endpoints
```bash
POST /gateway/v1/agents/{agent_id}/tasks     # Submit tasks to agents
GET  /gateway/v1/agents/{agent_id}/status    # Get agent status
GET  /gateway/v1/agents                      # List all agents
POST /gateway/v1/agents/{agent_id}/register   # Register new agent
DELETE /gateway/v1/agents/{agent_id}          # Unregister agent
DELETE /gateway/v1/tasks/{task_id}            # Cancel task
GET  /gateway/v1/system/status               # System status
GET  /gateway/v1/health                      # Gateway health
```

## Agent Usage Examples

### Submit Technical Analysis Task
```bash
curl -X POST "http://localhost:8000/gateway/v1/agents/builtin_technical_analyst_1/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "analyze_symbol",
    "input_data": {
      "symbol": "AAPL",
      "price_data": {
        "prices": [150, 152, 151, 153, 155],
        "volumes": [1000000, 1200000, 900000, 1500000, 1100000]
      },
      "indicators": ["rsi", "macd", "bollinger"]
    }
  }'
```

### Submit Business Analysis Task
```bash
curl -X POST "http://localhost:8000/gateway/v1/agents/builtin_business_analyst_1/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "valuation",
    "input_data": {
      "symbol": "AAPL",
      "financial_data": {
        "revenue": 365817000000,
        "net_income": 94680000000,
        "total_debt": 119000000000,
        "total_equity": 201000000000
      },
      "metrics": ["pe_ratio", "roe", "debt_to_equity"]
    }
  }'
```

### Submit Sentiment Analysis Task
```bash
curl -X POST "http://localhost:8000/gateway/v1/agents/builtin_sentiment_analyst_1/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "analyze_sentiment",
    "input_data": {
      "symbol": "AAPL",
      "text_data": {
        "articles": [
          {
            "title": "Apple beats earnings expectations",
            "content": "Apple reported strong quarterly earnings"
          }
        ],
        "posts": [
          {
            "content": "Bullish on AAPL! Great technical indicators",
            "likes": 150
          }
        ]
      },
      "sources": ["news", "social"]
    }
  }'
```

## What You'll See in Mission Control

### Agent Management Panel
- **Registered Agents**: Technical Analyst, Business Analyst, Sentiment Analyst
- **Real-time Status**: Active, idle, error states
- **Performance Metrics**: Tasks completed, error rates, execution times
- **Heartbeat Monitoring**: Live agent health checks

### Task Board
- **Kanban Columns**: Inbox → Backlog → Todo → In-Progress → Review → Done
- **Task Cards**: Agent tasks with priority and status
- **Drag-and-Drop**: Move tasks between columns
- **Comments & Assignments**: Collaborative task management

### Real-time Monitoring
- **Activity Feed**: Live stream of agent events
- **Log Viewer**: Filtered agent execution logs
- **Session Inspector**: Detailed task execution traces
- **WebSocket Updates**: Real-time status changes

### Cost Tracking
- **Token Usage**: Per-agent and per-model breakdowns
- **Cost Analysis**: Monthly and cumulative costs
- **Trend Charts**: Usage patterns over time
- **Budget Alerts**: Cost threshold notifications

## Testing

### Run All Tests
```bash
# Run complete test suite with coverage
pytest --cov=. --cov-fail-under=80 --junitxml=test-results.xml

# Run specific test categories
pytest -m unit                    # Fast unit tests
pytest -m integration            # Integration tests
pytest -m performance            # Performance benchmarks
pytest -m edge_case              # Edge case tests
```

### Test Coverage
```bash
# Generate coverage report
pytest --cov=. --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Performance Tests
```bash
# Run performance benchmarks
pytest -m performance -v

# Run with profiling
pytest -m performance --profile
```

## Development

### Code Quality
```bash
# Format code
black .
isort .

# Type checking
mypy .

# Linting
flake8 .

# Security analysis
bandit -r .
```

### Pre-commit Hooks
```bash
# Install pre-commit hooks
pre-commit install

# Run all checks
pre-commit run --all-files
```

## Models and Services

### Built-in Agents
- **TechnicalAnalystAgent**: RSI, MACD, Bollinger Bands, Moving Averages
- **BusinessAnalystAgent**: P/E ratios, DCF valuation, fundamental metrics
- **SentimentAnalystAgent**: News sentiment, social media analysis

### Observability Components
- **LangfuseObservability**: LLM call tracing and evaluation
- **MissionControlClient**: Structured event emission
- **ObservabilityManager**: Centralized tracking coordination

### Gateway Components
- **OpenClawGateway**: Agent lifecycle and task orchestration
- **AgentEndpoints**: REST API for external integration
- **TaskManager**: Background task management

## Architecture Principles

### Clean Separation
- **Agent Layer**: Pure business logic, no external dependencies
- **Observability Layer**: Tracing and monitoring, no business logic
- **Gateway Layer**: Orchestration and API, no agent logic

### Type Safety
- **Full Type Hints**: All functions and classes typed
- **Data Validation**: Pydantic models for all data structures
- **Error Handling**: Specific exception types with context

### Observability First
- **Every Execution Traced**: Langfuse traces for all agent runs
- **Structured Events**: Mission Control events for monitoring
- **Performance Metrics**: Execution time and resource usage

### Production Ready
- **Environment Configuration**: Development and production configs
- **Error Handling**: Graceful degradation and recovery
- **Monitoring**: Health checks and system metrics

## Deployment

### Development
```bash
# Use development configuration
cp .env.example .env
# Edit with development values
python main.py
```

### Production
```bash
# Use production configuration
cp .env.prod .env
# Edit with production values
python main.py
```

### Docker Deployment
```bash
# Build image
docker build -t trading-control-platform .

# Run container
docker run -p 8000:8000 -e ENVIRONMENT=production trading-control-platform
```

## Troubleshooting

### Common Issues

**Mission Control Not Connecting**
```bash
# Check Mission Control is running
curl http://localhost:3000/health

# Check API key configuration
grep MISSION_CONTROL_API_KEY .env
```

**Agents Not Registering**
```bash
# Check gateway logs
python main.py

# Verify Mission Control configuration
curl http://localhost:3000/api/agents
```

**Langfuse Tracing Not Working**
```bash
# Check Langfuse configuration
grep LANGFUSE_ .env

# Verify Langfuse connectivity
curl -H "Authorization: Bearer $LANGFUSE_PUBLIC_KEY" \
     https://cloud.langfuse.com/api/public/traces
```

### Debug Mode
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python main.py
```

## Contributing

1. **Fork** the repository
2. **Create** a feature branch
3. **Add tests** for new functionality
4. **Ensure** all tests pass and coverage is maintained
5. **Submit** a pull request

## License

MIT License - see LICENSE file for details.

## Support

- **Documentation**: [README.md](README.md)
- **Issues**: [GitHub Issues](https://github.com/your-org/trading-control-platform/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/trading-control-platform/discussions)

---

**Built with professional Python engineering standards, comprehensive testing, and production-ready observability.**
