#!/bin/bash
echo "🔧 Checking database schema..."

python3 - << 'EOF'
from sqlalchemy import create_engine, text
import os

db_url = os.getenv('DATABASE_URL', 'sqlite:///trading-control.db')
engine = create_engine(db_url)

with engine.connect() as conn:
    if 'postgresql' in db_url:
        result = conn.execute(text("""
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_name='agent_runs' 
            AND column_name='strategy_id'
        """))
        exists = result.fetchone() is not None
    else:
        result = conn.execute(text("PRAGMA table_info(agent_runs)"))
        exists = any(row[1] == 'strategy_id' for row in result)

    if not exists:
        print("⚠️ strategy_id missing — applying hotfix...")
        conn.execute(text("ALTER TABLE agent_runs ADD COLUMN strategy_id VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_strategy_id ON agent_runs (strategy_id)"))
        conn.commit()
        print("✅ Hotfix applied")
    else:
        print("✅ Schema already correct — skipping")
EOF

echo "🎯 Done"
