-- Debug the exact queries from the events history endpoint

-- Query 1: Stream counts (from processed_events table)
SELECT
    stream,
    COUNT(*) AS processed_count,
    MAX(COALESCE(processed_at, created_at)) AS last_processed_at
FROM processed_events
GROUP BY stream
ORDER BY processed_count DESC;

-- Query 2: Recent events (from events table)
SELECT id, event_type, source, created_at
FROM events
ORDER BY created_at DESC
LIMIT 5;

-- Query 3: Recent agent_logs (from agent_logs table)
SELECT id, trace_id, log_type, created_at
FROM agent_logs
ORDER BY created_at DESC
LIMIT 5;

-- Check if the columns exist and have the right names
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name IN ('processed_events', 'events', 'agent_logs')
ORDER BY table_name, column_name;
