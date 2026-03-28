# Trading Control

Trading Control is an event-driven trading orchestration platform with:

- a FastAPI backend for control and telemetry APIs,
- a Redis Streams pipeline for internal event flow, and
- an optional Next.js dashboard for operational visibility.

It is designed for deterministic local development, integration testing, and production-style runtime behavior.

## Documentation

- Architecture: https://matthew.docs.buildwithfern.com/docs/system-design/architecture
- API Reference: https://matthew.docs.buildwithfern.com/api-reference/api-reference/

## Quick Start

### 1) Prerequisites

- Python 3.10+
- pip
- (Optional for full runtime) PostgreSQL + Redis

### 2) Install

```bash
git clone https://github.com/SamuelMatthew95/trading-control.git
cd trading-control
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3) Configure environment

```bash
cp .env.example .env
```

Typical values:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/trading_control
REDIS_URL=redis://localhost:6379/0
ENABLE_SIGNAL_SCHEDULER=false
LOG_LEVEL=INFO
```

### 4) Run the API

```bash
uvicorn api.main:app --reload
```

### 5) Run tests

```bash
pytest
```

## Repository Layout

```text
trading-control/
├── api/                     # FastAPI app, services, event pipeline, persistence
├── docs/                    # Architecture, deployment, and contributor docs
├── frontend/                # Optional Next.js operator dashboard
├── scripts/                 # Operational and validation helper scripts
├── tests/                   # Unit, API, and integration test suites
├── fakeredis/               # In-repo async fakeredis test shim used by tests
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # Dev/test dependencies
├── pytest.ini               # Pytest configuration
└── README.md
```

## Note on `fakeredis/`

The `fakeredis/` folder is intentionally kept in-repo. It provides a minimal async `FakeAsyncRedis` implementation used by tests that import `fakeredis` directly. Removing this folder would break those tests unless all imports and fixtures are migrated to an external dependency pattern.

## License

Internal use only.
