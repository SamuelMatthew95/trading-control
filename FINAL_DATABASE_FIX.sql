-- Complete database schema fix for production
-- This fixes all remaining schema issues

-- Fix 1: Add missing source column to agent_grades
ALTER TABLE agent_grades 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'signal_generator';

-- Fix 2: Add missing source column to agent_logs  
ALTER TABLE agent_logs 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'reasoning_agent';

-- Fix 3: Add missing error_message column to agent_runs
ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Fix 4: Fix score column precision in agent_grades
ALTER TABLE agent_grades 
ALTER COLUMN score TYPE NUMERIC(5,2);

-- Fix 5: Add missing source column to agent_runs (if not already added)
ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'default_source';

-- Fix 6: Fix date column type in llm_cost_tracking (if needed)
-- Note: This might need to be handled in the application code
-- ALTER TABLE llm_cost_tracking ALTER COLUMN date TYPE DATE USING date::date;

-- Verify all fixes
SELECT 
    'agent_grades' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'agent_grades' AND column_name IN ('source', 'score')
UNION ALL
SELECT 
    'agent_runs' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'agent_runs' AND column_name IN ('source', 'error_message')
UNION ALL
SELECT 
    'agent_logs' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'agent_logs' AND column_name = 'source';
