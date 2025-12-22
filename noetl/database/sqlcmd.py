"""
SQL templates for Postgres and DuckDB.

Postgres uses %s as placeholders
DuckDB uses ? as placeholders
"""

EVENT_LOG_INSERT_POSTGRES = """
INSERT INTO event
(execution_id, event_id, parent_event_id, created_at, event_type,
 node_id, node_name, node_type, status, duration,
 context, result, meta, error,
 loop_id, loop_name, iterator, items, current_index, current_item,
 worker_id, distributed_state, context_key, context_value)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

EVENT_LOG_INSERT_DUCKDB = """
INSERT INTO event
(execution_id, event_id, parent_event_id, created_at, event_type,
 node_id, node_name, node_type, status, duration,
 context, result, meta, error,
 loop_id, loop_name, iterator, items, current_index, current_item,
 worker_id, distributed_state, context_key, context_value)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
SELECT loop_name, iterator, items
FROM event
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY created_at DESC
LIMIT 1
"""

LOOP_SELECT_DUCKDB = """
SELECT loop_name, iterator, items
FROM event
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY created_at DESC
LIMIT 1
"""

LOOP_DETAILS_SELECT_POSTGRES = """
SELECT loop_name, iterator, items, current_index, current_item
FROM event
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY created_at DESC
LIMIT 1
"""

LOOP_DETAILS_SELECT_DUCKDB = """
SELECT loop_name, iterator, items, current_index, current_item
FROM event
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY created_at DESC
LIMIT 1
"""

LOOP_RESULTS_SELECT_POSTGRES = """
SELECT NULL::text as results
FROM event
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY created_at DESC
LIMIT 1
"""

LOOP_RESULTS_SELECT_DUCKDB = """
SELECT NULL as results
FROM event
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY created_at DESC
LIMIT 1
"""

ACTIVE_LOOPS_SELECT_POSTGRES = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event
WHERE execution_id = %s
  AND loop_id IS NOT NULL
  AND distributed_state != 'completed'
"""

ACTIVE_LOOPS_SELECT_DUCKDB = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event
WHERE execution_id = ?
  AND loop_id IS NOT NULL
  AND distributed_state != 'completed'
"""

GET_ACTIVE_LOOPS_POSTGRES = """
SELECT el.loop_id, el.loop_name, el.iterator, el.items, el.current_index, el.current_item
FROM event el
INNER JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event
    WHERE execution_id = %s
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.distributed_state != 'completed'
ORDER BY el.created_at ASC
"""

GET_ACTIVE_LOOPS_DUCKDB = """
SELECT el.loop_id, el.loop_name, el.iterator, el.items, el.current_index, el.current_item
FROM event el
INNER JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event
    WHERE execution_id = ?
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.distributed_state != 'completed'
ORDER BY el.created_at ASC
"""

FIND_LOOP_BY_NAME_POSTGRES = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item
FROM event el
JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event
    WHERE execution_id = %s
      AND loop_name = %s
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.loop_name = %s
"""

FIND_LOOP_BY_NAME_DUCKDB = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item
FROM event el
JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event
    WHERE execution_id = ?
      AND loop_name = ?
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.loop_name = ?
"""

FIND_LOOP_INCLUDE_COMPLETED_POSTGRES = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item
FROM event el
INNER JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event
    WHERE execution_id = %s
      AND loop_name = %s
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.loop_name = %s
ORDER BY el.created_at DESC
LIMIT 1
"""

FIND_LOOP_INCLUDE_COMPLETED_DUCKDB = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item
FROM event el
INNER JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event
    WHERE execution_id = ?
      AND loop_name = ?
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.loop_name = ?
ORDER BY el.created_at DESC
LIMIT 1
"""

FIND_LOOP_EXCLUDE_COMPLETED_POSTGRES = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event_log
    WHERE execution_id = %s
      AND loop_name = %s
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = %s
  AND el.loop_name = %s
  AND el.distributed_state != 'completed'
ORDER BY el.created_at DESC
LIMIT 1
"""

FIND_LOOP_EXCLUDE_COMPLETED_DUCKDB = """
SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item
FROM event_log el
INNER JOIN (
    SELECT loop_id, MAX(created_at) as latest_timestamp
    FROM event_log
    WHERE execution_id = ?
      AND loop_name = ?
      AND loop_id IS NOT NULL
    GROUP BY loop_id
) latest ON el.loop_id = latest.loop_id AND el.created_at = latest.latest_timestamp
WHERE el.execution_id = ?
  AND el.loop_name = ?
  AND el.distributed_state != 'completed'
ORDER BY el.created_at DESC
LIMIT 1
"""

GET_ALL_LOOPS_POSTGRES = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event
WHERE execution_id = %s
  AND loop_id IS NOT NULL
"""

GET_ALL_LOOPS_DUCKDB = """
SELECT DISTINCT loop_id, loop_name, distributed_state
FROM event
WHERE execution_id = ?
  AND loop_id IS NOT NULL
"""

COMPLETE_LOOP_SELECT_POSTGRES = """
SELECT loop_name, iterator, items, current_index, results
FROM event
WHERE execution_id = %s
  AND loop_id = %s
ORDER BY created_at DESC
LIMIT 1
"""

COMPLETE_LOOP_SELECT_DUCKDB = """
SELECT loop_name, iterator, items, current_index, results
FROM event_log
WHERE execution_id = ?
  AND loop_id = ?
ORDER BY created_at DESC
LIMIT 1
"""

EXPORT_EXECUTION_DATA_POSTGRES = """
SELECT execution_id, event_id, parent_event_id, created_at, event_type,
       node_id, node_name, node_type, status, duration,
       context, result, meta, error,
       loop_id, loop_name, iterator, items, current_index, current_item,
       worker_id, distributed_state, context_key, context_value
FROM event_log
WHERE execution_id = %s
ORDER BY created_at
"""

EXPORT_EXECUTION_DATA_DUCKDB = """
SELECT execution_id, event_id, parent_event_id, created_at, event_type,
       node_id, node_name, node_type, status, duration,
       context, result, meta, error,
       loop_id, loop_name, iterator, items, current_index, current_item,
       worker_id, distributed_state, context_key, context_value
FROM event_log
WHERE execution_id = ?
ORDER BY created_at
"""

FIND_NODE_BY_NAME_POSTGRES = """
SELECT node_name, result
FROM event
WHERE execution_id = %s
  AND node_name = %s
  AND status = 'success'
ORDER BY created_at DESC
LIMIT 1
"""

FIND_NODE_BY_NAME_DUCKDB = """
SELECT node_name, result
FROM event
WHERE execution_id = ?
  AND node_name = ?
  AND status = 'success'
ORDER BY created_at DESC
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

TRANSITION_INSERT_POSTGRES = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (%s, %s, %s, %s, %s)
"""

TRANSITION_INSERT_DUCKDB = """
INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
VALUES (?, ?, ?, ?, ?)
"""

STEP_RESULTS_SELECT_POSTGRES = """
SELECT node_name, result
FROM event_log
WHERE execution_id = %s
  AND event_type = 'step_result'
  AND status = 'success'
"""

STEP_RESULTS_SELECT_DUCKDB = """
SELECT node_name, result
FROM event_log
WHERE execution_id = ?
  AND event_type = 'step_result'
  AND status = 'success'
"""

WORKFLOW_INSERT_POSTGRES = """
INSERT INTO workflow (execution_id, step_id, step_name, step_type, description, raw_config)
VALUES (%s, %s, %s, %s, %s, %s)
"""
