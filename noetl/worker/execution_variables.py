"""
Execution Variable Management for NoETL Workers.

Provides execution-scoped variable storage for:
- Step results (automatic)
- Bearer tokens (from auth system)
- Computed values
- User-defined variables

Variables are accessible via Jinja2 templates during playbook execution
and automatically cleaned up when execution completes.

Example usage in playbooks:

1. Bearer token with variable assignment:
   ```yaml
   - step: get_token
     tool: python
     auth:
       credential: oauth_creds
       bearer: true
       variable: my_token
     
   - step: use_token
     tool: http
     headers:
       Authorization: Bearer {{ my_token }}
   ```

2. Step results (automatic):
   ```yaml
   - step: fetch_data
     tool: http
     endpoint: https://api.example.com/data
   
   - step: process
     tool: python
     args:
       data: '{{ fetch_data.data }}'
   ```
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any
from datetime import datetime, timezone

from psycopg.types.json import Json
from noetl.core.common import get_async_db_connection

logger = logging.getLogger(__name__)


class ExecutionVariables:
    """Execution-scoped variable storage and retrieval."""
    
    @staticmethod
    async def set_variable(
        execution_id: int,
        variable_name: str,
        variable_value: Any,
        variable_type: str = 'user_defined',
        source_step: Optional[str] = None
    ) -> bool:
        """
        Store a variable for the execution scope.
        
        Args:
            execution_id: Execution ID
            variable_name: Variable name (accessible in templates)
            variable_value: Variable value (any JSON-serializable type)
            variable_type: Type of variable (step_result, bearer_token, computed, user_defined)
            source_step: Step name that produced this variable
            
        Returns:
            True if successfully stored
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO noetl.execution_variable (
                            execution_id, variable_name, variable_type,
                            variable_value, source_step
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (execution_id, variable_name) DO UPDATE SET
                            variable_value = EXCLUDED.variable_value,
                            variable_type = EXCLUDED.variable_type,
                            source_step = EXCLUDED.source_step,
                            updated_at = now()
                        """,
                        (
                            execution_id, variable_name, variable_type,
                            Json(variable_value), source_step
                        )
                    )
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning (may auto-commit): {e}")
            
            logger.debug(
                f"Stored execution variable '{variable_name}' "
                f"(type: {variable_type}, execution: {execution_id})"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to store execution variable: {e}")
            return False
    
    @staticmethod
    async def get_variable(
        execution_id: int,
        variable_name: str
    ) -> Optional[Any]:
        """
        Retrieve a variable value for the execution scope.
        
        Args:
            execution_id: Execution ID
            variable_name: Variable name
            
        Returns:
            Variable value or None if not found
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT variable_value, variable_type
                        FROM noetl.execution_variable
                        WHERE execution_id = %s
                          AND variable_name = %s
                        """,
                        (execution_id, variable_name)
                    )
                    row = await cursor.fetchone()
                    
                    if row:
                        value, var_type = row
                        logger.debug(
                            f"Retrieved execution variable '{variable_name}' "
                            f"(type: {var_type})"
                        )
                        return value
                    
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to retrieve execution variable: {e}")
            return None
    
    @staticmethod
    async def get_all_variables(execution_id: int) -> Dict[str, Any]:
        """
        Retrieve all variables for the execution scope.
        
        Useful for building Jinja2 context with all available variables.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Dictionary mapping variable names to values
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT variable_name, variable_value
                        FROM noetl.execution_variable
                        WHERE execution_id = %s
                        ORDER BY created_at ASC
                        """,
                        (execution_id,)
                    )
                    rows = await cursor.fetchall() or []
                    
                    variables = {row[0]: row[1] for row in rows}
                    
                    logger.debug(
                        f"Retrieved {len(variables)} execution variables "
                        f"for execution {execution_id}"
                    )
                    return variables
                    
        except Exception as e:
            logger.error(f"Failed to retrieve execution variables: {e}")
            return {}
    
    @staticmethod
    async def set_bearer_token(
        execution_id: int,
        variable_name: str,
        token_value: str,
        source_step: str
    ) -> bool:
        """
        Store a bearer token as an execution variable.
        
        Convenience method for auth system to store tokens.
        
        Args:
            execution_id: Execution ID
            variable_name: Variable name (e.g., 'amadeus_token')
            token_value: Token value
            source_step: Step that generated the token
            
        Returns:
            True if successfully stored
        """
        return await ExecutionVariables.set_variable(
            execution_id=execution_id,
            variable_name=variable_name,
            variable_value=token_value,
            variable_type='bearer_token',
            source_step=source_step
        )
    
    @staticmethod
    async def set_step_result(
        execution_id: int,
        step_name: str,
        result: Any
    ) -> bool:
        """
        Store a step result as an execution variable.
        
        Automatically called by step executors to make results
        available to subsequent steps via {{ step_name.field }}.
        
        Args:
            execution_id: Execution ID
            step_name: Step name
            result: Step result (dict, list, string, etc.)
            
        Returns:
            True if successfully stored
        """
        return await ExecutionVariables.set_variable(
            execution_id=execution_id,
            variable_name=step_name,
            variable_value=result,
            variable_type='step_result',
            source_step=step_name
        )
    
    @staticmethod
    async def cleanup_execution(execution_id: int) -> bool:
        """
        Clean up all variables for an execution.
        
        Called when playbook execution completes.
        
        Args:
            execution_id: Execution ID to clean up
            
        Returns:
            True if cleanup succeeded
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        DELETE FROM noetl.execution_variable
                        WHERE execution_id = %s
                        """,
                        (execution_id,)
                    )
                    deleted = cursor.rowcount
                    
                    if deleted > 0:
                        logger.info(
                            f"Cleaned up {deleted} execution variable(s) "
                            f"for execution {execution_id}"
                        )
                    
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning (may auto-commit): {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to cleanup execution variables: {e}")
            return False


async def extend_context_with_variables(
    context: Dict[str, Any],
    execution_id: int
) -> Dict[str, Any]:
    """
    Extend Jinja2 context with execution variables.
    
    Called before rendering templates to make variables available.
    
    Args:
        context: Existing context dictionary
        execution_id: Execution ID
        
    Returns:
        Extended context with variables merged in
    """
    variables = await ExecutionVariables.get_all_variables(execution_id)
    
    # Merge variables into context (variables take precedence)
    extended = context.copy()
    extended.update(variables)
    
    return extended


__all__ = [
    'ExecutionVariables',
    'extend_context_with_variables'
]
