"""
Event CRUD endpoints for managing events.
"""

from typing import Optional
import asyncio
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from noetl.core.common import convert_snowflake_ids_for_api, snowflake_id_to_int
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/events", response_class=JSONResponse)
async def create_event(
    request: Request,
    background_tasks: BackgroundTasks
):
    try:
        from .service import get_event_service
        from .processing import evaluate_broker_for_execution, _evaluate_broker_for_execution, _check_distributed_loop_completion
        
        body = await request.json()
        
        # Debug all incoming events
        if body.get('event_type') in ['execution_completed', 'execution_complete']:
            print(f"[PRINT DEBUG] Received execution completion event: {body.get('execution_id')}")
            logger.info(f"EVENT_DEBUG: Received execution completion event: {body}")
        
        event_service = get_event_service()
        result = await event_service.emit(body)
        
        # Check if this is a child execution completion event
        if body.get('event_type') in ['execution_completed', 'execution_complete']:
            print(f"[PRINT DEBUG] Processing completion event for execution {body.get('execution_id')}")
            logger.info(f"COMPLETION_HANDLER: Processing completion event for execution {body.get('execution_id')}")
            logger.info(f"COMPLETION_HANDLER: Event body: {body}")
            try:
                meta = body.get('meta', {}) or body.get('metadata', {})
                logger.info(f"COMPLETION_HANDLER: Meta data: {meta}")
                parent_execution_id = meta.get('parent_execution_id')
                parent_step = meta.get('parent_step')
                exec_id = body.get('execution_id')
                logger.info(f"COMPLETION_HANDLER: parent_execution_id={parent_execution_id}, parent_step={parent_step}, exec_id={exec_id}")
                
                if parent_execution_id and exec_id and parent_execution_id != exec_id:
                    # If parent_step is not in metadata, derive it from result events sent to parent
                    if not parent_step:
                        try:
                            from noetl.core.common import get_async_db_connection as get_db_conn
                            async with get_db_conn() as conn:
                                async with conn.cursor() as cur:
                                    # Find parent_step from result events sent back to parent for this child
                                    await cur.execute(
                                        """
                                        SELECT context::json->>'parent_step' as parent_step
                                        FROM noetl.event
                                        WHERE execution_id = %s
                                          AND event_type = 'result'
                                          AND context LIKE %s
                                          AND context::json->>'parent_step' IS NOT NULL
                                        LIMIT 1
                                        """,
                                        (parent_execution_id, f'%"child_execution_id": "{exec_id}"%')
                                    )
                                    row = await cur.fetchone()
                                    if row and row[0]:
                                        parent_step = row[0]
                        except Exception:
                            logger.debug("Failed to derive parent_step from result events", exc_info=True)
                    
                    if parent_step:
                        logger.info(f"COMPLETION_HANDLER: Child execution {exec_id} completed for parent {parent_execution_id} step {parent_step}")
                        print(f"completion handler: about to extract result for {exec_id}")
                    
                    # Extract result from the event
                    child_result = body.get('result')
                    print(f"completion handler: child_result from body = {child_result}")
                    if not child_result:
                        print(f"completion handler: no result in body, trying database lookup for {exec_id}")
                        # Try to get meaningful result from step results
                        from noetl.core.common import get_async_db_connection as get_db_conn
                        async with get_db_conn() as conn:
                            async with conn.cursor() as cur:
                                # Try to find meaningful results by step name priority
                                for step_name in ['evaluate_weather_step', 'evaluate_weather', 'alert_step', 'log_step']:
                                    print(f"completion handler: checking step {step_name} for results")
                                    await cur.execute(
                                        """
                                        SELECT result FROM noetl.event
                                        WHERE execution_id = %s
                                          AND node_name = %s
                                          AND event_type = 'action_completed'
                                          AND lower(status) IN ('completed','success')
                                          AND result IS NOT NULL
                                          AND result != '{}'
                                          AND NOT (result::text LIKE '%%"skipped": true%%')
                                          AND NOT (result::text LIKE '%%"reason": "control_step"%%')
                                        ORDER BY timestamp DESC
                                        LIMIT 1
                                        """,
                                        (exec_id, step_name)
                                    )
                                    result_row = await cur.fetchone()
                                    print(f"completion handler: step {step_name} result_row = {result_row}")
                                    if result_row:
                                        result_data = result_row[0] if isinstance(result_row, tuple) else result_row.get('result')
                                        try:
                                            import json
                                            child_result = json.loads(result_data) if isinstance(result_data, str) else result_data
                                            # Extract data if wrapped
                                            if isinstance(child_result, dict) and 'data' in child_result:
                                                child_result = child_result['data']
                                            break
                                        except Exception as e:
                                            print(f"completion handler: error parsing result for {step_name}: {e}")
                                            pass
                    
                    print(f"completion handler: final child_result = {child_result}")
                    
                    # Always proceed with completion check, even if no result
                    # Some executions may complete without returning meaningful data
                    if parent_execution_id and parent_step:
                        print(f"completion handler: proceeding with completion check for parent {parent_execution_id} step {parent_step}")
                        
                        if child_result:
                            # Find the iteration node_id pattern by looking up the loop_iteration event for this child
                            from noetl.core.common import get_async_db_connection as get_db_conn
                            async with get_db_conn() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                    """
                                    SELECT node_id, loop_id, loop_name, iterator, current_index, current_item 
                                    FROM noetl.event
                                    WHERE execution_id = %s
                                      AND event_type = 'loop_iteration'
                                      AND node_name = %s
                                      AND context LIKE %s
                                    ORDER BY timestamp DESC
                                    LIMIT 1
                                    """,
                                    (parent_execution_id, parent_step, f'%"child_execution_id": "{exec_id}"%')
                                )
                                    iter_row = await cur.fetchone()
                                    iter_node_id = None
                                    loop_metadata = {}
                                    if iter_row:
                                        if isinstance(iter_row, tuple):
                                            iter_node_id, loop_id, loop_name, iterator, current_index, current_item = iter_row
                                        else:
                                            iter_node_id = iter_row.get('node_id')
                                            loop_id = iter_row.get('loop_id')
                                            loop_name = iter_row.get('loop_name')
                                            iterator = iter_row.get('iterator')
                                            current_index = iter_row.get('current_index')
                                            current_item = iter_row.get('current_item')
                                        
                                        # Build loop metadata dict for action_completed event
                                        if loop_id:
                                            loop_metadata.update({
                                                'loop_id': loop_id,
                                                'loop_name': loop_name,
                                                'iterator': iterator,
                                                'current_index': current_index,
                                                'current_item': current_item
                                            })
                                    
                                    # Emit action_completed event for the parent loop to aggregate
                                    emit_data = {
                                        'execution_id': parent_execution_id,
                                        'event_type': 'action_completed',
                                        'status': 'COMPLETED',
                                        'node_id': iter_node_id or f'{parent_execution_id}-step-X-iter-{exec_id}',
                                        'node_name': parent_step,
                                        'node_type': 'task',
                                        'result': child_result,
                                        'context': {
                                            'child_execution_id': exec_id,
                                            'parent_step': parent_step,
                                            'return_step': None
                                        }
                                    }
                                    # Add loop metadata to the event if available
                                    emit_data.update(loop_metadata)
                                    
                                    await event_service.emit(emit_data)
                                    logger.info(f"COMPLETION_HANDLER: Emitted action_completed for parent {parent_execution_id} step {parent_step} from child {exec_id} with result: {child_result} and loop metadata: {loop_metadata}")
                        
                        # Always check if this completes a distributed loop, regardless of whether we have results
                        print(f"completion handler: calling distributed loop completion check for parent {parent_execution_id} step {parent_step}")
                        logger.info(f"COMPLETION_HANDLER: Calling distributed loop completion check for parent {parent_execution_id} step {parent_step}")
                        try:
                            await _check_distributed_loop_completion(parent_execution_id, parent_step)
                            print(f"completion handler: distributed loop completion check completed for parent {parent_execution_id}")
                        except Exception as e:
                            print(f"completion handler: error in distributed loop completion check: {e}")
                            logger.error(f"COMPLETION_HANDLER: Error in distributed loop completion check: {e}", exc_info=True)
                                
            except Exception as e:
                print(f"completion handler: Exception in completion handler: {e}")
                logger.debug("Failed to handle execution_completed event", exc_info=True)
        
        try:
            execution_id = result.get("execution_id") or body.get("execution_id")
            if execution_id:
                try:
                    asyncio.create_task(evaluate_broker_for_execution(execution_id))
                except Exception:
                    background_tasks.add_task(lambda eid=execution_id: _evaluate_broker_for_execution(eid))
        except Exception:
            pass
        return result
    except Exception as e:
        logger.exception(f"Error creating event: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating event: {e}."
        )


@router.get("/events/by-execution/{execution_id}", response_class=JSONResponse)
async def get_events_by_execution(
    request: Request,
    execution_id: str
):
    """
    Get all events for a specific execution.
    """
    try:
        from .service import get_event_service
        
        # Convert execution_id from string to int for database queries
        execution_id_int = snowflake_id_to_int(execution_id)
        
        event_service = get_event_service()
        events = await event_service.get_events_by_execution_id(execution_id_int)
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"No events found for execution '{execution_id}'."
            )
        # Convert snowflake IDs to strings for API compatibility
        events = convert_snowflake_ids_for_api(events)
        return events

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching events by execution: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching events by execution: {e}"
        )


@router.get("/events/by-id/{event_id}", response_class=JSONResponse)
async def get_event_by_id(
    request: Request,
    event_id: str
):
    """
    Get a single event by its ID.
    """
    try:
        from .service import get_event_service
        
        event_service = get_event_service()
        event = await event_service.get_event_by_id(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event with ID '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event by ID: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event by ID: {e}"
        )


@router.get("/events/{event_id}", response_class=JSONResponse)
async def get_event(
    request: Request,
    event_id: str
):
    """
    Legacy endpoint for getting events by execution_id or event_id.
    Use /events/by-execution/{execution_id} or /events/by-id/{event_id} instead.
    """
    try:
        from .service import get_event_service
        
        event_service = get_event_service()
        event = await event_service.get_event(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event: {e}"
        )


@router.get("/events/query", response_class=JSONResponse)
async def get_event_by_query(
    request: Request,
    event_id: Optional[str] = None
):
    if not event_id:
        raise HTTPException(
            status_code=400,
            detail="event_id query parameter is required."
        )

    try:
        from .service import get_event_service
        
        event_service = get_event_service()
        event = await event_service.get_event(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event: {e}."
        )
