-- QUICK PRODUCTION FIX - Run this directly
-- This bypasses alembic entirely and fixes the version table

-- Insert the missing revision that alembic is looking for
INSERT INTO alembic_version (version_num, down_revision) 
VALUES ('79567db1f377_fix_agent_schema', '20260404_positions_snapshot_fix')
ON CONFLICT (version_num) DO UPDATE SET 
    version_num = EXCLUDED.version_num, 
    down_revision = EXCLUDED.down_revision;

-- Verify it worked
SELECT version_num FROM alembic_version WHERE version_num = '79567db1f377_fix_agent_schema';
