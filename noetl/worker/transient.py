"""
Variables cache service for execution-scoped runtime variables.

Provides execution-scoped variable storage with cache-like behavior:
- Execution isolation (variables scoped to execution_id)
- Access tracking (access_count, accessed_at)
- Mutable values (variables can be updated)
- Auto-cleanup on execution completion

Pattern follows auth_cache.py implementation.
Database access uses pool connection pattern (noetl.core.db.pool).
"""

from typing import Any, Dict, Optional
from datetime import datetime, timezone
import os
import httpx

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection, get_pool
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class TransientVars:
    """
    Variable cache service for execution-scoped runtime variables.
    
    Provides mutable variable storage during playbook execution with:
    - Execution-scoped isolation
    - Access tracking (read count and timestamps)
    - Type classification (user_defined, step_result, computed, iterator_state)
    - Source step tracking for debugging
    
    Similar to auth_cache but for runtime workflow state instead of credentials.
    
    ARCHITECTURE NOTE:
    - In worker context: uses server REST API (worker never accesses noetl schema directly)
    - In server context: uses direct database pool access
    """
    
    @staticmethod
    def _is_worker_context() -> bool:
        """Check if running in worker context (should use API) vs server context (should use DB)."""
        is_worker = os.getenv("NOETL_WORKER_MODE") == "true"
        logger.info(f"TransientVars: NOETL_WORKER_MODE={os.getenv('NOETL_WORKER_MODE')}, is_worker={is_worker}")
        return is_worker
    
    @staticmethod
    def _get_server_url() -> str:
        """Get server URL for API calls."""
        return os.getenv("SERVER_API_URL", "http://noetl.noetl.svc.cluster.local:8082")

    @staticmethod
    async def get_cached(
        var_name: str,
        execution_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve variable from cache and update access tracking.
        
        Uses server API when running in worker context (no pool), or direct DB when in server.
        
        Args:
            var_name: Variable name
            execution_id: Execution ID for scoping
            
        Returns:
            Dict with keys: value, type, source_step, created_at, accessed_at, access_count
            None if variable not found
        """
        # Check if running in worker context (use API) or server context (use DB)
        if TransientVars._is_worker_context():
            # Worker context - use server API
            server_url = TransientVars._get_server_url()
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        f"{server_url}/api/vars/{execution_id}/{var_name}"
                    )
                    if response.status_code == 200:
                        data = response.json()
                        logger.debug(
                            f"VAR: Retrieved '{var_name}' from server API "
                            f"(execution {execution_id})"
                        )
                        # API returns variable metadata directly (value, type, source_step, etc.)
                        return data
                    elif response.status_code == 404:
                        logger.debug(f"VAR: Cache miss for '{var_name}' (execution {execution_id})")
                        return None
                    else:
                        logger.warning(f"VAR: Server API returned {response.status_code} for '{var_name}'")
                        return None
            except Exception as e:
                logger.warning(f"VAR: Failed to get cached variable '{var_name}' via API: {e}")
                return None
        else:
            # Server context - use direct DB access
            try:
                async with get_pool_connection() as conn:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        # Retrieve and update access tracking in one query
                        await cur.execute(
                            """
                            UPDATE noetl.transient
                            SET 
                                access_count = access_count + 1,
                                accessed_at = NOW()
                            WHERE execution_id = %(execution_id)s 
                              AND var_name = %(var_name)s
                            RETURNING 
                                var_value as value,
                                var_type as type,
                                source_step,
                                created_at,
                                accessed_at,
                                access_count
                            """,
                            {"execution_id": execution_id, "var_name": var_name}
                        )
                        row = await cur.fetchone()
                        
                        if row:
                            logger.debug(
                                f"VAR: Retrieved '{var_name}' from DB cache "
                                f"(execution {execution_id}, access_count={row['access_count']})"
                            )
                            return dict(row)
                        else:
                            logger.debug(f"VAR: Cache miss for '{var_name}' (execution {execution_id})")
                            return None
                        
            except Exception as e:
                logger.warning(f"VAR: Failed to get cached variable '{var_name}': {e}")
                return None

    @staticmethod
    async def set_cached(
        var_name: str,
        var_value: Any,
        execution_id: int,
        var_type: str = 'user_defined',
        source_step: Optional[str] = None
    ) -> None:
        """
        Store or update variable in cache.
        
        Uses server API when running in worker context (no pool), or direct DB when in server.
        
        Args:
            var_name: Variable name
            var_value: Variable value (any JSON-serializable type)
            execution_id: Execution ID for scoping
            var_type: Variable classification (user_defined, step_result, computed, iterator_state)
            source_step: Step name that set/updated the variable
        """
        # Check if running in worker context (use API) or server context (use DB)
        if TransientVars._is_worker_context():
            # Worker context - use server API
            logger.info(f"TransientVars.set_cached: Using server API (execution {execution_id}, var={var_name})")
            server_url = TransientVars._get_server_url()
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{server_url}/api/vars/{execution_id}",
                        json={
                            "variables": {var_name: var_value},
                            "var_type": var_type,
                            "source_step": source_step
                        }
                    )
                    if response.status_code == 200:
                        logger.debug(
                            f"VAR: Set '{var_name}' via server API "
                            f"(execution {execution_id})"
                        )
                    else:
                        logger.warning(f"VAR: Server API returned {response.status_code} for set '{var_name}'")
            except Exception as e:
                logger.warning(f"VAR: Failed to set cached variable '{var_name}' via API: {e}")
        else:
            # Server context - use direct DB access
            try:
                async with get_pool_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            INSERT INTO noetl.transient (
                                execution_id,
                                var_name,
                                var_type,
                                var_value,
                                source_step,
                                created_at,
                                accessed_at,
                                access_count
                            ) VALUES (
                                %(execution_id)s, 
                                %(var_name)s, 
                                %(var_type)s, 
                                %(var_value)s, 
                                %(source_step)s, 
                                NOW(), 
                                NOW(), 
                                0
                            )
                            ON CONFLICT (execution_id, var_name)
                            DO UPDATE SET
                                var_value = EXCLUDED.var_value,
                                var_type = EXCLUDED.var_type,
                                source_step = EXCLUDED.source_step,
                                accessed_at = NOW()
                            """,
                            {
                                "execution_id": execution_id,
                                "var_name": var_name,
                                "var_type": var_type,
                                "var_value": Json(var_value),
                                "source_step": source_step
                            }
                        )
                        
                        logger.debug(f"VAR: Set '{var_name}' in DB cache (execution {execution_id})")
                        
            except Exception as e:
                logger.warning(f"VAR: Failed to set cached variable '{var_name}': {e}")

    @staticmethod
    async def get_all_vars(execution_id: int) -> Dict[str, Any]:
        """
        Get all variables for execution as flat dict.
        
        Does NOT update access tracking (bulk read operation).
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Dict mapping var_name to var_value: {var_name: value, ...}
            Empty dict if no variables found
        """
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT var_name, var_value
                        FROM noetl.transient
                        WHERE execution_id = %(execution_id)s
                        ORDER BY created_at
                        """,
                        {"execution_id": execution_id}
                    )
                    rows = await cur.fetchall()
                    
                    # Build flat dict: {var_name: value}
                    result = {}
                    for row in rows:
                        result[row['var_name']] = row['var_value']
                    
                    logger.debug(
                        f"VAR: Loaded {len(result)} variables for execution {execution_id}"
                    )
                    return result
                
        except Exception as e:
            logger.warning(f"VAR: Failed to get all variables for execution {execution_id}: {e}")
            return {}

    @staticmethod
    async def get_all_vars_with_metadata(execution_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Get all variables with full metadata.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Dict mapping var_name to metadata dict:
            {
                var_name: {
                    value: <value>,
                    type: <var_type>,
                    source_step: <step>,
                    created_at: <timestamp>,
                    accessed_at: <timestamp>,
                    access_count: <count>
                }
            }
        """
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT 
                            var_name,
                            var_value as value,
                            var_type as type,
                            source_step,
                            created_at,
                            accessed_at,
                            access_count
                        FROM noetl.transient
                        WHERE execution_id = %(execution_id)s
                        ORDER BY created_at
                        """,
                        {"execution_id": execution_id}
                    )
                    rows = await cur.fetchall()
                    
                    result = {row['var_name']: dict(row) for row in rows}
                    logger.debug(
                        f"VAR: Loaded {len(result)} variables with metadata for execution {execution_id}"
                    )
                    return result
                
        except Exception as e:
            logger.warning(
                f"VAR: Failed to get variables with metadata for execution {execution_id}: {e}"
            )
            return {}

    @staticmethod
    async def delete_var(
        var_name: str,
        execution_id: int
    ) -> bool:
        """
        Delete single variable.
        
        Args:
            var_name: Variable name to delete
            execution_id: Execution ID
            
        Returns:
            True if variable was deleted, False if not found
        """
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        DELETE FROM noetl.transient
                        WHERE execution_id = %(execution_id)s AND var_name = %(var_name)s
                        """,
                        {"execution_id": execution_id, "var_name": var_name}
                    )
                    deleted = cur.rowcount > 0
                    
                    if deleted:
                        logger.debug(f"VAR: Deleted variable '{var_name}' (execution {execution_id})")
                    else:
                        logger.debug(
                            f"VAR: Variable '{var_name}' not found for deletion (execution {execution_id})"
                        )
                    
                    return deleted
                
        except Exception as e:
            logger.error(f"VAR: Failed to delete variable '{var_name}': {e}")
            return False

    @staticmethod
    async def cleanup_execution(execution_id: int) -> int:
        """
        Delete all variables for execution.
        
        Called when execution completes to clean up execution-scoped variables.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Number of variables deleted
        """
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        DELETE FROM noetl.transient
                        WHERE execution_id = %(execution_id)s
                        """,
                        {"execution_id": execution_id}
                    )
                    count = cur.rowcount
                    
                    logger.info(f"VAR: Cleaned up {count} variables for execution {execution_id}")
                    return count
                
        except Exception as e:
            logger.error(f"VAR: Failed to cleanup variables for execution {execution_id}: {e}")
            return 0

    @staticmethod
    async def set_multiple(
        variables: Dict[str, Any],
        execution_id: int,
        var_type: str = 'user_defined',
        source_step: Optional[str] = None
    ) -> int:
        """
        Set multiple variables in a single transaction.
        
        Args:
            variables: Dict of {var_name: var_value}
            execution_id: Execution ID
            var_type: Variable type for all variables
            source_step: Source step for all variables
            
        Returns:
            Number of variables set
        """
        if not variables:
            return 0
            
        try:
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    count = 0
                    for var_name, var_value in variables.items():
                        await cur.execute(
                            """
                            INSERT INTO noetl.transient (
                                execution_id,
                                var_name,
                                var_type,
                                var_value,
                                source_step,
                                created_at,
                                accessed_at,
                                access_count
                            ) VALUES (
                                %(execution_id)s, 
                                %(var_name)s, 
                                %(var_type)s, 
                                %(var_value)s, 
                                %(source_step)s, 
                                NOW(), 
                                NOW(), 
                                0
                            )
                            ON CONFLICT (execution_id, var_name)
                            DO UPDATE SET
                                var_value = EXCLUDED.var_value,
                                var_type = EXCLUDED.var_type,
                                source_step = EXCLUDED.source_step,
                                accessed_at = NOW()
                            """,
                            {
                                "execution_id": execution_id,
                                "var_name": var_name,
                                "var_type": var_type,
                                "var_value": Json(var_value),
                                "source_step": source_step
                            }
                        )
                        count += 1
                    
                    logger.debug(
                        f"VAR: Set {count} variables "
                        f"(execution {execution_id}, type={var_type}, source={source_step})"
                    )
                    return count
                
        except Exception as e:
            logger.error(f"VAR: Failed to set multiple variables: {e}")
            raise
