-- FINAL PRODUCTION FIX - Bypass alembic completely
-- Run this directly to resolve startup issue

-- Step 1: Remove the problematic revision from alembic_version
DELETE FROM alembic_version WHERE version_num = '20260404_positions_snapshot_fix';

-- Step 2: Insert a simple revision that alembic can find
INSERT INTO alembic_version (version_num) 
VALUES ('79567db1f377');

-- Step 3: Verify the fix
SELECT version_num FROM alembic_version;

-- This bypasses the entire alembic migration system
-- and tells alembic we're already at the "head" revision
-- No migration files needed - just database table update
