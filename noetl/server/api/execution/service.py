"""
NoETL Execution Service - Business logic for execution endpoints.

Handles catalog lookup, validation, and execution orchestration.
Separates business logic from endpoint routing concerns.
"""

import json
from typing import Dict, Any, Tuple, Optional
from fastapi import HTTPException
from noetl.core.logger import setup_logger
from noetl.core.common import get_async_db_connection
from noetl.server.api.broker import execute_playbook_via_broker
from .schema import ExecutionRequest, ExecutionResponse

logger = setup_logger(__name__, include_location=True)


class ExecutionService:
    """
    Service class handling execution business logic.
    
    Responsibilities:
    - Resolve catalog entries from various identifiers
    - Validate execution requests
    - Orchestrate playbook/tool/model execution
    - Persist execution metadata
    """
    
    @staticmethod
    async def resolve_catalog_entry(request: ExecutionRequest) -> Tuple[str, str, str, Optional[str]]:
        """
        Resolve catalog entry from request identifiers.
        
        Returns:
            Tuple of (path, version, content, catalog_id)
        
        Raises:
            HTTPException: If catalog entry not found or invalid
        """
        catalog_id = request.catalog_id
        path = request.path
        version = request.version or "latest"
        execution_type = request.type
        
        logger.debug(
            f"Resolving catalog entry: catalog_id={catalog_id}, "
            f"path={path}, version={version}, type={execution_type}"
        )
        
        # Strategy 1: catalog_id lookup
        if catalog_id:
            logger.debug(f"Using catalog_id lookup: {catalog_id}")
            
            row = None
            db_error = None
            
            try:
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT catalog_id, path, version, content
                            FROM noetl.catalog
                            WHERE catalog_id = %s
                            """,
                            (catalog_id,)
                        )
                        row = await cur.fetchone()
            except Exception as e:
                logger.error(f"Database error during catalog_id lookup: {e}")
                db_error = e
            
            # Check results after context manager exits
            if db_error:
                raise HTTPException(
                    status_code=500,
                    detail=f"Database error: {str(db_error)}"
                )
            
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Catalog entry with ID '{catalog_id}' not found"
                )
            
            catalog_id_result, path_result, version_result, content = row
            logger.info(
                f"Resolved by catalog_id: path={path_result} (type: {type(path_result).__name__}), "
                f"version={version_result} (type: {type(version_result).__name__}), "
                f"catalog_id={catalog_id_result} (type: {type(catalog_id_result).__name__})"
            )
            # Convert to strings for schema compatibility
            path_str = str(path_result)
            version_str = str(version_result)
            catalog_id_str = str(catalog_id_result)
            logger.info(
                f"After conversion: path={path_str} (type: {type(path_str).__name__}), "
                f"version={version_str} (type: {type(version_str).__name__}), "
                f"catalog_id={catalog_id_str} (type: {type(catalog_id_str).__name__})"
            )
            return path_str, version_str, content, catalog_id_str
        
        # Strategy 2: Path + version lookup
        if path:
            logger.debug(f"Using path+version lookup: path={path}, version={version}")
            
            row = None
            db_error = None
            
            try:
                if version == "latest":
                    # Get latest version for this path
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                SELECT catalog_id, version, content
                                FROM noetl.catalog
                                WHERE path = %s
                                ORDER BY created_at DESC
                                LIMIT 1
                                """,
                                (path,)
                            )
                            row = await cur.fetchone()
                else:
                    # Get specific version
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                SELECT catalog_id, content
                                FROM noetl.catalog
                                WHERE path = %s AND version = %s
                                """,
                                (path, version)
                            )
                            row = await cur.fetchone()
            except Exception as e:
                logger.error(f"Database error during path lookup: {e}")
                db_error = e
            
            # Check results after context manager exits
            if db_error:
                raise HTTPException(
                    status_code=500,
                    detail=f"Database error: {str(db_error)}"
                )
            
            if not row:
                if version == "latest":
                    raise HTTPException(
                        status_code=404,
                        detail=f"No catalog entries found for path '{path}'"
                    )
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Catalog entry '{path}' with version '{version}' not found"
                    )
            
            if version == "latest":
                catalog_id_result, version_result, content = row
                logger.debug(
                    f"Resolved latest version: version={version_result}, "
                    f"catalog_id={catalog_id_result}"
                )
                # Convert to strings for schema compatibility
                return path, str(version_result), content, str(catalog_id_result)
            else:
                catalog_id_result, content = row
                logger.debug(
                    f"Resolved specific version: catalog_id={catalog_id_result}"
                )
                # Convert to strings for schema compatibility
                return path, version, content, str(catalog_id_result)
        
        # Should never reach here due to request validation, but just in case
        raise HTTPException(
            status_code=400,
            detail="No valid identifier provided (catalog_id, path, or playbook_id required)"
        )
    
    @staticmethod
    async def execute(request: ExecutionRequest) -> ExecutionResponse:
        """
        Execute a playbook/tool/model based on the request.
        
        Args:
            request: Validated execution request
        
        Returns:
            ExecutionResponse with execution details
        
        Raises:
            HTTPException: If execution fails
        """
        try:
            # Resolve catalog entry
            path, version, content, catalog_id = await ExecutionService.resolve_catalog_entry(request)
            logger.info(
                f"After resolve_catalog_entry: path={path} (type: {type(path).__name__}), "
                f"version={version} (type: {type(version).__name__}), "
                f"catalog_id={catalog_id} (type: {type(catalog_id).__name__})"
            )
            
            logger.debug(
                f"Executing: path={path}, version={version}, "
                f"type={request.type}, catalog_id={catalog_id}"
            )
            
            # Prepare execution parameters
            parameters = request.parameters or {}
            merge = request.merge
            sync_to_postgres = request.sync_to_postgres
            
            # Extract context
            context = request.context
            parent_execution_id = context.parent_execution_id if context else None
            parent_event_id = context.parent_event_id if context else None
            parent_step = context.parent_step if context else None
            
            # Execute via broker
            result = execute_playbook_via_broker(
                playbook_content=content,
                playbook_path=path,
                playbook_version=version,
                input_payload=parameters,
                sync_to_postgres=sync_to_postgres,
                merge=merge,
                parent_execution_id=parent_execution_id,
                parent_event_id=parent_event_id,
                parent_step=parent_step
            )
            
            # Persist workload record for server-side tracking
            exec_id = result.get("execution_id")
            if exec_id and sync_to_postgres:
                await ExecutionService.persist_workload(exec_id, parameters)
            
            # Build response - ensure all fields are proper types
            execution_response = ExecutionResponse(
                execution_id=str(exec_id) if exec_id else "",
                catalog_id=str(catalog_id) if catalog_id is not None else None,
                path=str(path) if path else None,
                playbook_id=str(path) if path else None,  # For backward compatibility
                playbook_name=path.split("/")[-1] if path else None,
                version=str(version) if version else None,
                type=request.type,
                status="running",
                timestamp=result.get("timestamp", ""),
                progress=0,
                result=result if not sync_to_postgres else None
            )
            
            logger.debug(f"Execution created: execution_id={exec_id}")
            return execution_response
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error executing request: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def persist_workload(execution_id: str, parameters: Dict[str, Any]) -> None:
        """
        Persist workload data for an execution.
        
        Args:
            execution_id: Execution ID
            parameters: Execution parameters to persist
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO workload (execution_id, data)
                        VALUES (%s, %s)
                        ON CONFLICT (execution_id) DO UPDATE SET data = EXCLUDED.data
                        """,
                        (execution_id, json.dumps(parameters or {}))
                    )
                    try:
                        await conn.commit()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Failed to persist workload for execution {execution_id}: {e}")


async def execute_request(request: ExecutionRequest) -> ExecutionResponse:
    """
    Main entry point for execution service.
    
    Args:
        request: Validated execution request
    
    Returns:
        ExecutionResponse with execution details
    """
    return await ExecutionService.execute(request)
