-- CRITICAL DATABASE SCHEMA FIXES
-- Run these commands immediately to fix schema issues

-- Fix 1: Add missing columns to events table
ALTER TABLE events ADD COLUMN IF NOT EXISTS entity_id VARCHAR(255);
ALTER TABLE events ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);
ALTER TABLE events ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE events ADD COLUMN IF NOT EXISTS processed BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE events ADD COLUMN IF NOT EXISTS schema_version VARCHAR(16) DEFAULT 'v3';

-- Create unique index for idempotency_key (required for ON CONFLICT)
CREATE UNIQUE INDEX IF NOT EXISTS events_idempotency_key_idx 
ON events (idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Fix 2: Add missing columns to agent_logs table
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS source VARCHAR(64) NOT NULL DEFAULT 'agent';
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS log_level VARCHAR(20) NOT NULL DEFAULT 'INFO';
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS step_name VARCHAR(100);
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS step_data JSONB DEFAULT '{}'::jsonb;

-- Fix 3: Add missing columns to agent_runs table  
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS source VARCHAR(64) NOT NULL DEFAULT 'reasoning_agent';
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS run_type VARCHAR(32) NOT NULL DEFAULT 'analysis';
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS execution_time_ms INTEGER;

-- Fix 4: Make agent_grades columns nullable (they were incorrectly set as NOT NULL)
ALTER TABLE agent_grades ALTER COLUMN agent_id DROP NOT NULL;
ALTER TABLE agent_grades ALTER COLUMN agent_run_id DROP NOT NULL;

-- Verify all fixes
SELECT 
    table_name, 
    column_name, 
    data_type, 
    is_nullable,
    default_value
FROM information_schema.columns 
WHERE table_name IN ('events', 'agent_logs', 'agent_runs', 'agent_grades')
    AND column_name IN (
        'entity_id', 'idempotency_key', 'data', 'processed', 'schema_version',
        'source', 'log_level', 'step_name', 'step_data', 
        'run_type', 'execution_time_ms'
    )
ORDER BY table_name, column_name;
