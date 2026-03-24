#!/bin/bash
set -e

# Only run if explicitly enabled
if [ "$RUN_DB_HOTFIX" != "true" ]; then
    echo "Database hotfix disabled — skipping"
    exit 0
fi

echo "Running DIRECT database hotfix"

# Direct SQL approach - more reliable
python3 - << 'EOF'
import os
import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

db_url = os.getenv('DATABASE_URL', 'sqlite:///trading-control.db')

async def run_hotfix():
    # Use async engine for PostgreSQL
    if 'postgresql' in db_url:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            # Check if column exists
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name='agent_runs' AND column_name='strategy_id'
            """))
            exists = result.fetchone() is not None
            
            if not exists:
                print("Adding strategy_id column...")
                await conn.execute(text("ALTER TABLE agent_runs ADD COLUMN strategy_id VARCHAR"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_strategy_id ON agent_runs(strategy_id)"))
                print("✅ Column added successfully")
            else:
                print("✅ Column already exists")
    else:
        # SQLite fallback
        engine = create_engine(db_url)
        with engine.begin() as conn:
            result = conn.execute(text("PRAGMA table_info(agent_runs)"))
            columns = [row[1] for row in result]
            exists = 'strategy_id' in columns
            
            if not exists:
                print("Adding strategy_id column...")
                conn.execute(text("ALTER TABLE agent_runs ADD COLUMN strategy_id VARCHAR"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_strategy_id ON agent_runs(strategy_id)"))
                print("✅ Column added successfully")
            else:
                print("✅ Column already exists")
    
    await engine.dispose() if 'postgresql' in db_url else None

asyncio.run(run_hotfix())
EOF

echo "Direct hotfix complete"
