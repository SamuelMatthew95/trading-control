#!/bin/bash

echo "🚀 Production Deployment..."

# Set Python path
export PYTHONPATH="/opt/render/project/src:$PYTHONPATH"

# One-time safety net, then proper migrations
echo "🔧 Running safety check..."
./fix-production.sh

echo "🔄 Running Alembic migrations..."
cd /opt/render/project/src
python -m alembic upgrade head

echo "🎯 Starting API..."
exec uvicorn api.main:app --host 0.0.0.0 --port 10000
