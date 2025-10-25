"""
NoETL Execution Service - Business logic for execution endpoints.

Handles catalog lookup, validation, and execution orchestration.
Separates business logic from endpoint routing concerns.
"""

import json
from typing import Dict, Any, Tuple, Optional
from fastapi import HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from noetl.core.common import AppBaseModel
from noetl.core.db.pool import get_pool
from noetl.core.logger import setup_logger
from noetl.server.api.broker import execute_playbook_via_broker
from noetl.server.api.catalog import CatalogService
from .schema import ExecutionRequest, ExecutionResponse

logger = setup_logger(__name__, include_location=True)


# class CatalogEntry(AppBaseModel):
#     """Resolved catalog entry with all required metadata for execution."""
#     path: str
#     version: str
#     content: str
#     catalog_id: str


class ExecutionService:
#     """
#     Service class handling execution business logic.
    
#     Responsibilities:
#     - Resolve catalog entries from various identifiers
#     - Validate execution requests
#     - Orchestrate playbook/tool/model execution
#     - Persist execution metadata
#     """
    
#     @staticmethod
#     async def resolve_catalog_entry(request: ExecutionRequest) -> CatalogEntry:
#         """
#         Resolve catalog entry from request identifiers.
        
#         Returns:
#             CatalogEntry with resolved metadata
        
#         Raises:
#             ValueError: If catalog entry not found or invalid
#             RuntimeError: If database error occurs
#         """
#         # Use CatalogService to resolve the entry
#         catalog_entry = await CatalogService.resolve_catalog_entry(
#             catalog_id=request.catalog_id,
#             path=request.path,
#             version=request.version
#         )
        
#         # Convert to execution-specific CatalogEntry
#         return CatalogEntry(
#             path=catalog_entry.path,
#             version=catalog_entry.version,
#             content=catalog_entry.content,
#             catalog_id=catalog_entry.catalog_id
#         )
        
    
    @staticmethod
    async def execute(request: ExecutionRequest, requestor_info: Optional[Dict[str, Any]] = None) -> ExecutionResponse:
        """
        Execute a playbook/tool/model based on the request.
        
        Args:
            request: Validated execution request
            requestor_info: Optional requestor details (IP, user agent, etc.)
        
        Returns:
            ExecutionResponse with execution details
        
        Raises:
            HTTPException: If execution fails
        """
        try:
            # Add timestamp to requestor info
            from datetime import datetime
            if requestor_info:
                requestor_info['timestamp'] = datetime.utcnow().isoformat()
            
            # Resolve catalog entry
            entry = await ExecutionService.resolve_catalog_entry(request)
            
            logger.debug(
                f"Executing: path={entry.path}, version={entry.version}, "
                f"type={request.type}, catalog_id={entry.catalog_id}"
            )
            
            # Prepare execution parameters
            parameters = request.parameters or {}
            merge = request.merge
            
            # Extract context
            context = request.context
            parent_execution_id = context.parent_execution_id if context else None
            parent_event_id = context.parent_event_id if context else None
            parent_step = context.parent_step if context else None

            
            execution_id = await ExecutionService.create_workload(
                entry.path, entry.version, parameters
            )
            # Execute via broker
            result = execute_playbook_via_broker(
                execution_id=execution_id,
                playbook_content=entry.content,
                playbook_path=entry.path,
                playbook_version=entry.version,
                input_payload=parameters,
                merge=merge,
                parent_execution_id=parent_execution_id,
                parent_event_id=parent_event_id,
                parent_step=parent_step,
                requestor_info=requestor_info
            )

            
            # Build response - ensure all fields are proper types
            execution_response = ExecutionResponse(
                execution_id=str(execution_id),
                catalog_id=entry.catalog_id,
                path=entry.path,
                playbook_id=entry.path,  # For backward compatibility
                playbook_name=entry.path.split("/")[-1],
                version=entry.version,
                type=request.type,
                status="running",
                timestamp=result.get("timestamp", ""),
                progress=0,
                result=result
            )

            logger.debug(f"Execution created: execution_id={execution_id}")
            return execution_response
            
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            raise HTTPException(status_code=404, detail=str(e))
        except RuntimeError as e:
            logger.error(f"Runtime error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error executing request: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def create_workload(path: str, version: str, workload: Dict[str, Any] | None) -> int:
        payload = {
            'path': path,
            'version': version,
            'workload': workload or {},
        }
        async with get_pool().connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO noetl.workload (data) VALUES (%(data)s) RETURNING execution_id",
                    {"data": json.dumps(payload)},
                )
                return (await cur.fetchone())["execution_id"]



async def execute_request(request: ExecutionRequest, requestor_info: Optional[Dict[str, Any]] = None) -> ExecutionResponse:
    """
    Main entry point for execution service.
    
    Args:
        request: Validated execution request
        requestor_info: Optional requestor details (IP, user agent, etc.)
    
    Returns:
        ExecutionResponse with execution details
    """
    return await ExecutionService.execute(request, requestor_info)
