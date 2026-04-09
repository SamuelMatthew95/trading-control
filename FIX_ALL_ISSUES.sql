-- Fix all remaining database schema issues

-- Fix 1: Add missing error_message column
ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Fix 2: Increase score column precision to handle larger values
ALTER TABLE agent_grades 
ALTER COLUMN score TYPE NUMERIC(5,2);

-- Fix 3: Add missing source column (if not already added)
ALTER TABLE agent_runs 
ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'default_source';

-- Verify all fixes
SELECT 
    'agent_runs' as table_name,
    column_name,
    data_type
FROM information_schema.columns 
WHERE table_name = 'agent_runs' 
UNION ALL
SELECT 
    'agent_grades' as table_name,
    column_name,
    data_type
FROM information_schema.columns 
WHERE table_name = 'agent_grades' AND column_name = 'score';
