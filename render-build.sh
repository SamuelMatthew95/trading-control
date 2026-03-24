#!/bin/bash

echo "🚀 Production Deployment..."

# Set Python path
export PYTHONPATH="/opt/render/project/src:$PYTHONPATH"

# Only run hotfix if explicitly enabled
if [ "$RUN_DB_HOTFIX" = "true" ]; then
    echo "🔧 Running safety hotfix..."
    ./fix-production.sh
else
    echo "✅ Hotfix disabled - using migrations only"
fi

echo "🔄 Running Alembic migrations..."
cd /opt/render/project/src
python -m alembic upgrade head

echo "🎯 Starting API..."
exec uvicorn api.main:app --host 0.0.0.0 --port 10000
