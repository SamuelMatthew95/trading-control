-- CORRECTED PRODUCTION FIX - Use exact revision name alembic expects
-- Run this directly to resolve startup issue

-- Step 1: Remove conflicting revisions
DELETE FROM alembic_version WHERE version_num LIKE '79567db1f377%';

-- Step 2: Insert the exact revision alembic is looking for
INSERT INTO alembic_version (version_num) 
VALUES ('79567db1f377_fix_agent_schema');

-- Step 3: Verify the fix
SELECT version_num FROM alembic_version;

-- This uses the exact revision ID alembic expects
-- No migration files needed - just database table update
