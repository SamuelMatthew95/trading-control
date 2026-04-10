-- Fixed verification query (remove default_value which doesn't exist)
SELECT 
    table_name, 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name IN ('events', 'agent_logs', 'agent_runs', 'agent_grades')
    AND column_name IN (
        'entity_id', 'idempotency_key', 'data', 'processed', 'schema_version',
        'source', 'log_level', 'step_name', 'step_data', 
        'run_type', 'execution_time_ms'
    )
ORDER BY table_name, column_name;

-- Also check agent_grades specifically for nullable columns
SELECT 
    column_name, 
    is_nullable, 
    data_type
FROM information_schema.columns 
WHERE table_name = 'agent_grades' 
    AND column_name IN ('agent_id', 'agent_run_id')
ORDER BY column_name;
