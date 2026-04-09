-- Manual database fixes for deployment issues
-- Run these commands directly on the PostgreSQL database

-- Fix 1: Add missing columns to events table
ALTER TABLE events ADD COLUMN IF NOT EXISTS entity_type VARCHAR(50);
ALTER TABLE events ADD COLUMN IF NOT EXISTS entity_id VARCHAR(255);

-- Fix 2: Ensure agent_logs has source column (should exist but check)
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS source VARCHAR(64) NOT NULL DEFAULT 'agent';

-- Fix 3: Verify the columns were added successfully
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name IN ('events', 'agent_logs') 
AND column_name IN ('entity_type', 'entity_id', 'source')
ORDER BY table_name, column_name;
