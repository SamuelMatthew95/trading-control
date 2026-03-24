#!/bin/bash

echo "🚀 Production Deployment..."

# Set Python path
export PYTHONPATH="/opt/render/project/src:$PYTHONPATH"

# Run Alembic migrations
echo "� Running database migrations..."
cd /opt/render/project/src
python -m alembic upgrade head

echo "🎯 Starting API..."
exec uvicorn api.main:app --host 0.0.0.0 --port 10000
