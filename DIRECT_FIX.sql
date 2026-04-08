-- DIRECT FIX FOR PRODUCTION ALEMBIC ISSUE
-- Run this directly on your production database

-- Step 1: Insert the missing revision (alembic_version only has version_num column)
INSERT INTO alembic_version (version_num) 
VALUES ('79567db1f377_fix_agent_schema')
ON CONFLICT (version_num) DO UPDATE SET 
    version_num = EXCLUDED.version_num;

-- Step 2: Verify it worked
SELECT version_num FROM alembic_version WHERE version_num = '79567db1f377_fix_agent_schema';

-- This bypasses the need for the actual migration file
-- and directly tells alembic the revision exists
