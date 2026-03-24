#!/bin/bash
# Simple production fix for Render deployment

echo "🔧 Fixing database schema..."

# Add strategy_id column if it doesn't exist
python3 -c "
from sqlalchemy import create_engine, text
import os

db_url = os.getenv('DATABASE_URL', 'sqlite:///trading-control.db')
engine = create_engine(db_url)

with engine.connect() as conn:
    # Check if strategy_id exists
    if 'postgresql' in db_url:
        result = conn.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = \\'agent_runs\\' AND column_name = \\'strategy_id\\''))
        exists = result.fetchone() is not None
    else:
        result = conn.execute(text('PRAGMA table_info(agent_runs)'))
        columns = [row[1] for row in result]
        exists = 'strategy_id' in columns
    
    if not exists:
        print('Adding strategy_id column...')
        conn.execute(text('ALTER TABLE agent_runs ADD COLUMN strategy_id VARCHAR'))
        if 'postgresql' in db_url:
            conn.execute(text('CREATE INDEX ix_agent_runs_strategy_id ON agent_runs (strategy_id)'))
        else:
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_agent_runs_strategy_id ON agent_runs (strategy_id)'))
        conn.commit()
        print('✅ Fixed!')
    else:
        print('✅ Already exists')
"

echo "🎯 Database ready!"
