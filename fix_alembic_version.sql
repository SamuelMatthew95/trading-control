-- Fix alembic version table to skip the problematic long migration
-- and set it to the new short migration instead

-- Update alembic_version to skip the problematic long migration
-- and jump directly to the new short migration
UPDATE alembic_version 
SET version_num = '79567db1f377_fix_agent_schema' 
WHERE version_num = '20260404_positions_snapshot_fix';

-- Verify the change
SELECT version_num FROM alembic_version;
