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
        5.5. Process keychain section (create keychain entries)
        6. Emit execution start event
        7. Persist workflow/workbook/transitions
        8. Emit workflow initialized event
        9. Publish initial steps to queue
        
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
        
        # Step 3: Use catalog entry payload (already validated and parsed at registration)
        playbook = catalog_entry.payload
        if not playbook:
            # Fallback to parsing content if payload is None (shouldn't happen with modern catalog)
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
        
        # Step 5.5: Process keychain section before workflow starts
        keychain_section = playbook.get('keychain')
        if keychain_section and catalog_entry.catalog_id:
            logger.info(f"EXECUTION: Processing keychain section with {len(keychain_section)} entries")
            from noetl.server.keychain_processor import process_keychain_section
            try:
                keychain_data = await process_keychain_section(
                    keychain_section=keychain_section,
                    catalog_id=int(catalog_entry.catalog_id),
                    execution_id=int(execution_id),
                    workload_vars=merged_workload
                )
                logger.info(f"EXECUTION: Keychain processing complete, created {len(keychain_data)} entries")
            except Exception as e:
                logger.error(f"EXECUTION: Failed to process keychain section: {e}", exc_info=True)
                # Don't fail execution, keychain errors will surface when workers try to resolve
        
        # Step 6: Emit execution start event
        logger.critical(f"DEBUG: BEFORE emit_execution_start")
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
        logger.critical(f"DEBUG: AFTER emit_execution_start, start_event_id={start_event_id}")
        
        # Step 7: Persist workflow/workbook/transitions
        logger.critical(f"DEBUG SERVICE: About to persist workflow_steps, count={len(execution_plan.workflow_steps)}")
        logger.critical(f"DEBUG SERVICE: workflow_steps[0] keys={execution_plan.workflow_steps[0].keys() if execution_plan.workflow_steps else 'empty'}")
        try:
            await ExecutionEventEmitter.persist_workflow(execution_plan.workflow_steps)
            logger.critical(f"DEBUG SERVICE: Completed persist_workflow")
        except Exception as e:
            logger.critical(f"DEBUG SERVICE: Error in persist_workflow: {type(e).__name__}: {e}")
            raise
        
        try:
            await ExecutionEventEmitter.persist_workbook(execution_plan.workbook_tasks)
            logger.critical(f"DEBUG SERVICE: Completed persist_workbook")
        except Exception as e:
            logger.critical(f"DEBUG SERVICE: Error in persist_workbook: {type(e).__name__}: {e}")
            raise
        
        try:
            await ExecutionEventEmitter.persist_transitions(
                execution_id,
                execution_plan.transitions
            )
            logger.critical(f"DEBUG SERVICE: Completed persist_transitions")
        except Exception as e:
            logger.critical(f"DEBUG SERVICE: Error in persist_transitions: {type(e).__name__}: {e}")
            raise
        
        # Step 9: Emit workflow initialized event
        workflow_event_id = await ExecutionEventEmitter.emit_workflow_initialized(
            execution_id=execution_id,
            catalog_id=catalog_entry.catalog_id,
            parent_event_id=start_event_id,
            step_count=len(execution_plan.workflow_steps),
            transition_count=len(execution_plan.transitions)
        )
        
        # Step 9: Publish initial steps to queue
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
            f"Execution initiated: execution_id={execution_id}, queue subsystem removed; "
            f"initial tasks not enqueued"
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

