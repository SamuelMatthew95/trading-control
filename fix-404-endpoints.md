# Fix Dashboard 404 Errors

## Problem
Frontend was getting 404 Not Found errors when requesting:
- `/api/dashboard/prices`
- `/api/dashboard/system/metrics` 
- `/api/dashboard/events/recent`

## Root Cause
Missing dependencies prevented the dashboard router from importing, causing routes to not be registered.

## Solution
Updated requirements files with compatible dependency versions.

## Files Changed

### requirements.txt
- Updated FastAPI from 0.104.1 → 0.135.2
- Updated uvicorn from 0.24.0 → 0.42.0
- Updated pydantic from 2.5.0 → 2.12.5
- Updated pydantic-settings from 2.0.0 → 2.13.0
- Updated redis from 5.0.1 → 7.4.0
- Updated asyncpg from 0.29.0 → 0.31.0
- Updated aiosqlite from 0.19.0 → 0.22.0
- Updated structlog from 23.2.0 → 25.5.0
- Updated numpy from 1.26.0,<2 → 2.4.4
- Updated pgvector from 0.2.0 → 0.4.2

### requirements-dev.txt
- Updated httpx from 0.28.0 → 0.28.1

## Verification
All dashboard endpoints are now properly registered and accessible:
- ✅ `/api/dashboard/prices`
- ✅ `/api/dashboard/system/metrics`
- ✅ `/api/dashboard/events/recent`

## Deployment Instructions
```bash
# Install updated dependencies
pip install -r requirements.txt

# Restart the server
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## Testing
```bash
# Verify routes are registered
python3 -c "
from fastapi import FastAPI
from api.routes.dashboard_v2 import router as dashboard_v2_router
app = FastAPI()
app.include_router(dashboard_v2_router, prefix='/api')
routes = [r.path for r in app.routes if hasattr(r, 'path') and '/dashboard' in r.path]
print('Dashboard routes:', routes)
"
```
