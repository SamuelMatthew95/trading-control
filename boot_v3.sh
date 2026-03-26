#!/bin/bash
# Simple V3 Boot Script - Easy to understand

echo "🚀 STARTING V3 TRADING SYSTEM"
echo "================================"

# Check if Redis is running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "❌ Redis is not running"
    echo "💡 Start Redis with: brew services start redis"
    exit 1
fi
echo "✅ Redis is running"

# Check if PostgreSQL is running
if ! pg_isready > /dev/null 2>&1; then
    echo "❌ PostgreSQL is not running"
    echo "💡 Start PostgreSQL with: brew services start postgresql"
    exit 1
fi
echo "✅ PostgreSQL is running"

# Go to API directory
cd api

# Apply database migrations
echo "📊 Applying database migrations..."
alembic upgrade head
echo "✅ Database migrations applied"

# Start V3 system
echo "🔄 Starting V3 event-driven system..."
python simple_startup.py

echo "👋 V3 system stopped"
