#!/bin/bash

# Production deployment script for Render
# This ensures proper database setup and migrations

echo "🚀 Starting Production Deployment..."

# Set environment
export PYTHONPATH="/opt/render/project/src:$PYTHONPATH"

# Check if we're in production
if [ "$RENDER" = "true" ]; then
    echo "📦 Production environment detected"
    
    # Wait for database to be ready
    echo "⏳ Waiting for database..."
    python -c "
import asyncio
import time
from sqlalchemy import create_engine, text
from api.config import settings

async def wait_for_db():
    engine = create_engine(str(settings.DATABASE_URL))
    for i in range(30):
        try:
            with engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            print('✅ Database is ready!')
            return
        except Exception as e:
            print(f'⏳ Waiting for database... ({i+1}/30)')
            time.sleep(2)
    raise Exception('Database not ready after 60 seconds')

asyncio.run(wait_for_db())
"
    
    # Run migrations
    echo "🔄 Running database migrations..."
    cd /opt/render/project/src
    python -m alembic upgrade head
    
    echo "✅ Production setup complete!"
else
    echo "🏠 Local development environment"
fi

echo "🎯 Starting application..."
