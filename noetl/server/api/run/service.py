"""
NoETL Execution Service - Business logic for execution endpoints.

Handles catalog lookup, validation, and execution orchestration.
Separates business logic from endpoint routing concerns.
"""

import json
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
from fastapi import HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from noetl.core.common import AppBaseModel, deep_merge
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.server.api.catalog import CatalogService
from .schema import ExecutionRequest, ExecutionResponse
from .validation import PlaybookValidator, PlaybookValidationError
from .planner import ExecutionPlanner
from .events import ExecutionEventEmitter
from .publisher import QueuePublisher

logger = setup_logger(__name__, include_location=True)


# class CatalogEntry(AppBaseModel):
#     """Resolved catalog entry with all required metadata for execution."""
#     path: str
#     version: str
#     content: str
#     catalog_id: str


class ExecutionService:
    """
    Service class handling execution business logic.
    
    Responsibilities:
    - Resolve catalog entries from various identifiers
    - Validate playbook content
    - Build execution plan
    - Emit preliminary events
    - Publish initial tasks to queue
    """
    
    @staticmethod
    async def execute(request: ExecutionRequest, requestor_info: Optional[Dict[str, Any]] = None) -> ExecutionResponse:
        """
        Execute a playbook based on the request.
        
        Full execution flow:
        1. Resolve catalog entry (path/version or catalog_id)
        2. Generate execution_id
        3. Validate playbook content
        4. Build execution plan (workflow, transitions, workbook)
        5. Merge workload data
        6. Persist workload to workload table
        7. Emit execution start event
        8. Persist workflow/workbook/transitions
        9. Emit workflow initialized event
        10. Publish initial steps to queue
        
        Args:
            request: Validated execution request
            requestor_info: Optional requestor details (IP, user agent, etc.)
        
        Returns:
            ExecutionResponse with execution details
        
        Raises:
            HTTPException: If execution fails
        """
            # Add timestamp to requestor info
        if requestor_info:
            requestor_info['timestamp'] = datetime.utcnow().isoformat()
        
        # Step 1: Resolve catalog entry
        catalog_entry = await CatalogService.get(
            catalog_id=request.catalog_id,
            path=request.path,
            version=request.version
        )
        
        if not catalog_entry:
            identifier = request.catalog_id or f"{request.path}@{request.version or 'latest'}"
            raise HTTPException(
                status_code=404,
                detail=f"Catalog entry not found: {identifier}"
            )
        
        logger.debug(
            f"Executing: path={catalog_entry.path}, version={catalog_entry.version}, "
            f"catalog_id={catalog_entry.catalog_id}"
        )
        
        # Step 2: Generate execution_id from database snowflake function
        # This ensures the ID is available for caching/evaluation throughout the execution
        execution_id = await get_snowflake_id()
        logger.debug(f"Generated execution_id from database: {execution_id}")
        
        # Step 3: Validate playbook content
        try:
            playbook = PlaybookValidator.validate_and_parse(catalog_entry.content)
        except PlaybookValidationError as e:
            logger.error(f"Playbook validation failed: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid playbook: {e}")
        
        # Step 4: Build execution plan
        execution_plan = ExecutionPlanner.build_plan(playbook, execution_id)
        
        # Step 5: Merge workload data
        base_workload = PlaybookValidator.extract_workload(playbook)
        args = request.args or {}
        
        if request.merge and args:
            merged_workload = deep_merge(base_workload, args)
        else:
            merged_workload = {**base_workload, **args}
        
        # Step 6: Persist workload to workload table
        await ExecutionService._persist_workload(
            execution_id,
            catalog_entry.path,
            catalog_entry.version,
            merged_workload
        )
        
        # Step 7: Emit execution start event
        start_event_id = await ExecutionEventEmitter.emit_execution_start(
            execution_id=execution_id,
            catalog_id=catalog_entry.catalog_id,
            path=catalog_entry.path,
            version=str(catalog_entry.version),
            workload=merged_workload,
            parent_execution_id=request.context.parent_execution_id if request.context else None,
            parent_event_id=request.context.parent_event_id if request.context else None,
            requestor_info=requestor_info,
            metadata=request.metadata
        )
        
        # Step 8: Persist workflow/workbook/transitions
        await ExecutionEventEmitter.persist_workflow(execution_plan.workflow_steps)
        await ExecutionEventEmitter.persist_workbook(execution_plan.workbook_tasks)
        await ExecutionEventEmitter.persist_transitions(
            execution_id,
            execution_plan.transitions
        )
        
        # Step 9: Emit workflow initialized event
        workflow_event_id = await ExecutionEventEmitter.emit_workflow_initialized(
            execution_id=execution_id,
            catalog_id=catalog_entry.catalog_id,
            parent_event_id=start_event_id,
            step_count=len(execution_plan.workflow_steps),
            transition_count=len(execution_plan.transitions)
        )
        
        # Step 10: Publish initial steps to queue
        context = {
            "workload": merged_workload,
            "path": catalog_entry.path,
            "version": str(catalog_entry.version)
        }
        
        # Extract parent_execution_id from request context if this is a nested playbook call
        parent_execution_id = None
        if request.context and request.context.parent_execution_id:
            parent_execution_id = str(request.context.parent_execution_id)
        
        queue_ids = await QueuePublisher.publish_initial_steps(
            execution_id=execution_id,
            catalog_id=catalog_entry.catalog_id,
            initial_steps=execution_plan.initial_steps,
            workflow_steps=execution_plan.workflow_steps,
            parent_event_id=workflow_event_id,
            context=context,
            metadata=request.metadata,
            parent_execution_id=parent_execution_id
        )
        
        logger.info(
            f"Execution initiated: execution_id={execution_id}, "
            f"published {len(queue_ids)} initial tasks to queue"
        )
        
        # Build response
        execution_response = ExecutionResponse(
            execution_id=execution_id,
            catalog_id=catalog_entry.catalog_id,
            path=catalog_entry.path,
            name=catalog_entry.path.split("/")[-1],
            version=str(catalog_entry.version),
            type="playbook",
            status="running",
            timestamp=datetime.utcnow().isoformat(),
            progress=0,
            result={
                "execution_id": execution_id,
                "start_event_id": start_event_id,
                "workflow_event_id": workflow_event_id,
                "queue_ids": queue_ids,
                "initial_steps": execution_plan.initial_steps
            }
        )
        logger.debug(f"Execution created: execution_id={execution_id}")
        return execution_response

    @staticmethod
    async def _persist_workload(
        execution_id: str,
        path: str,
        version: str,
        workload: Dict[str, Any]
    ) -> None:
        """
        Persist workload to workload table.
        
        Args:
            execution_id: Execution identifier
            path: Playbook path
            version: Playbook version
            workload: Merged workload data
        """
        payload = {
            'path': path,
            'version': version,
            'workload': workload,
        }
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.workload (execution_id, data, created_at)
                    VALUES (%(execution_id)s, %(data)s, %(created_at)s)
                    """,
                    {
                        "execution_id": execution_id,
                        "data": json.dumps(payload),
                        "created_at": datetime.utcnow()
                    }
                )
        
        logger.debug(f"Persisted workload for execution {execution_id}")

