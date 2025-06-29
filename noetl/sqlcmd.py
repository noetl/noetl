"""
SQL templates for Postgres and DuckDB.

Postgres uses %s as placeholders
DuckDB uses ? as placeholders
"""

EVENT_LOG_INSERT_POSTGRES = """
INSERT INTO event_log
(execution_id, event_id, parent_event_id, timestamp, event_type,
 node_id, node_name, node_type, status, duration,
 input_context, output_result, metadata, error,
 loop_id, loop_name, iterator, items, current_index, current_item, results,
 worker_id, distributed_state, context_key, context_value)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

EVENT_LOG_INSERT_DUCKDB = """
INSERT INTO event_log
(execution_id, event_id, parent_event_id, timestamp, event_type,
 node_id, node_name, node_type, status, duration,
 input_context, output_result, metadata, error,
 loop_id, loop_name, iterator, items, current_index, current_item, results,
 worker_id, distributed_state, context_key, context_value)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

TRANSITION_INSERT_POSTGRES = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (%s, %s, %s, %s, %s)
"""

TRANSITION_INSERT_DUCKDB = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (?, ?, ?, ?, ?)
"""

LOOP_SELECT_POSTGRES = """
SELECT loop_name, iterator, items, results
FROM event_log
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY timestamp DESC
LIMIT 1
"""

LOOP_SELECT_DUCKDB = """
SELECT loop_name, iterator, items, results
FROM event_log
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY timestamp DESC
LIMIT 1
"""

LOOP_DETAILS_SELECT_POSTGRES = """
SELECT loop_name, iterator, items, current_index, current_item, results
FROM event_log
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY timestamp DESC
LIMIT 1
"""

LOOP_DETAILS_SELECT_DUCKDB = """
SELECT loop_name, iterator, items, current_index, current_item, results
FROM event_log
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY timestamp DESC
LIMIT 1
"""

LOOP_RESULTS_SELECT_POSTGRES = """
SELECT results
FROM event_log
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY timestamp DESC
LIMIT 1
"""

LOOP_RESULTS_SELECT_DUCKDB = """
SELECT results
FROM event_log
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY timestamp DESC
LIMIT 1
"""

ACTIVE_LOOPS_SELECT_POSTGRES = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event_log
WHERE execution_id = %s
  AND loop_id IS NOT NULL
  AND distributed_state != 'completed'
"""

ACTIVE_LOOPS_SELECT_DUCKDB = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event_log
WHERE execution_id = ?
  AND loop_id IS NOT NULL
  AND distributed_state != 'completed'
"""

GET_ACTIVE_LOOPS_POSTGRES = """
SELECT el.loop_id, el.loop_name, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = %s
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.distributed_state != 'completed'
ORDER BY el.timestamp ASC
"""

GET_ACTIVE_LOOPS_DUCKDB = """
SELECT el.loop_id, el.loop_name, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = ?
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.distributed_state != 'completed'
ORDER BY el.timestamp ASC
"""

FIND_LOOP_BY_NAME_POSTGRES = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = %s
      AND loop_name = %s
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.loop_name = %s
"""

FIND_LOOP_BY_NAME_DUCKDB = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = ?
      AND loop_name = ?
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.loop_name = ?
"""

FIND_LOOP_INCLUDE_COMPLETED_POSTGRES = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = %s
      AND loop_name = %s
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.loop_name = %s
ORDER BY el.timestamp DESC
LIMIT 1
"""

FIND_LOOP_INCLUDE_COMPLETED_DUCKDB = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = ?
      AND loop_name = ?
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.loop_name = ?
ORDER BY el.timestamp DESC
LIMIT 1
"""

FIND_LOOP_EXCLUDE_COMPLETED_POSTGRES = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = %s
      AND loop_name = %s
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.loop_name = %s
  AND el.distributed_state != 'completed'
ORDER BY el.timestamp DESC
LIMIT 1
"""

FIND_LOOP_EXCLUDE_COMPLETED_DUCKDB = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(timestamp) as latest_timestamp
    FROM event_log
    WHERE execution_id = ?
      AND loop_name = ?
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.loop_name = ?
  AND el.distributed_state != 'completed'
ORDER BY el.timestamp DESC
LIMIT 1
"""

GET_ALL_LOOPS_POSTGRES = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event_log
WHERE execution_id = %s
  AND loop_id IS NOT NULL
"""

GET_ALL_LOOPS_DUCKDB = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event_log
WHERE execution_id = ?
  AND loop_id IS NOT NULL
"""

COMPLETE_LOOP_SELECT_POSTGRES = """
SELECT loop_name, iterator, items, current_index, results
FROM event_log
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY timestamp DESC
LIMIT 1
"""

COMPLETE_LOOP_SELECT_DUCKDB = """
SELECT loop_name, iterator, items, current_index, results
FROM event_log
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY timestamp DESC
LIMIT 1
"""

EXPORT_EXECUTION_DATA_POSTGRES = """
SELECT execution_id, event_id, parent_event_id, timestamp, event_type,
       node_id, node_name, node_type, status, duration,
       input_context, output_result, metadata, error,
       loop_id, loop_name, iterator, items, current_index, current_item, results,
       worker_id, distributed_state, context_key, context_value
FROM event_log
WHERE execution_id = %s
ORDER BY timestamp
"""

EXPORT_EXECUTION_DATA_DUCKDB = """
SELECT execution_id, event_id, parent_event_id, timestamp, event_type,
       node_id, node_name, node_type, status, duration,
       input_context, output_result, metadata, error,
       loop_id, loop_name, iterator, items, current_index, current_item, results,
       worker_id, distributed_state, context_key, context_value
FROM event_log
WHERE execution_id = ?
ORDER BY timestamp
"""

FIND_NODE_BY_NAME_POSTGRES = """
SELECT node_name, output_result
FROM event_log
WHERE execution_id = %s
  AND node_name = %s
  AND status = 'success'
ORDER BY timestamp DESC
LIMIT 1
"""

FIND_NODE_BY_NAME_DUCKDB = """
SELECT node_name, output_result
FROM event_log
WHERE execution_id = ?
  AND node_name = ?
  AND status = 'success'
ORDER BY timestamp DESC
LIMIT 1
"""

TRANSITION_INSERT_ML_POSTGRES = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (%s, %s, %s, %s, %s)
"""

TRANSITION_INSERT_ML_DUCKDB = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (?, ?, ?, ?, ?)
"""

TRANSITION_INSERT_DIRECT_POSTGRES = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (%s, %s, %s, %s, %s)
"""

TRANSITION_INSERT_DIRECT_DUCKDB = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (?, ?, ?, ?, ?)
"""

WORKLOAD_TABLE_EXISTS_POSTGRES = """
SELECT EXISTS (
    SELECT FROM information_schema.tables 
    WHERE table_name = 'workload'
)
"""

WORKLOAD_TABLE_EXISTS_DUCKDB = """
SELECT COUNT(*) 
FROM information_schema.tables 
WHERE table_name = 'workload'
"""

WORKLOAD_COUNT_POSTGRES = """
SELECT COUNT(*) FROM workload
"""

WORKLOAD_COUNT_DUCKDB = """
SELECT COUNT(*) FROM workload
"""

WORKLOAD_COUNT_BY_ID_POSTGRES = """
SELECT COUNT(*) FROM workload WHERE execution_id = %s
"""

WORKLOAD_COUNT_BY_ID_DUCKDB = """
SELECT COUNT(*) FROM workload WHERE execution_id = ?
"""

WORKLOAD_INSERT_POSTGRES = """
INSERT INTO workload (execution_id, data)
VALUES (%s, %s)
ON CONFLICT (execution_id) DO UPDATE
SET data = EXCLUDED.data
"""

WORKLOAD_INSERT_DUCKDB = """
INSERT INTO workload (execution_id, data) VALUES (?, ?)
"""

WORKLOAD_UPDATE_DUCKDB = """
UPDATE workload SET data = ? WHERE execution_id = ?
"""

WORKLOAD_SELECT_POSTGRES = """
SELECT data FROM workload WHERE execution_id = %s
"""

WORKLOAD_SELECT_DUCKDB = """
SELECT data FROM workload WHERE execution_id = ?
"""

WORKLOAD_SELECT_ALL_IDS_POSTGRES = """
SELECT execution_id FROM workload
"""

WORKLOAD_SELECT_ALL_IDS_DUCKDB = """
SELECT execution_id FROM workload
"""

TRANSITION_INSERT_POSTGRES = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (%s, %s, %s, %s, %s)
"""

TRANSITION_INSERT_DUCKDB = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (?, ?, ?, ?, ?)
"""

STEP_RESULTS_SELECT_POSTGRES = """
SELECT node_name, output_result
FROM event_log
WHERE execution_id = %s
  AND event_type = 'step_result'
  AND status = 'success'
"""

STEP_RESULTS_SELECT_DUCKDB = """
SELECT node_name, output_result
FROM event_log
WHERE execution_id = ?
  AND event_type = 'step_result'
  AND status = 'success'
"""

WORKFLOW_INSERT_POSTGRES = """
INSERT INTO workflow
VALUES (%s, %s, %s, %s, %s, %s)
"""

WORKFLOW_INSERT_DUCKDB = """
INSERT INTO workflow
VALUES (?, ?, ?, ?, ?, ?)
"""

TRANSITION_INSERT_CONDITION_POSTGRES = """
INSERT INTO transition
VALUES (%s, %s, %s, %s, %s)
"""

TRANSITION_INSERT_CONDITION_DUCKDB = """
INSERT INTO transition
VALUES (?, ?, ?, ?, ?)
"""

WORKBOOK_INSERT_POSTGRES = """
INSERT INTO workbook
VALUES (%s, %s, %s, %s, %s)
"""

WORKBOOK_INSERT_DUCKDB = """
INSERT INTO workbook
VALUES (?, ?, ?, ?, ?)
"""
