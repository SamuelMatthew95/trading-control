-- Direct PostgreSQL script to add missing source columns
-- Run this directly on your production database to fix the immediate issue

-- Add source column to agent_runs table
ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) NOT NULL DEFAULT 'reasoning_agent';

-- Add source column to agent_logs table  
ALTER TABLE agent_logs 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) NOT NULL DEFAULT 'agent';

-- Add source column to agent_grades table
ALTER TABLE agent_grades 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) NOT NULL DEFAULT 'grade_agent';

-- Add source column to events table
ALTER TABLE events 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT NULL;

-- Also add any other missing columns from the migration
ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS run_type VARCHAR(32) NOT NULL DEFAULT 'analysis';

ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS execution_time_ms INTEGER DEFAULT NULL;

ALTER TABLE events 
ADD COLUMN IF NOT EXISTS data JSONB DEFAULT NULL;

ALTER TABLE events 
ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255) NOT NULL DEFAULT '';

ALTER TABLE events 
ADD COLUMN IF NOT EXISTS schema_version VARCHAR(32) DEFAULT NULL;

ALTER TABLE events 
ADD COLUMN IF NOT EXISTS processed BOOLEAN DEFAULT FALSE;

-- Create unique index for events if it doesn't exist
CREATE UNIQUE INDEX IF NOT EXISTS uq_events_idempotency_key ON events(idempotency_key);

-- Drop NOT NULL constraints that were blocking inserts
ALTER TABLE agent_grades ALTER COLUMN agent_id DROP NOT NULL;
ALTER TABLE agent_grades ALTER COLUMN agent_run_id DROP NOT NULL;

-- Verify the changes
SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name IN ('agent_runs', 'agent_logs', 'agent_grades', 'events')
    AND column_name = 'source'
ORDER BY table_name;
