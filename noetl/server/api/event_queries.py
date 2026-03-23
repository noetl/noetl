PENDING_COMMAND_COUNT_SQL = """
    WITH issued_commands AS (
        SELECT meta->>'command_id' AS command_id
        FROM noetl.event
        WHERE execution_id = %(execution_id)s
          AND event_type = 'command.issued'
          AND meta ? 'command_id'
        UNION ALL
        SELECT result->'data'->>'command_id' AS command_id
        FROM noetl.event
        WHERE execution_id = %(execution_id)s
          AND event_type = 'command.issued'
          AND (result->'data') ? 'command_id'
    ),
    finished_commands AS (
        SELECT meta->>'command_id' AS command_id
        FROM noetl.event
        WHERE execution_id = %(execution_id)s
          AND event_type IN ('command.completed', 'command.failed', 'command.cancelled')
          AND meta ? 'command_id'
        UNION ALL
        SELECT result->'data'->>'command_id' AS command_id
        FROM noetl.event
        WHERE execution_id = %(execution_id)s
          AND event_type IN ('command.completed', 'command.failed', 'command.cancelled')
          AND (result->'data') ? 'command_id'
    )
    SELECT COUNT(*) AS pending_count
    FROM (
        SELECT command_id
        FROM issued_commands
        WHERE command_id IS NOT NULL
        EXCEPT
        SELECT command_id
        FROM finished_commands
        WHERE command_id IS NOT NULL
    ) AS pending
"""
