-- Simple fix for llm_cost_tracking date issue
-- Make the date column accept strings temporarily

-- Check current column type
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'llm_cost_tracking' AND column_name = 'date';

-- If it's DATE type, change it to TEXT to accept string dates
ALTER TABLE llm_cost_tracking 
ALTER COLUMN date TYPE TEXT USING date::TEXT;

-- Verify the fix
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'llm_cost_tracking' AND column_name = 'date';
