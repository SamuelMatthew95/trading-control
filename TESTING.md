# Testing Guide

Production-ready testing setup for the trading-control application, covering backend testing and prepared frontend testing structure.

## 🚀 Quick Start

### Backend Tests
```bash
# Install dependencies
pip install -r requirements-test.txt

# Run all backend tests
pytest tests/ -v

# Run specific categories
pytest tests/api/ -v          # API tests (3 tests)
pytest tests/core/ -v         # Core logic tests (21 tests)
pytest tests/integration/ -v  # Integration tests (3 tests)
```

### Frontend Tests
⚠️ **Currently Disabled** - No frontend UI application exists yet.

When frontend is added, follow these steps:
```bash
# Install dependencies
cd tests/frontend
npm install

# Install Playwright browsers
npm run playwright:install

# Run tests (after frontend app exists)
npm run test:unit              # Jest unit tests
npm run test:e2e               # Playwright E2E tests
npm run test:ci                # CI-friendly run
```

## 📁 Folder Structure

```
├── tests/                           # Main test directory
│   ├── __init__.py                  # Root test package
│   ├── conftest.py                  # Global fixtures
│   ├── api/                         # API endpoint tests
│   │   ├── __init__.py
│   │   ├── conftest.py             # API fixtures
│   │   ├── test_dashboard_real_data.py
│   │   ├── test_dlq_api.py
│   │   └── test_websocket_fixes.py
│   ├── core/                        # Business logic tests
│   │   ├── __init__.py
│   │   ├── conftest.py             # Core fixtures
│   │   ├── test_agent_run_utils.py
│   │   ├── test_learning_monitoring.py
│   │   └── ... (21 total tests)
│   ├── integration/                 # Integration tests
│   │   ├── __init__.py
│   │   ├── conftest.py             # Integration fixtures
│   │   ├── test_feedback_pipeline.py
│   │   ├── test_service_flow.py
│   │   └── test_redis_connection_fixes.py
│   └── frontend/                    # ⚠️ Frontend tests (ready but disabled)
│       ├── __init__.py
│       ├── conftest.py             # Frontend configuration
│       ├── package.json            # Frontend test dependencies
│       ├── jest.config.js          # Jest configuration
│       ├── jest.config.simple.js   # Simplified Jest config
│       ├── playwright.config.ts    # Playwright configuration
│       ├── src/__tests__/           # Unit/Component tests (ready)
│       │   ├── components/         # React component tests
│       │   ├── pages/              # Page tests with API integration
│       │   ├── hooks/              # React hook tests
│       │   ├── utils/              # Frontend utility tests
│       │   └── setup.ts            # Jest setup
│       ├── e2e/                    # End-to-end tests (ready)
│       │   ├── auth.spec.ts        # Authentication E2E tests
│       │   └── dashboard.spec.ts   # Dashboard E2E tests
│       ├── mocks/                  # Centralized API mocking
│       │   ├── server.ts          # MSW server setup
│       │   └── handlers.ts        # API mock handlers
│       └── TESTING.md              # Frontend-specific documentation
├── frontend/                        # ⚠️ Frontend application (not yet created)
│   └── ... (will be added later)
├── api/                            # Backend API
│   └── ... (source code)
└── .github/workflows/
    └── ci-simple.yml               # CI/CD pipeline (frontend jobs disabled)
```

## 🧪 Testing Stack

### Backend Testing ✅ **ACTIVE**
- **pytest** - Test runner and fixtures
- **pytest-asyncio** - Async test support
- **httpx** - HTTP client for API testing
- **fake_redis** - Redis mocking
- **Custom fixtures** - Database sessions, test data

### Frontend Testing ⚠️ **PREPARED BUT DISABLED**
- **Jest** - Unit test runner (configured)
- **React Testing Library** - Component testing (ready)
- **Playwright** - E2E browser automation (ready)
- **MSW** - API mocking for isolated testing (ready)
- **TypeScript** - Type-safe testing (ready)

## 📝 Test Examples

### Backend API Test ✅
```python
# tests/api/test_dashboard_real_data.py
import pytest
from httpx import AsyncClient
from api.main import app
from tests.conftest import TEST_REFERENCE_DT

@pytest.mark.asyncio
async def test_dashboard_signals():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/dashboard/signals")
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data
```

### Frontend Unit Test ⚠️ **Ready but Disabled**
```tsx
// tests/frontend/src/__tests__/components/ThemeToggle.test.tsx
import { render, screen } from '../utils/test-utils';
import { ThemeToggle } from '@/components/ThemeToggle';

test('renders theme toggle', () => {
  render(<ThemeToggle />);
  expect(screen.getByRole('button', { name: /toggle theme/i })).toBeInTheDocument();
});
```

### Frontend E2E Test ⚠️ **Ready but Disabled**
```typescript
// tests/frontend/e2e/dashboard.spec.ts
import { test, expect } from '@playwright/test';

test('dashboard loads correctly', async ({ page }) => {
  await page.goto('/dashboard');
  await expect(page.getByText('Dashboard')).toBeVisible();
});
```

## 🔧 Configuration

### Backend Configuration ✅
```python
# tests/conftest.py - Global fixtures
@pytest.fixture
def fake_redis():
    """Mock Redis for testing"""
    # Redis mocking implementation

@pytest.fixture
def TEST_REFERENCE_DT():
    """Test reference datetime"""
    # Test datetime fixture
```

### Frontend Configuration ⚠️ **Prepared but Disabled**
```javascript
// tests/frontend/jest.config.js
const nextJest = require('next/jest');
const createJestConfig = nextJest({ dir: '../frontend' });

const customJestConfig = {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/src/__tests__/setup.ts'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/../frontend/src/$1',
  },
  coverageThreshold: {
    global: { branches: 70, functions: 70, lines: 70, statements: 70 }
  }
};

module.exports = createJestConfig(customJestConfig);
```

```typescript
// tests/frontend/playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
  webServer: process.env.CI ? {
    command: 'cd ../frontend && npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  } : undefined,
});
```

## 🔄 CI/CD Pipeline

### Workflow Structure
```yaml
# .github/workflows/ci-simple.yml
name: Frontend & Integration Tests

on:
  push:
    branches: [ main, develop ]
    paths: [ 'frontend/**', 'api/**' ]
  pull_request:
    branches: [ main, develop ]
    paths: [ 'frontend/**', 'api/**' ]

jobs:
  frontend-unit:      # ⚠️ Disabled until frontend exists
  frontend-e2e:       # ⚠️ Disabled until frontend exists
  integration-backend: # ✅ Active when backend changes
```

### Current Status
- ✅ **Backend tests**: Active and working
- ⚠️ **Frontend jobs**: Configured but disabled until frontend app exists

## 📊 Test Coverage

### Backend Tests ✅ (27 total)
- **API Tests**: 3 tests - Endpoint validation, authentication
- **Core Tests**: 21 tests - Business logic, models, utilities
- **Integration Tests**: 3 tests - Cross-component interactions

### Frontend Tests ⚠️ (4 total - Ready but Disabled)
- **Unit Tests**: 2 tests - Component testing with RTL
- **E2E Tests**: 2 tests - Browser automation with Playwright

## 🎯 To Enable Frontend Testing

When you're ready to add the frontend application:

### 1. Add Next.js Frontend
```bash
# Create Next.js app in frontend/ directory
npx create-next-app@latest frontend --typescript --tailwind --eslint
cd frontend
npm install @testing-library/react @testing-library/jest-dom @testing-library/user-event
npm install -D playwright @playwright/test msw
```

### 2. Update Frontend Package Scripts
```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build", 
    "start": "next start",
    "lint": "next lint",
    "type-check": "tsc --noEmit",
    "test": "jest",
    "test:watch": "jest --watch",
    "test:coverage": "jest --coverage"
  }
}
```

### 3. Enable CI/CD Jobs
Uncomment or remove the `if: false` conditions in `.github/workflows/ci-simple.yml` for frontend jobs.

### 4. Run Tests
```bash
# Backend (working now)
pytest tests/ -v

# Frontend (after app exists)
cd tests/frontend
npm install && npm run playwright:install
npm run test:unit
npm run test:e2e
```

## 🎯 Best Practices

### Backend Testing ✅
1. **Use fixtures** for common setup (database, Redis, test data)
2. **Test categories** in appropriate folders (api/, core/, integration/)
3. **Mock external services** to ensure test isolation
4. **Use async/await** for async operations
5. **Validate both success and error scenarios**

### Frontend Testing ⚠️ **Ready for When Frontend Exists**
1. **Test components in isolation** with RTL
2. **Mock API calls** with MSW for consistent testing
3. **Test user interactions** and accessibility
4. **Use meaningful assertions** for user-visible behavior
5. **Maintain test data** close to real API responses

## 🐛 Debugging

### Backend Debugging ✅
```bash
# Run specific test with output
pytest tests/core/test_agent_run_utils.py::test_create_agent_run -v -s

# Run with debugger
pytest --pdb tests/core/test_agent_run_utils.py
```

### Frontend Debugging ⚠️ **Ready for When Frontend Exists**
```bash
# Debug unit tests
cd tests/frontend
npm test -- --testNamePattern="ThemeToggle"

# Debug E2E tests
npm run test:e2e:debug

# Generate Playwright code
npx playwright codegen http://localhost:3000
```

## 📋 Maintenance

### Regular Tasks
- [ ] Update test dependencies regularly
- [ ] Review coverage reports and improve low-coverage areas
- [ ] Keep API mocks in sync with backend changes
- [ ] Clean up obsolete or duplicate tests
- [ ] Monitor test performance and flaky tests

### Before Pushing
- [ ] Run `pytest tests/ -v` locally ✅
- [ ] Run `cd tests/frontend && npm run test:ci` (when frontend exists) ⚠️
- [ ] Verify all tests pass
- [ ] Check coverage meets thresholds
- [ ] Review test output for warnings

---

This testing architecture provides comprehensive coverage for backend components and is fully prepared for frontend testing when the application is ready.
