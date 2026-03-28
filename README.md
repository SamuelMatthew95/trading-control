# Trading Control

Trading Control is a Python-based trading orchestration service that coordinates strategy execution, captures operational metrics, and exposes APIs for monitoring and control. The project combines an async backend, optional frontend dashboard, and automated tests so you can run and validate trading workflows in a repeatable way.

## Documentation

- Architecture: https://matthew.docs.buildwithfern.com/docs/system-design/architecture
- API Reference: https://matthew.docs.buildwithfern.com/api-reference/api-reference/

## Prerequisites

- Python 3.10+
- pip
- (Optional for full runtime) PostgreSQL and Redis

## Installation

```bash
git clone https://github.com/SamuelMatthew95/trading-control.git
cd trading-control
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

For development and testing tools:

```bash
pip install -r requirements-dev.txt
```

## Configuration

Copy and edit the example environment file:

```bash
cp .env.example .env
```

Common variables:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/trading_control
REDIS_URL=redis://localhost:6379/0
ENABLE_SIGNAL_SCHEDULER=false
LOG_LEVEL=INFO
```

## Run the Bot / API

```bash
uvicorn api.main:app --reload
```

## Run Tests

```bash
pytest
```

## Project Structure

```text
trading-control/
├── api/                    # FastAPI app, core domain logic, services, and DB layer
├── docs/                   # Project documentation
├── frontend/               # Optional Next.js dashboard
├── scripts/                # Utility and validation scripts
├── tests/                  # Unit and regression tests
├── requirements.txt        # Production dependencies
├── requirements-dev.txt    # Development and test dependencies
└── README.md
```

## License

Internal use only.
