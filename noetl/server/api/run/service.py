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
from noetl.core.db.pool import get_pool
from noetl.core.logger import setup_logger
from noetl.server.api.broker import execute_playbook_via_broker
from .schema import ExecutionRequest, ExecutionResponse

logger = setup_logger(__name__, include_location=True)


class CatalogEntry(BaseModel):
    """Resolved catalog entry with all required metadata."""
    path: str
    version: str
    content: str
    catalog_id: str


class ResourceContent(BaseModel):
    catalog_id: str
    path: str
    version: int
    content: str

    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)


    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Path cannot be empty")
        return cleaned

    @field_validator("version", mode="before")
    @classmethod
    def parse_version(cls, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Version must be an integer") from exc

    @model_validator(mode="after")
    def validate_identifiers(self) -> "ResourceContent":
        if not self.catalog_id and not self.path:
            raise ValueError("Either catalog_id or path must be provided")
        return self

    @staticmethod
    def _build_query(        
        catalog_id: Optional[str] = None,
        path: Optional[str] = None,
        version: Optional[int] = None) -> tuple[str, Dict[str, Any]]:
        base_query = "SELECT catalog_id, path, version, content FROM noetl.catalog"
        params: Dict[str, Any] = {}

        if catalog_id:
            where_clause = "catalog_id = %(catalog_id)s"
            params["catalog_id"] = catalog_id
            order_clause = ""
        else:
            clauses = ["path = %(path)s"]
            params["path"] = path
            if version is not None:
                clauses.append("version = %(version)s")
                params["version"] = version
                order_clause = ""
            else:
                order_clause = "ORDER BY version DESC"
            where_clause = " AND ".join(clauses)

        parts = [f"{base_query} WHERE {where_clause}"]
        if order_clause:
            parts.append(order_clause)
        parts.append("LIMIT 1")

        return " ".join(parts), params

    @staticmethod
    async def get(
        catalog_id: Optional[str] = None,
        path: Optional[str] = None,
        version: Optional[int] = None
    ) -> "ResourceContent | None":
        """
        Execute a database query and return a single row.
        
        Args:
            query: SQL query string with named parameters
            params: Dictionary of named parameters
            
        Returns:
            Dictionary representing the row, or None if not found
            
        Raises:
            RuntimeError: If database error occurs
        """
        query, params = ResourceContent._build_query(
            catalog_id=catalog_id,
            path=path,
            version=version
        )
        async with get_pool().connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                return ResourceContent(**row) if row else None

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
    async def resolve_catalog_entry(request: ExecutionRequest) -> CatalogEntry:
        """
        Resolve catalog entry from request identifiers.
        
        Returns:
            CatalogEntry with resolved metadata
        
        Raises:
            ValueError: If catalog entry not found or invalid
            RuntimeError: If database error occurs
        """
        # Build lookup input from request
        
        resource_content = await ResourceContent.get(
            catalog_id=request.catalog_id,
            path=request.path,
            version=request.version
        )
        
        return resource_content
        
    
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
