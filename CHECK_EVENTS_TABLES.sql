-- Check if events tables have any data
SELECT 'processed_events' as table_name, COUNT(*) as record_count FROM processed_events
UNION ALL
SELECT 'events' as table_name, COUNT(*) as record_count FROM events  
UNION ALL
SELECT 'agent_logs' as table_name, COUNT(*) as record_count FROM agent_logs;

-- Check recent events if any exist
SELECT 'events' as table_name, id, event_type, source, created_at 
FROM events 
ORDER BY created_at DESC 
LIMIT 5;

-- Check recent agent_logs if any exist  
SELECT 'agent_logs' as table_name, id, log_type, source, created_at
FROM agent_logs 
ORDER BY created_at DESC 
LIMIT 5;
