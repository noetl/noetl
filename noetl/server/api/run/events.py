"""
Event emission module for execution lifecycle.

Handles preliminary event registration in event table for:
- Execution start events
- Workflow initialization events
- Step preparation events
"""

from typing import Dict, Any, Optional, List
import json
from datetime import datetime
from psycopg.rows import dict_row
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class ExecutionEventEmitter:
    """
    Emits execution lifecycle events to event table.
    
    Responsibilities:
    - Emit execution start event
    - Persist workflow steps to workflow table
    - Persist workbook tasks to workbook table
    - Persist transitions to transition table
    """
    
    @staticmethod
    async def emit_execution_start(
        execution_id: str,
        catalog_id: str,
        path: str,
        version: str,
        workload: Dict[str, Any],
        parent_execution_id: Optional[str] = None,
        parent_event_id: Optional[str] = None,
        requestor_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Emit execution start event.
        
        Args:
            execution_id: Execution identifier
            catalog_id: Catalog entry ID
            path: Playbook path
            version: Playbook version
            workload: Merged workload data
            parent_execution_id: Optional parent execution
            parent_event_id: Optional parent event
            requestor_info: Optional requestor metadata (IP, user agent, etc.)
            
        Returns:
            event_id of the emitted event
        """
        # Generate event_id from database
        event_id = await get_snowflake_id()
        
        # Convert parent IDs to integers or None (database expects bigint)
        parent_execution_id_int = None
        if parent_execution_id:
            try:
                parent_execution_id_int = int(parent_execution_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid parent_execution_id: {parent_execution_id}, setting to None")
        
        parent_event_id_int = None
        if parent_event_id:
            try:
                parent_event_id_int = int(parent_event_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid parent_event_id: {parent_event_id}, setting to None")
        
        context = {
            "path": path,
            "version": version,
            "workload": workload
        }
        
        if parent_execution_id_int:
            context["parent_execution_id"] = parent_execution_id_int
        if parent_event_id_int:
            context["parent_event_id"] = parent_event_id_int
        
        meta = {
            "emitted_at": datetime.utcnow().isoformat(),
            "emitter": "execution_service"
        }
        
        if requestor_info:
            meta["requestor"] = requestor_info
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id,
                        catalog_id,
                        event_id,
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
                    ) VALUES (
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(event_id)s,
                        %(parent_event_id)s,
                        %(parent_execution_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(context)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_id": event_id,
                        "parent_event_id": parent_event_id_int,
                        "parent_execution_id": parent_execution_id_int,
                        "event_type": "execution_started",
                        "node_id": "playbook",
                        "node_name": path,
                        "node_type": "execution",
                        "status": "STARTED",
                        "context": json.dumps(context),
                        "meta": json.dumps(meta),
                        "created_at": datetime.utcnow()
                    }
                )
        
        logger.info(
            f"Emitted execution start event: execution_id={execution_id}, "
            f"event_id={event_id}, catalog_id={catalog_id}"
        )
        
        return event_id
    
    @staticmethod
    async def persist_workflow(
        workflow_steps: List[Dict[str, Any]]
    ) -> int:
        """
        Persist workflow steps to workflow table.
        
        Args:
            workflow_steps: List of workflow step records
            
        Returns:
            Number of steps persisted
        """
        if not workflow_steps:
            return 0
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Insert workflow steps
                for step in workflow_steps:
                    await cur.execute(
                        """
                        INSERT INTO noetl.workflow (
                            execution_id,
                            step_id,
                            step_name,
                            step_type,
                            description,
                            raw_config
                        ) VALUES (
                            %(execution_id)s,
                            %(step_id)s,
                            %(step_name)s,
                            %(step_type)s,
                            %(description)s,
                            %(raw_config)s
                        )
                        ON CONFLICT (execution_id, step_id) DO UPDATE SET
                            step_name = EXCLUDED.step_name,
                            step_type = EXCLUDED.step_type,
                            description = EXCLUDED.description,
                            raw_config = EXCLUDED.raw_config
                        """,
                        step
                    )
        
        logger.debug(f"Persisted {len(workflow_steps)} workflow steps")
        return len(workflow_steps)
    
    @staticmethod
    async def persist_workbook(
        workbook_tasks: List[Dict[str, Any]]
    ) -> int:
        """
        Persist workbook tasks to workbook table.
        
        Args:
            workbook_tasks: List of workbook task records
            
        Returns:
            Number of tasks persisted
        """
        if not workbook_tasks:
            return 0
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Insert workbook tasks
                for task in workbook_tasks:
                    await cur.execute(
                        """
                        INSERT INTO noetl.workbook (
                            execution_id,
                            task_id,
                            task_name,
                            task_type,
                            raw_config
                        ) VALUES (
                            %(execution_id)s,
                            %(task_id)s,
                            %(task_name)s,
                            %(task_type)s,
                            %(raw_config)s
                        )
                        ON CONFLICT (execution_id, task_id) DO UPDATE SET
                            task_name = EXCLUDED.task_name,
                            task_type = EXCLUDED.task_type,
                            raw_config = EXCLUDED.raw_config
                        """,
                        task
                    )
        
        logger.debug(f"Persisted {len(workbook_tasks)} workbook tasks")
        return len(workbook_tasks)
    
    @staticmethod
    async def persist_transitions(
        execution_id: str,
        transitions: List[Dict[str, Any]]
    ) -> int:
        """
        Persist step transitions to transition table.
        
        Args:
            execution_id: Execution identifier
            transitions: List of transition records
            
        Returns:
            Number of transitions persisted
        """
        if not transitions:
            return 0
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Insert transitions
                for trans in transitions:
                    await cur.execute(
                        """
                        INSERT INTO noetl.transition (
                            execution_id,
                            from_step,
                            to_step,
                            condition,
                            with_params
                        ) VALUES (
                            %(execution_id)s,
                            %(from_step)s,
                            %(to_step)s,
                            %(condition)s,
                            %(with_params)s
                        )
                        ON CONFLICT (execution_id, from_step, to_step, condition) DO UPDATE SET
                            with_params = EXCLUDED.with_params
                        """,
                        {
                            "execution_id": execution_id,
                            "from_step": trans["from_step"],
                            "to_step": trans["to_step"],
                            "condition": trans.get("condition", ""),
                            "with_params": json.dumps(trans.get("with_params", {}))
                        }
                    )
        
        logger.debug(f"Persisted {len(transitions)} transitions for execution {execution_id}")
        return len(transitions)
    
    @staticmethod
    async def emit_workflow_initialized(
        execution_id: str,
        catalog_id: str,
        parent_event_id: str,
        step_count: int,
        transition_count: int
    ) -> str:
        """
        Emit workflow initialization complete event.
        
        Args:
            execution_id: Execution identifier
            catalog_id: Catalog entry ID
            parent_event_id: Parent event ID (execution start event)
            step_count: Number of workflow steps
            transition_count: Number of transitions
            
        Returns:
            event_id of the emitted event
        """
        # Generate event_id from database
        event_id = await get_snowflake_id()
        
        context = {
            "step_count": step_count,
            "transition_count": transition_count
        }
        
        meta = {
            "emitted_at": datetime.utcnow().isoformat(),
            "emitter": "execution_service"
        }
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id,
                        catalog_id,
                        event_id,
                        parent_event_id,
                        event_type,
                        node_id,
                        node_name,
                        node_type,
                        status,
                        context,
                        meta,
                        created_at
                    ) VALUES (
                        %(execution_id)s,
                        %(catalog_id)s,
                        %(event_id)s,
                        %(parent_event_id)s,
                        %(event_type)s,
                        %(node_id)s,
                        %(node_name)s,
                        %(node_type)s,
                        %(status)s,
                        %(context)s,
                        %(meta)s,
                        %(created_at)s
                    )
                    """,
                    {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_id": event_id,
                        "parent_event_id": parent_event_id,
                        "event_type": "workflow_initialized",
                        "node_id": "workflow",
                        "node_name": "workflow",
                        "node_type": "workflow",
                        "status": "COMPLETED",
                        "context": json.dumps(context),
                        "meta": json.dumps(meta),
                        "created_at": datetime.utcnow()
                    }
                )
        
        logger.info(
            f"Emitted workflow initialized event: execution_id={execution_id}, "
            f"event_id={event_id}, steps={step_count}, transitions={transition_count}"
        )
        
        return event_id
