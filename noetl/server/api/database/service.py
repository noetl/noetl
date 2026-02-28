"""
NoETL Database API Service - Business logic for database operations.

Handles:
- Query execution
- Stored procedure calls
- Result retrieval and formatting
- Credential-based connections
- Custom database connections
"""

from typing import Optional, Any
from fastapi import HTTPException
from noetl.core.common import get_async_db_connection, get_pgdb_connection
from noetl.core.logger import setup_logger
from psycopg.rows import dict_row
from noetl.server.api.credential.service import CredentialService
from .schema import (
    PostgresExecuteRequest,
    PostgresExecuteResponse,
    WeatherAlertSummaryResponse,
    WeatherAlertSummaryRow,
    AuthSessionValidateRequest,
    AuthSessionValidateResponse,
    AuthSessionUser,
)

logger = setup_logger(__name__)


class DatabaseService:
    """Service class for database operations."""
    
    @staticmethod
    async def _resolve_connection_string(request: PostgresExecuteRequest) -> Optional[str]:
        """
        Resolve connection string from request parameters.
        
        Priority:
        1. connection_string (explicit full connection string)
        2. credential (credential name from credential table)
        3. database (database name with default credentials)
        4. None (use default connection)
        
        Args:
            request: PostgreSQL execution request
            
        Returns:
            Connection string or None for default
        """
        # Priority 1: Explicit connection string
        if request.connection_string:
            return request.connection_string
        
        # Priority 2: Credential from credential table
        if request.credential:
            try:
                credential_obj = await CredentialService.get_credential(
                    request.credential,
                    include_data=True,
                )
                credential_data = {
                    "type": credential_obj.type,
                    "data": credential_obj.data or {},
                }
                
                if not credential_data or credential_data.get('type') != 'postgres':
                    raise HTTPException(
                        status_code=400,
                        detail=f"Credential '{request.credential}' not found or not a postgres credential"
                    )
                
                data = credential_data.get('data', {})
                db_name = data.get('db_name') or data.get('database')
                user = data.get('db_user') or data.get('user')
                password = data.get('db_password') or data.get('password')
                host = data.get('db_host') or data.get('host')
                port = data.get('db_port') or data.get('port')
                schema = request.db_schema or data.get('db_schema') or data.get('schema', 'public')
                
                if not all([db_name, user, password, host, port]):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Credential '{request.credential}' missing required fields"
                    )
                
                return f"dbname={db_name} user={user} password={password} host={host} port={port} options='-c search_path={schema}'"
                
            except HTTPException:
                raise
            except Exception as e:
                logger.exception(f"Error loading credential '{request.credential}': {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load credential: {str(e)}"
                )
        
        # Priority 3: Database name with default credentials
        if request.database:
            return get_pgdb_connection(
                db_name=request.database,
                schema=request.db_schema
            )
        
        # Priority 4: Default connection
        return None
    
    @staticmethod
    async def execute_postgres(request: PostgresExecuteRequest) -> PostgresExecuteResponse:
        """
        Execute a PostgreSQL query or stored procedure.
        
        Args:
            request: PostgreSQL execution request
            
        Returns:
            PostgresExecuteResponse with results or error
            
        Raises:
            HTTPException: If validation fails
        """
        # Validate that either query or procedure is provided
        if not request.query and not request.procedure:
            raise HTTPException(
                status_code=400,
                detail="query or procedure is required"
            )
        
        try:
            # Resolve connection string from request
            connection_string = await DatabaseService._resolve_connection_string(request)
            
            async with get_async_db_connection(connection_string=connection_string) as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    result = None
                    
                    if request.query:
                        if request.parameters is not None:
                            params = request.parameters
                            if isinstance(params, dict):
                                await cursor.execute(request.query, params)
                            elif isinstance(params, (list, tuple)):
                                await cursor.execute(request.query, params)
                            else:
                                await cursor.execute(request.query, (params,))
                        else:
                            await cursor.execute(request.query)
                        try:
                            result = await cursor.fetchall()
                        except Exception:
                            result = None
                    
                    elif request.procedure:
                        if isinstance(request.parameters, (list, tuple)):
                            await cursor.execute(request.procedure, request.parameters)
                        else:
                            await cursor.execute(request.procedure)
                        try:
                            result = await cursor.fetchall()
                        except Exception:
                            result = None
                    
                    # Commit transaction
                    try:
                        await conn.commit()
                        logger.debug("Database API transaction committed successfully")
                    except Exception as e:
                        logger.error(f"Database API commit failed: {e}")
                        raise
            
            return PostgresExecuteResponse(
                status="ok",
                result=result
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error executing database operation: {e}")
            return PostgresExecuteResponse(
                status="error",
                error=str(e)
            )

    @staticmethod
    async def validate_auth_session(request: AuthSessionValidateRequest) -> AuthSessionValidateResponse:
        """
        Validate auth session token against auth schema.

        Uses dedicated query path (no dynamic SQL from caller).
        """
        token = (request.session_token or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail="session_token is required")

        try:
            connection_request = PostgresExecuteRequest(
                credential=request.credential or "pg_auth"
            )
            connection_string = await DatabaseService._resolve_connection_string(connection_request)

            async with get_async_db_connection(connection_string=connection_string) as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                          s.user_id,
                          u.email,
                          COALESCE(NULLIF(u.display_name, ''), u.email) AS display_name,
                          s.expires_at::text AS expires_at,
                          COALESCE(
                            (
                              SELECT json_agg(r.role_name ORDER BY r.role_name)
                              FROM auth.user_roles ur
                              JOIN auth.roles r ON ur.role_id = r.role_id
                              WHERE ur.user_id = s.user_id
                                AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
                            ),
                            '[]'::json
                          ) AS roles
                        FROM auth.sessions s
                        JOIN auth.users u ON u.user_id = s.user_id
                        WHERE s.session_token = %s
                          AND s.is_active = TRUE
                          AND u.is_active = TRUE
                          AND s.expires_at > NOW()
                        LIMIT 1
                        """,
                        (token,)
                    )
                    row = await cursor.fetchone()

            if not row:
                return AuthSessionValidateResponse(
                    status="ok",
                    valid=False,
                    user=None,
                    expires_at=None,
                )

            roles = row.get("roles")
            if not isinstance(roles, list):
                roles = []

            return AuthSessionValidateResponse(
                status="ok",
                valid=True,
                user=AuthSessionUser(
                    user_id=int(row.get("user_id") or 0),
                    email=str(row.get("email") or ""),
                    display_name=str(row.get("display_name") or row.get("email") or ""),
                    roles=[str(r) for r in roles if r is not None],
                ),
                expires_at=str(row.get("expires_at") or ""),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error validating auth session: {e}")
            return AuthSessionValidateResponse(
                status="error",
                valid=False,
                user=None,
                expires_at=None,
                error=str(e)
            )
    
    @staticmethod
    async def get_last_weather_alert_summary(
        execution_id: str
    ) -> WeatherAlertSummaryResponse:
        """
        Get the last weather alert summary row for a given execution.
        
        This is an example endpoint showing how to query specific tables.
        
        Args:
            execution_id: Execution ID to filter by
            
        Returns:
            WeatherAlertSummaryResponse with row data or error
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT id, alert_cities, alert_count, execution_id, created_at
                        FROM public.weather_alert_summary
                        WHERE execution_id = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (execution_id,)
                    )
                    row_dict = await cur.fetchone()
                    
                    if row_dict:
                        row = WeatherAlertSummaryRow(**row_dict)
                        return WeatherAlertSummaryResponse(
                            status="ok",
                            row=row
                        )
                    else:
                        return WeatherAlertSummaryResponse(
                            status="ok",
                            row=None
                        )
                    
        except Exception as e:
            logger.exception(f"Error retrieving weather alert summary: {e}")
            return WeatherAlertSummaryResponse(
                status="error",
                error=str(e)
            )
