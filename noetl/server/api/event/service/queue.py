"""
Queue management utilities.

Handles task enqueueing with retry configuration.
"""

import json
from typing import Dict, Any
from noetl.core.common import snowflake_id_to_int
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def enqueue_task(
    cur, conn,
    execution_id: str,
    step_name: str,
    task: Dict[str, Any],
    ctx: Dict[str, Any],
    catalog_id: int
) -> None:
    """
    Enqueue a task to the worker queue.
    
    Args:
        cur: Database cursor
        conn: Database connection
        execution_id: Execution ID
        step_name: Step name
        task: Task definition
        ctx: Execution context
        catalog_id: Catalog ID
    """
    
    logger.info(f"QUEUE: enqueue_task called for step='{step_name}', execution={execution_id}")
    
    from noetl.server.api.broker import encode_task_for_queue
    
    # Extract retry config
    max_attempts = 3
    retry_config = task.get('retry')
    if isinstance(retry_config, bool):
        max_attempts = 3 if retry_config else 1
    elif isinstance(retry_config, int):
        max_attempts = retry_config
    elif isinstance(retry_config, dict):
        max_attempts = retry_config.get('max_attempts', 3)
    
    logger.info(f"QUEUE: max_attempts={max_attempts}, catalog_id={catalog_id}")
    
    # Encode task
    logger.info(f"QUEUE: About to encode task")
    try:
        encoded = encode_task_for_queue(task)
        logger.info(f"QUEUE: Task encoded successfully, type={type(encoded)}")
    except Exception as e:
        logger.error(f"QUEUE: encode_task_for_queue FAILED: {e}", exc_info=True)
        raise
    
    # Insert into queue
    logger.info(f"QUEUE: About to INSERT into noetl.queue")
    try:
        await cur.execute(
            """
            INSERT INTO noetl.queue (
                execution_id, catalog_id, node_id,
                action, context, priority, max_attempts, available_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, now())
            ON CONFLICT (execution_id, node_id) DO NOTHING
            RETURNING queue_id
            """,
            (
                snowflake_id_to_int(execution_id),
                catalog_id,
                f"{execution_id}:{step_name}",
                json.dumps(encoded),
                json.dumps(ctx),
                5,
                max_attempts,
            )
        )
        logger.info(f"QUEUE: INSERT executed, fetching result")
        result = await cur.fetchone()
        logger.info(f"QUEUE: Fetch result={result}")
        
        logger.info(f"QUEUE: About to commit")
        await conn.commit()
        logger.info(f"QUEUE: Commit successful")
        
        if result:
            logger.info(f"QUEUE: Enqueued task for step '{step_name}' in execution {execution_id}, queue_id={result[0]}")
        else:
            logger.debug(f"QUEUE: Task for step '{step_name}' already queued (conflict)")
    except Exception as e:
        logger.error(f"QUEUE: INSERT or COMMIT FAILED: {e}", exc_info=True)
        raise
