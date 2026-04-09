-- Quick fix for missing source column in agent_grades
-- This fixes the NotNullViolationError

-- Add missing source column to agent_grades
ALTER TABLE agent_grades 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'signal_generator';

-- Verify the fix
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'agent_grades' AND column_name = 'source';
