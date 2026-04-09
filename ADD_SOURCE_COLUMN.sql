-- Add source column to agent_runs table with a nice default
-- This fixes the UndefinedColumnError in production

ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'reasoning_agent';

-- Verify the column was added
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'agent_runs' AND column_name = 'source';
