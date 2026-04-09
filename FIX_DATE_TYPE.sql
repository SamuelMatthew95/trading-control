-- Fix date column type in llm_cost_tracking
-- Convert string dates to proper DATE type

-- Check current column type
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'llm_cost_tracking' AND column_name = 'date';

-- If the column is VARCHAR/TEXT, convert it to DATE
-- Note: This will only work if existing data can be converted
ALTER TABLE llm_cost_tracking 
ALTER COLUMN date TYPE DATE USING date::date;

-- Verify the fix
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'llm_cost_tracking' AND column_name = 'date';
