-- Clean up stuck executions that were interrupted by server restarts
-- These executions are older than 5 minutes and have no terminal event

WITH stuck_executions AS (
  SELECT DISTINCT e1.execution_id 
  FROM noetl.event e1
  WHERE e1.event_type = 'playbook.initialized'
    AND e1.created_at < NOW() - INTERVAL '5 minutes'
    AND NOT EXISTS (
      SELECT 1 FROM noetl.event e2 
      WHERE e2.execution_id = e1.execution_id 
        AND e2.event_type IN ('playbook.completed', 'playbook.failed', 'execution.cancelled')
    )
)
INSERT INTO noetl.event (execution_id, event_type, status, payload, created_at)
SELECT 
  execution_id, 
  'execution.cancelled', 
  'CANCELLED',
  '{"reason": "Cleaned up stuck execution after server restart", "auto_cancelled": true}'::jsonb,
  NOW()
FROM stuck_executions
ON CONFLICT DO NOTHING;

-- Show summary
SELECT 
  COUNT(*) as total_stuck_executions_cleaned
FROM stuck_executions;
