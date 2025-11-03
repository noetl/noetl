"""
NoETL Event Service - Database operations for event emission.

Simple event emission service without business logic - direct database operations only.
Similar pattern to run/catalog services.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from psycopg.rows import dict_row
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger
from .schema import EventEmitRequest, EventEmitResponse, EventQuery, EventResponse, EventListResponse


logger = setup_logger(__name__, include_location=True)


class EventService:
    """Service for event emission and retrieval operations."""
    
    @staticmethod
    async def emit_event(request: EventEmitRequest) -> EventEmitResponse:
        """
        Emit an event to the event log.
        
        Args:
            request: Event emission request
            
        Returns:
            EventEmitResponse with event_id and confirmation
        """
        # Generate event_id if not provided
        if request.event_id:
            event_id = int(request.event_id)
        else:
            event_id = await get_snowflake_id()
        
        # Convert IDs to integers for database (BIGINT columns)
        execution_id = int(request.execution_id)
        catalog_id = int(request.catalog_id) if request.catalog_id else None
        parent_event_id = int(request.parent_event_id) if request.parent_event_id else None
        parent_execution_id = int(request.parent_execution_id) if request.parent_execution_id else None
        
        # Defense-in-depth: resolve catalog_id from execution if missing
        # This prevents event insert failures and lost telemetry
        if catalog_id is None and execution_id:
            try:
                catalog_id = await EventService.get_catalog_id_from_execution(execution_id)
                logger.debug(f"Resolved missing catalog_id={catalog_id} from execution_id={execution_id}")
            except Exception as e:
                logger.warning(f"Failed to resolve catalog_id for execution {execution_id}: {e}")
        
        # Use provided timestamp or generate new one
        created_at = request.created_at or datetime.utcnow()
        
        # Prepare context, meta, and result as JSON
        context = Json(request.context) if request.context else None
        meta = Json(request.meta) if request.meta else None
        result = Json(request.result) if request.result else None
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        event_id,
                        execution_id,
                        catalog_id,
                        parent_event_id,
                        parent_execution_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        duration,
                        context,
                        result,
                        error,
                        stack_trace,
                        meta,
                        created_at
                    ) VALUES (
                        %(event_id)s,
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(parent_event_id)s,
                        %(parent_execution_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(duration)s,
                        %(context)s,
                        %(result)s,
                        %(error)s,
                        %(stack_trace)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "event_id": event_id,
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "parent_event_id": parent_event_id,
                        "parent_execution_id": parent_execution_id,
                        "event_type": request.event_type,
                        "node_id": request.node_id,
                        "node_name": request.node_name,
                        "node_type": request.node_type,
                        "status": request.status,
                        "duration": request.duration,
                        "context": context,
                        "result": result,
                        "error": request.error,
                        "stack_trace": request.stack_trace,
                        "meta": meta,
                        "created_at": created_at,
                    }
                )
                await conn.commit()
        
        logger.info(
            f"Event emitted: event_id={event_id}, execution_id={execution_id}, "
            f"type={request.event_type}, status={request.status}"
        )
        
        return EventEmitResponse(
            event_id=str(event_id),
            execution_id=str(execution_id),
            event_type=request.event_type,
            status="emitted",
            created_at=created_at.isoformat()
        )
    
    @staticmethod
    async def get_event(event_id: str) -> Optional[EventResponse]:
        """
        Retrieve a single event by ID.
        
        Args:
            event_id: Event identifier
            
        Returns:
            EventResponse or None if not found
        """
        event_id_int = int(event_id)
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT
                        event_id,
                        execution_id,
                        catalog_id,
                        parent_event_id,
                        parent_execution_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        context,
                        meta,
                        created_at
                    FROM noetl.event
                    WHERE event_id = %(event_id)s
                    """,
                    {"event_id": event_id_int}
                )
                
                row = await cur.fetchone()
                
                if not row:
                    return None
                
                return EventResponse(
                    event_id=str(row['event_id']),
                    execution_id=str(row['execution_id']),
                    catalog_id=str(row['catalog_id']) if row['catalog_id'] else None,
                    parent_event_id=str(row['parent_event_id']) if row['parent_event_id'] else None,
                    parent_execution_id=str(row['parent_execution_id']) if row['parent_execution_id'] else None,
                    event_type=row['event_type'],
                    node_id=row['node_id'],
                    node_name=row['node_name'],
                    node_type=row['node_type'],
                    status=row['status'],
                    context=row['context'],
                    meta=row['meta'],
                    created_at=row['created_at'].isoformat() if row['created_at'] else None
                )
    
    @staticmethod
    async def list_events(query: EventQuery) -> EventListResponse:
        """
        List events with filtering and pagination.
        
        Args:
            query: Query parameters
            
        Returns:
            EventListResponse with paginated results
        """
        # Build WHERE clause
        where_clauses = []
        params = {}
        
        if query.execution_id:
            where_clauses.append("execution_id = %(execution_id)s")
            params["execution_id"] = int(query.execution_id)
        
        if query.catalog_id:
            where_clauses.append("catalog_id = %(catalog_id)s")
            params["catalog_id"] = int(query.catalog_id)
        
        if query.event_type:
            where_clauses.append("event_type = %(event_type)s")
            params["event_type"] = query.event_type
        
        if query.status:
            where_clauses.append("status = %(status)s")
            params["status"] = query.status
        
        if query.parent_execution_id:
            where_clauses.append("parent_execution_id = %(parent_execution_id)s")
            params["parent_execution_id"] = int(query.parent_execution_id)
        
        if query.node_name:
            where_clauses.append("node_name = %(node_name)s")
            params["node_name"] = query.node_name
        
        if query.start_time:
            where_clauses.append("created_at >= %(start_time)s")
            params["start_time"] = query.start_time
        
        if query.end_time:
            where_clauses.append("created_at <= %(end_time)s")
            params["end_time"] = query.end_time
        
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Add pagination
        params["limit"] = query.limit
        params["offset"] = query.offset
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Get total count
                count_sql = f"""
                    SELECT COUNT(*) as total
                    FROM noetl.event
                    {where_sql}
                """
                await cur.execute(count_sql, params)
                count_row = await cur.fetchone()
                total = count_row['total'] if count_row else 0
                
                # Get paginated results
                list_sql = f"""
                    SELECT
                        event_id,
                        execution_id,
                        catalog_id,
                        parent_event_id,
                        parent_execution_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        context,
                        meta,
                        created_at
                    FROM noetl.event
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                """
                
                await cur.execute(list_sql, params)
                rows = await cur.fetchall()
                
                items = [
                    EventResponse(
                        event_id=str(row['event_id']),
                        execution_id=str(row['execution_id']),
                        catalog_id=str(row['catalog_id']) if row['catalog_id'] else None,
                        parent_event_id=str(row['parent_event_id']) if row['parent_event_id'] else None,
                        parent_execution_id=str(row['parent_execution_id']) if row['parent_execution_id'] else None,
                        event_type=row['event_type'],
                        node_id=row['node_id'],
                        node_name=row['node_name'],
                        node_type=row['node_type'],
                        status=row['status'],
                        context=row['context'],
                        meta=row['meta'],
                        created_at=row['created_at'].isoformat() if row['created_at'] else None
                    )
                    for row in rows
                ]
                
                has_more = (query.offset + query.limit) < total
                
                return EventListResponse(
                    items=items,
                    total=total,
                    limit=query.limit,
                    offset=query.offset,
                    has_more=has_more
                )
    
    @staticmethod
    async def get_catalog_id_from_execution(execution_id: int | str) -> int:
        """
        Get catalog_id from the first event of an execution.
        
        This is useful for queue operations that need to associate jobs with catalogs.
        
        Args:
            execution_id: Execution ID (int or string)
            
        Returns:
            Catalog ID as integer
            
        Raises:
            ValueError: If no catalog_id found for the execution
        """
        execution_id_int = int(execution_id)
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT catalog_id 
                    FROM noetl.event 
                    WHERE execution_id = %(execution_id)s 
                    ORDER BY created_at 
                    LIMIT 1
                    """,
                    {"execution_id": execution_id_int}
                )
                row = await cur.fetchone()
                
                if row and row['catalog_id']:
                    return int(row['catalog_id'])
                else:
                    raise ValueError(f"No catalog_id found for execution {execution_id}")
    
    @staticmethod
    async def get_earliest_context(execution_id: int | str) -> Optional[Dict[str, Any]]:
        """
        Get the context from the earliest event of an execution.
        
        Useful for retrieving initial workload configuration.
        
        Args:
            execution_id: Execution ID (int or string)
            
        Returns:
            Context dictionary from the first event, or None if not found
        """
        execution_id_int = int(execution_id)
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT context 
                    FROM noetl.event 
                    WHERE execution_id = %(execution_id)s 
                    ORDER BY created_at ASC 
                    LIMIT 1
                    """,
                    {"execution_id": execution_id_int}
                )
                row = await cur.fetchone()
                return row['context'] if row else None
    
    @staticmethod
    async def get_all_node_results(execution_id: int | str) -> Dict[str, Any]:
        """
        Get all node results from events for an execution.
        
        Returns a map of node_name -> result for all events with non-empty results.
        
        Args:
            execution_id: Execution ID (int or string)
            
        Returns:
            Dictionary mapping node names to their results
        """
        execution_id_int = int(execution_id)
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT node_name, result 
                    FROM noetl.event 
                    WHERE execution_id = %(execution_id)s 
                      AND result IS NOT NULL 
                      AND result != '{}'::jsonb 
                      AND result != 'null'::jsonb
                    ORDER BY created_at ASC
                    """,
                    {"execution_id": execution_id_int}
                )
                rows = await cur.fetchall()
                
                # Build map of node_name -> result
                results = {}
                for row in rows:
                    if row['node_name']:
                        results[row['node_name']] = row['result']
                
                return results


__all__ = ["EventService"]
