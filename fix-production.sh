#!/bin/bash

# Only run if explicitly enabled
if [ "$RUN_DB_HOTFIX" != "true" ]; then
    echo "✅ Database hotfix disabled - skipping"
    exit 0
fi

echo "🔧 Running one-time database hotfix..."

python3 - << 'EOF'
import sys
from sqlalchemy import create_engine, text
import os

db_url = os.getenv('DATABASE_URL', 'sqlite:///trading-control.db')
engine = create_engine(db_url)

with engine.connect() as conn:
    # Check if hotfix already applied
    try:
        result = conn.execute(text("SELECT value FROM schema_migrations_meta WHERE key = 'strategy_id_hotfix'"))
        if result.fetchone():
            print("✅ Hotfix already applied - skipping")
            sys.exit(0)
    except Exception:
        # Table doesn't exist yet, that's fine
        pass
    
    # Check if strategy_id column exists
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
        
        # Create meta table and mark as done
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR
            )
        """))
        
        # Insert marker (cross-database compatible)
        try:
            conn.execute(text("""
                INSERT INTO schema_migrations_meta (key, value)
                VALUES ('strategy_id_hotfix', 'done')
            """))
        except Exception:
            pass  # Already exists
        
        conn.commit()
        print("✅ Hotfix applied")
    else:
        print("✅ Schema already correct")
        # Still mark as done to prevent rechecks
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations_meta (
                    key VARCHAR PRIMARY KEY,
                    value VARCHAR
                )
            """))
            conn.execute(text("""
                INSERT INTO schema_migrations_meta (key, value)
                VALUES ('strategy_id_hotfix', 'done')
            """))
        except Exception:
            pass
        conn.commit()
EOF

echo "🎯 Hotfix complete"
