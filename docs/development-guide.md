# 🚀 Development Setup Guide

## Quick Start

Get your Trading Bot Brain running locally in minutes.

---

## 📋 Prerequisites

### Required Software
- **Python 3.11+** - Backend runtime
- **Node.js 18+** - Frontend runtime
- **PostgreSQL** - Local database (or use Neon/Supabase)
- **Git** - Version control

### Required Services
- **Anthropic API Key** - For AI agent functionality
- **Database** - PostgreSQL instance (local or managed)

---

## 🚀 Setup Instructions

### 1. Clone Repository
```bash
git clone https://github.com/your-username/trading-control-python.git
cd trading-control-python
```

### 2. Backend Setup
```bash
# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env.local
# Edit .env.local with your configuration
nano .env.local
```

### 3. Database Setup
```bash
# Option 1: Use managed PostgreSQL (Recommended)
# Set DATABASE_URL in .env.local to your Neon/Supabase connection string

# Option 2: Local PostgreSQL
# Create local database
createdb trading_bot
psql trading_bot -c "CREATE USER trading_bot WITH PASSWORD 'your_password';"

# Initialize database tables
python scripts/init_db.py
```

### 4. Frontend Setup
```bash
cd frontend

# Install Node.js dependencies
npm install

# Set up environment variables
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

### 5. Run Development Servers

#### Backend Server
```bash
# From root directory
python3 api/index.py

# Server will run on http://localhost:8000
# API docs available at http://localhost:8000/docs
```

#### Frontend Server
```bash
# From frontend directory
cd frontend

# Start development server
npm run dev

# Frontend will run on http://localhost:3000
# Dashboard will connect to backend API
```

---

## 🧪 Verification Steps

### Test Backend API
```bash
# Test health endpoint
curl http://localhost:8000/api/health

# Expected response:
{
  "status": "healthy",
  "orchestrator": true,
  "database": "connected"
}
```

### Test Frontend Connection
```bash
# Test API connectivity from frontend
curl http://localhost:3000/api/health

# Should proxy to backend successfully
```

### Test Full System
1. Open http://localhost:3000 in browser
2. Navigate to Dashboard tab
3. Enter a symbol (e.g., AAPL) and price
4. Click "Analyze Trade" button
5. Watch real-time agent updates
6. Verify trade saves to database

---

## 🔧 Configuration

### Environment Variables (.env.local)
```bash
# Required for production
DATABASE_URL=postgresql://user:password@host:5432/database_name
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NODE_ENV=development

# Optional for development
NEXT_PUBLIC_APP_URL=http://localhost:3000
LANGFUSE_PUBLIC_KEY=your_langfuse_key
LANGFUSE_SECRET_KEY=your_langfuse_secret
```

### Database Configuration
```bash
# Local PostgreSQL setup
createdb trading_bot
psql trading_bot -c "
CREATE USER trading_bot WITH PASSWORD 'secure_password';
CREATE DATABASE trading_bot;
GRANT ALL PRIVILEGES ON DATABASE trading_bot TO trading_bot;
"
```

---

## 🧪 Development Workflow

### Daily Development
```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Start backend (Terminal 1)
python3 api/index.py

# 3. Start frontend (Terminal 2)
cd frontend && npm run dev

# 4. Make changes
# Edit files and see hot reload automatically
```

### Code Quality Checks
```bash
# Python formatting
black api/ --check

# Import sorting
isort api/ --check-only

# Type checking
mypy api/

# Frontend formatting
cd frontend && npm run format

# Frontend linting
cd frontend && npm run lint
```

### Testing
```bash
# Run backend tests
python3 -m pytest tests/ -v

# Run frontend tests
cd frontend && npm test

# Run with coverage
python3 -m pytest tests/ --cov=api --cov-report=html
cd frontend && npm run test:coverage
```

---

## 🐛 Troubleshooting

### Common Issues

#### Backend Won't Start
```bash
# Check Python version
python3 --version  # Should be 3.11+

# Check dependencies
pip list | grep -E "(fastapi|uvicorn|pydantic)"

# Check environment
python3 scripts/validate_env.py
```

#### Frontend Build Errors
```bash
# Clear Next.js cache
cd frontend && rm -rf .next

# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install

# Check Node.js version
node --version  # Should be 18+
```

#### Database Connection Issues
```bash
# Test connection
python3 -c "
import psycopg2
try:
    conn = psycopg2.connect('postgresql://user:pass@host:5432/db')
    print('✅ Database connection successful')
except Exception as e:
    print(f'❌ Database connection failed: {e}')
"

# Check database URL format
python3 -c "
from urllib.parse import urlparse
url = 'postgresql://user:pass@host:5432/db'
parsed = urlparse(url)
print(f'Scheme: {parsed.scheme}')
print(f'Host: {parsed.hostname}')
print(f'Port: {parsed.port}')
"
```

#### Port Conflicts
```bash
# Check what's using port 8000
lsof -i :8000

# Check what's using port 3000
lsof -i :3000

# Kill processes if needed
kill -9 <PID>
```

---

## 📚 Development Resources

### Documentation
- **[Architecture](architecture.md)** - System design and components
- **[API Documentation](http://localhost:8000/docs)** - Interactive API docs
- **[Component Library](../frontend/src/components/)** - Reusable UI components

### Learning Resources
- **[FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)** - Backend framework
- **[Next.js Documentation](https://nextjs.org/docs)** - Frontend framework
- **[PostgreSQL Guide](https://www.postgresql.org/docs/)** - Database system

### Tools & Extensions
- **[Postico](https://www.postico.com/)** - PostgreSQL GUI client
- **[Insomnia](https://insomnia.rest/)** - API testing client
- **[React DevTools](https://chrome.google.com/webstore/detail/fmkadmapgofadagbjgkkhdn/)** - Browser dev tools

---

## 🔄 Next Steps

After successful setup:

1. **Explore the Dashboard** - Try all features and tabs
2. **Add Test Trades** - Populate database with sample data
3. **Test AI Agents** - Verify Claude API integration
4. **Review Performance** - Check agent learning system
5. **Customize Configuration** - Adjust settings for your needs

---

## 🎯 Best Practices

### Development
- **Commit frequently** with descriptive messages
- **Use branches** for features and bug fixes
- **Write tests** for new functionality
- **Update documentation** when making changes

### Security
- **Never commit** `.env.local` or API keys
- **Use environment variables** for all configuration
- **Validate inputs** on all API endpoints
- **Keep dependencies** updated regularly

---

**🚀 Your Trading Bot Brain is ready for development!**

Follow this guide to get your local environment running smoothly.
