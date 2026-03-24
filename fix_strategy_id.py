#!/usr/bin/env python3
"""Simple fix for strategy_id column"""

import asyncio
from sqlalchemy import create_engine, text
from api.config import settings

def fix_strategy_id():
    # Get database URL
    db_url = str(settings.DATABASE_URL) if settings.DATABASE_URL else 'sqlite:///trading-control.db'
    print(f'Database URL: {db_url}')

    engine = create_engine(db_url)

    # Check if strategy_id column exists
    with engine.connect() as conn:
        if 'postgresql' in db_url:
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'agent_runs' AND column_name = 'strategy_id'
            """))
            exists = result.fetchone() is not None
        else:
            # SQLite
            result = conn.execute(text("PRAGMA table_info(agent_runs)"))
            columns = [row[1] for row in result]
            exists = 'strategy_id' in columns
        
        print(f'strategy_id exists: {exists}')
        
        if not exists:
            print('Adding strategy_id column...')
            if 'postgresql' in db_url:
                conn.execute(text('ALTER TABLE agent_runs ADD COLUMN strategy_id VARCHAR'))
                conn.execute(text('CREATE INDEX ix_agent_runs_strategy_id ON agent_runs (strategy_id)'))
            else:
                conn.execute(text('ALTER TABLE agent_runs ADD COLUMN strategy_id VARCHAR'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS ix_agent_runs_strategy_id ON agent_runs (strategy_id)'))
            conn.commit()
            print('✅ strategy_id column added!')
        else:
            print('✅ strategy_id already exists')

if __name__ == "__main__":
    fix_strategy_id()
