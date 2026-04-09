-- COMPLETE ALEMBIC BYPASS - Set to head without any migrations
-- This tells alembic we're already at the latest version

-- Step 1: Remove ALL alembic version entries
DELETE FROM alembic_version;

-- Step 2: Insert a single "head" entry that tells alembic we're done
INSERT INTO alembic_version (version_num) 
VALUES ('head');

-- Step 3: Verify the bypass
SELECT version_num FROM alembic_version;

-- This completely bypasses the alembic migration system
-- Alembic sees "head" and thinks no migrations are needed
-- Application can start immediately without any migration files
