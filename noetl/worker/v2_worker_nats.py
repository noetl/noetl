"""
NoETL V2 Worker with NATS Integration

Event-driven worker that:
1. Subscribes to NATS for command notifications
2. Fetches command details from server queue API  
3. Executes based on tool.kind
4. Emits events back to server (POST /api/v2/events)

NO backward compatibility - pure V2 implementation.
"""

import asyncio
import logging
import httpx
import os
from typing import Optional, Any
from datetime import datetime, timezone

from noetl.core.db.pool import get_pool_connection
from noetl.core.logger import setup_logger
from noetl.core.messaging import NATSCommandSubscriber

logger = setup_logger(__name__, include_location=True)


class V2Worker:
    """
    V2 Worker that receives command notifications from NATS and executes them.
    
    Architecture:
    - Subscribes to NATS subject for command notifications
    - Receives lightweight message with {execution_id, queue_id, step, server_url}
    - Fetches full command from server API
    - Executes tool based on tool.kind
    - Emits events to POST /api/v2/events
    - NEVER directly updates queue table (server does this via events)
    """
    
    def __init__(
        self,
        worker_id: str,
        nats_url: str = "nats://noetl:noetl@nats.nats.svc.cluster.local:4222",
        server_url: Optional[str] = None
    ):
        self.worker_id = worker_id
        self.nats_url = nats_url
        self.server_url = server_url  # Fallback, usually comes from notification
        self._running = False
        self._http_client: Optional[httpx.AsyncClient] = None
        self._nats_subscriber: Optional[NATSCommandSubscriber] = None
    
    async def start(self):
        """Start the worker NATS subscription."""
        self._running = True
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._nats_subscriber = NATSCommandSubscriber(
            nats_url=self.nats_url,
            consumer_name=f"worker-{self.worker_id}"
        )
        
        print(f"Worker {self.worker_id} starting...", flush=True)
        print(f"NATS URL: {self.nats_url}", flush=True)
        logger.info(f"Worker {self.worker_id} starting...")
        logger.info(f"NATS URL: {self.nats_url}")
        
        # Connect to NATS
        print("Connecting to NATS...", flush=True)
        await self._nats_subscriber.connect()
        print("Connected to NATS", flush=True)
        
        # Subscribe to command notifications (this should never return)
        print("Subscribing to command notifications...", flush=True)
        logger.info(f"Subscribing to command notifications...")
        await self._nats_subscriber.subscribe(self._handle_command_notification)
    
    async def cleanup(self):
        """Cleanup resources."""
        if self._nats_subscriber:
            await self._nats_subscriber.close()
        if self._http_client:
            await self._http_client.aclose()
        logger.info(f"Worker {self.worker_id} stopped")
    
    def stop(self):
        """Stop the worker."""
        self._running = False
    
    async def _handle_command_notification(self, notification: dict):
        """
        Handle command notification from NATS.
        
        Notification contains: {execution_id, queue_id, step, server_url}
        """
        try:
            execution_id = notification["execution_id"]
            queue_id = notification["queue_id"]
            step = notification["step"]
            server_url = notification["server_url"]
            
            logger.info(f"Received command: execution={execution_id}, queue={queue_id}, step={step}")
            
            # Fetch full command from server
            command = await self._fetch_command(server_url, queue_id)
            
            if not command:
                logger.warning(f"Command {queue_id} not found or already processed")
                return
            
            # Execute the command
            await self._execute_command(command, server_url)
            
        except Exception as e:
            logger.exception(f"Error handling command notification: {e}")
    
    async def _fetch_command(self, server_url: str, queue_id: int) -> Optional[dict]:
        """
        Fetch command from server queue API and lock it.
        
        Uses UPDATE...RETURNING to atomically lock the command.
        Returns command dict or None if not available.
        """
        try:
            response = await self._http_client.post(
                f"{server_url.rstrip('/')}/api/postgres/execute",
                json={
                    "procedure": """
                        UPDATE noetl.queue
                        SET status = 'running', 
                            worker_id = %s,
                            updated_at = NOW()
                        WHERE queue_id = %s
                          AND status = 'queued'
                        RETURNING queue_id, execution_id, node_id, action, context
                    """,
                    "parameters": [self.worker_id, queue_id],
                    "schema": "noetl"
                },
                timeout=10.0
            )
            response.raise_for_status()
            
            result = response.json()
            
            if result.get("status") == "ok" and result.get("result"):
                rows = result["result"]
                if rows:
                    # Parse result (queue_id, execution_id, node_id, action, context)
                    row = rows[0]
                    return {
                        "queue_id": row[0],
                        "execution_id": row[1],
                        "step": row[2],
                        "tool_kind": row[3],
                        "context": row[4]
                    }
            
            return None
            
        except Exception as e:
            logger.exception(f"Failed to fetch command {queue_id}: {e}")
            return None
    
    async def _execute_command(self, command: dict, server_url: str):
        """Execute a command and emit events."""
        execution_id = command["execution_id"]
        queue_id = command["queue_id"]  # Extract queue_id for error handling
        step = command["step"]
        tool_kind = command["tool_kind"]
        context = command["context"]
        
        # Store execution_id for sub-playbook calls
        self._current_execution_id = execution_id
        
        tool_config = context.get("tool_config", {})
        args = context.get("args", {})
        
        # CRITICAL: Merge tool_config.args with top-level args
        # In V2 DSL, step args are often defined within the tool block
        # e.g., tool: {kind: python, args: {name: "value"}, script: {...}}
        # The engine puts these in tool_config.args, but the worker needs them in args
        if "args" in tool_config:
            # Merge with top-level args taking precedence
            merged_args = {**tool_config["args"], **args}
            args = merged_args
            logger.error(f"DEBUG: Merged args from tool_config.args: {args}")
        else:
            logger.error(f"DEBUG: No args in tool_config, using top-level args: {args}")
        
        logger.info(f"Executing {step} (tool={tool_kind}) for execution {execution_id}")
        
        try:
            # Emit step.enter event
            await self._emit_event(
                server_url,
                execution_id,
                step,
                "step.enter",
                {"status": "started"}
            )
            
            # Execute tool
            response = await self._execute_tool(tool_kind, tool_config, args, step)
            
            # Emit call.done event
            await self._emit_event(
                server_url,
                execution_id,
                step,
                "call.done",
                {"response": response}
            )
            
            # Emit step.exit event
            await self._emit_event(
                server_url,
                execution_id,
                step,
                "step.exit",
                {"result": response, "status": "completed"}
            )
            
            logger.info(f"Completed {step} for execution {execution_id}")
            
        except Exception as e:
            logger.error(f"Execution error for {step}: {e}", exc_info=True)
            
            # Emit error event
            await self._emit_event(
                server_url,
                execution_id,
                step,
                "call.done",
                {"error": str(e)}
            )
            
            # Emit step.exit with error status
            await self._emit_event(
                server_url,
                execution_id,
                step,
                "step.exit",
                {
                    "status": "failed",
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            
            # Update queue status to failed
            try:
                await self._update_queue_status(queue_id, "failed", str(e))
            except Exception as update_err:
                logger.error(f"Failed to update queue status: {update_err}")
    
    async def _update_queue_status(self, queue_id: int, status: str, error: str = None):
        """Update queue item status."""
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                if error:
                    await cur.execute("""
                        UPDATE noetl.queue
                        SET status = %s,
                            updated_at = NOW(),
                            context = jsonb_set(
                                COALESCE(context, '{}'::jsonb),
                                '{error}',
                                to_jsonb(%s::text)
                            )
                        WHERE queue_id = %s
                    """, (status, error, queue_id))
                else:
                    await cur.execute("""
                        UPDATE noetl.queue
                        SET status = %s, updated_at = NOW()
                        WHERE queue_id = %s
                    """, (status, queue_id))
            await conn.commit()
    
    async def _execute_tool(
        self,
        tool_kind: str,
        config: dict,
        args: dict,
        step: str
    ) -> Any:
        """
        Execute tool using noetl/plugin/* implementations.
        
        This delegates to the mature plugin system which includes:
        - Script loading (GCS, S3, HTTP, file)
        - Authentication resolution and caching
        - Pagination and retry logic
        - Event callbacks for progress tracking
        - Template rendering
        - Error handling
        """
        # Import plugin executors
        from noetl.plugin import (
            execute_http_task,
            execute_postgres_task,
            execute_duckdb_task,
            execute_secrets_task,
            execute_sink_task,
            execute_workbook_task,
            execute_playbook_task,
        )
        # Import async version of Python executor
        from noetl.plugin.tools.python import execute_python_task_async
        from jinja2 import Environment, BaseLoader
        
        # Create minimal context for plugin execution
        # Plugins expect: task_config, context, jinja_env
        # V2 worker provides: config, args
        context = {"args": args, "step": step}
        jinja_env = Environment(loader=BaseLoader())
        
        # Map V2 config format to plugin task_config format
        # Plugins use different field names than V2 DSL
        task_config = {**config, "args": args, "name": step}
        
        if tool_kind == "python":
            # Use plugin's execute_python_task_async (not the sync wrapper!)
            # This includes:
            # - Script loading (GCS/S3/HTTP/file)
            # - Base64 code support
            # - Kwargs unpacking
            # - Error handling
            result = await execute_python_task_async(task_config, context, jinja_env, args)
            # Normalize result - plugin returns dict, may need to extract 'data' or 'result'
            if isinstance(result, dict):
                return result.get('data', result.get('result', result))
            return result
            
        elif tool_kind == "http":
            # Use plugin's execute_http_task which includes:
            # - Auth resolution and credential caching
            # - Pagination support
            # - Template rendering
            # - Response processing
            task_with = args  # Plugin uses 'task_with' for rendered params
            result = await execute_http_task(task_config, context, jinja_env, task_with)
            # Normalize result
            if isinstance(result, dict):
                return result.get('data', result)
            return result
            
        elif tool_kind == "postgres":
            # Use plugin's execute_postgres_task
            result = await execute_postgres_task(task_config, context, jinja_env, args)
            return result.get('data', result) if isinstance(result, dict) else result
            
        elif tool_kind == "duckdb":
            # Use plugin's execute_duckdb_task
            result = await execute_duckdb_task(task_config, context, jinja_env, args)
            return result.get('data', result) if isinstance(result, dict) else result
            
        elif tool_kind == "secrets":
            # Use plugin's execute_secrets_task
            result = await execute_secrets_task(task_config, context, jinja_env)
            return result
            
        elif tool_kind == "sink":
            # Use plugin's execute_sink_task
            result = await execute_sink_task(task_config, context, jinja_env)
            return result
            
        elif tool_kind == "workbook":
            # Use plugin's execute_workbook_task
            result = await execute_workbook_task(task_config, context, jinja_env, args)
            return result
            
        elif tool_kind == "playbook":
            # Use plugin's execute_playbook_task
            result = await execute_playbook_task(task_config, context, jinja_env, args)
            return result
            
        elif tool_kind == "container":
            # Container execution - keep inline for now as it's V2-specific
            return await self._execute_container(config, args)
            
        elif tool_kind == "script":
            # Script loading is now handled by python plugin via 'script' field
            # This is a legacy fallback
            return await self._execute_script(config, args)
            
        else:
            raise NotImplementedError(f"Tool kind '{tool_kind}' not implemented")
    
    async def _execute_python(self, config: dict, args: dict) -> Any:
        """Execute Python code."""
        import inspect
        
        # Priority: script > code_b64 > code
        code = config.get("code", "")
        
        # Handle script attribute (external code loading)
        if "script" in config:
            from noetl.worker.script_loader import load_script_content
            script_config = config["script"]
            code = await load_script_content(script_config)
        elif "code_b64" in config:
            import base64
            code = base64.b64decode(config["code_b64"]).decode("utf-8")
        
        if not code:
            raise ValueError("Python tool requires 'code', 'code_b64', or 'script' in config")
        
        # Execute code
        namespace = {"args": args}
        exec(code, namespace)
        
        # Call main() if it exists
        if "main" in namespace and callable(namespace["main"]):
            main_func = namespace["main"]
            sig = inspect.signature(main_func)
            
            # Determine how to call the function based on its signature
            if len(sig.parameters) == 0:
                # No parameters: call without args
                result = main_func()
            elif any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                # Has **kwargs: unpack args as keyword arguments
                result = main_func(**args)
            elif all(isinstance(args, dict) and (p.name in args or p.default != inspect.Parameter.empty) 
                     for p in sig.parameters.values() if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)):
                # All parameters can be satisfied by args dict keys or have defaults: unpack kwargs
                result = main_func(**args)
            else:
                # Pass args dict as single parameter (backward compatibility)
                result = main_func(args)
            
            # Await if it's a coroutine
            if inspect.iscoroutine(result):
                result = await result
            
            return result
        
        return {"status": "ok"}
    
    async def _execute_http(self, config: dict, args: dict) -> Any:
        """Execute HTTP request."""
        method = config.get("method", "GET").upper()
        url = config.get("url") or config.get("endpoint")
        headers = config.get("headers", {})
        params = config.get("params", {})
        json_body = config.get("json")
        
        if not url:
            raise ValueError("HTTP tool requires 'url' or 'endpoint' in config")
        
        # Debug logging
        logger.info(f"HTTP {method} request to URL: {url}")
        logger.info(f"  Headers: {headers}")
        logger.info(f"  Params: {params}")
        
        # Make request
        response = await self._http_client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body
        )
        response.raise_for_status()
        
        return {
            "status_code": response.status_code,
            "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        }
    
    async def _execute_postgres(self, config: dict, args: dict) -> Any:
        """Execute Postgres query with auth resolution."""
        query = config.get("query") or config.get("sql") or config.get("command")
        auth_spec = config.get("auth")
        
        if not query:
            raise ValueError("Postgres tool requires 'query', 'sql', or 'command' in config")
        
        # If no auth specified, use default connection
        if not auth_spec:
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, args if args else None)
                    
                    # Check if query returns results
                    if cur.description:
                        results = await cur.fetchall()
                        return [dict(row) for row in results]
                    else:
                        await conn.commit()
                        return {"status": "ok", "rowcount": cur.rowcount}
        
        # Resolve credentials via server API
        from noetl.worker.secrets import fetch_credential_by_key
        credential = fetch_credential_by_key(auth_spec)
        
        if not credential or not credential.get("data"):
            raise ValueError(f"Failed to resolve credential: {auth_spec}")
        
        # Extract connection parameters
        cred_data = credential.get("data", {})
        host = cred_data.get("db_host") or cred_data.get("host")
        port = cred_data.get("db_port") or cred_data.get("port") or 5432
        user = cred_data.get("db_user") or cred_data.get("user") or cred_data.get("username")
        password = cred_data.get("db_password") or cred_data.get("password")
        database = cred_data.get("db_name") or cred_data.get("database") or cred_data.get("dbname")
        
        if not all([host, user, password, database]):
            raise ValueError(f"Incomplete Postgres credentials for: {auth_spec}")
        
        # Create connection string
        import psycopg
        conn_string = f"host={host} port={port} user={user} password={password} dbname={database}"
        
        # Execute with credential-specific connection
        async with await psycopg.AsyncConnection.connect(conn_string) as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, args if args else None)
                
                # Check if query returns results
                if cur.description:
                    results = await cur.fetchall()
                    return [dict(row) for row in results]
                else:
                    await conn.commit()
                    return {"status": "ok", "rowcount": cur.rowcount}
    
    async def _execute_duckdb(self, config: dict, args: dict) -> Any:
        """Execute DuckDB query."""
        import duckdb
        
        query = config.get("query") or config.get("sql")
        database = config.get("database", ":memory:")
        
        if not query:
            raise ValueError("DuckDB tool requires 'query' or 'sql' in config")
        
        # Connect to database (can be :memory: or file path)
        conn = duckdb.connect(database)
        
        try:
            # Execute query
            result = conn.execute(query, args if args else None)
            
            # Check if query returns results
            if result.description:
                # Fetch all rows and convert to list of dicts
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()
                return [dict(zip(columns, row)) for row in rows]
            else:
                # For DML operations (INSERT, UPDATE, DELETE)
                return {"status": "ok", "rowcount": len(result.fetchall())}
        finally:
            conn.close()
    
    async def _execute_workbook(self, config: dict, args: dict) -> Any:
        """Execute a named task from the workbook section."""
        task_name = config.get("name")
        if not task_name:
            raise ValueError("Workbook execution requires 'name' in config")
        
        # Get workbook task definition from catalog
        # In V2, workbook tasks are stored in playbook.workbook section
        # For now, return error - requires catalog access
        raise NotImplementedError("Workbook tool execution requires catalog integration")
    
    async def _execute_playbook(self, config: dict, args: dict) -> Any:
        """Execute a sub-playbook."""
        path = config.get("path")
        return_step = config.get("return_step")
        
        if not path:
            raise ValueError("Playbook execution requires 'path' in config")
        
        # Call server to start sub-playbook execution
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")
        
        # Get server URL from config or environment
        server_url = os.getenv("SERVER_API_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        # Get current execution_id to pass as parent
        parent_execution_id = getattr(self, '_current_execution_id', None)
        
        payload = {"path": path, "payload": args}
        if parent_execution_id:
            payload["parent_execution_id"] = parent_execution_id
        
        response = await self._http_client.post(
            f"{server_url}/api/v2/execute",
            json=payload,
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()
        
        execution_id = result.get("execution_id")
        
        # Poll for sub-playbook completion if return_step is specified
        if return_step:
            max_wait = config.get("timeout", 300)  # Default 5 minutes
            poll_interval = 2  # seconds
            elapsed = 0
            
            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                # Check execution status
                status_response = await self._http_client.get(
                    f"{server_url}/api/v2/executions/{execution_id}/status",
                    timeout=10.0
                )
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    state = status_data.get("status")
                    
                    if state in ["completed", "failed", "error"]:
                        # Get result from return_step
                        if state == "completed" and return_step:
                            return status_data.get("steps", {}).get(return_step, {})
                        return status_data
            
            # Timeout - return what we have
            logger.warning(f"Sub-playbook {execution_id} timed out after {max_wait}s")
        
        # Async execution - return execution info immediately
        return {
            "status": "started",
            "execution_id": execution_id,
            "path": path,
            "async": return_step is None
        }
    
    async def _execute_secrets(self, config: dict, args: dict) -> Any:
        """Fetch secrets/credentials from secret manager."""
        secret_name = config.get("name")
        provider = config.get("provider", "env")  # env, aws, gcp, azure
        
        if not secret_name:
            raise ValueError("Secrets execution requires 'name' in config")
        
        if provider == "env":
            # Read from environment variable
            import os
            value = os.getenv(secret_name)
            if value is None:
                raise ValueError(f"Secret not found in environment: {secret_name}")
            return {"value": value}
        else:
            raise NotImplementedError(f"Secret provider '{provider}' not implemented")
    
    async def _execute_sink(self, config: dict, args: dict) -> Any:
        """Persist data to storage backend."""
        backend = config.get("backend", "postgres")
        table = config.get("table")
        data = config.get("data")
        connection = config.get("connection")
        
        if not table:
            raise ValueError("Sink execution requires 'table' in config")
        if not data:
            raise ValueError("Sink execution requires 'data' in config")
        
        if backend == "postgres":
            # Use postgres plugin to insert data
            from noetl.core.db.pool import get_pool_connection
            
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    # Normalize data to list of dicts
                    rows = data if isinstance(data, list) else [data]
                    
                    if not rows:
                        return {"status": "ok", "rows_inserted": 0}
                    
                    # Get column names from first row
                    columns = list(rows[0].keys())
                    placeholders = ", ".join(["%s"] * len(columns))
                    columns_str = ", ".join(columns)
                    
                    # Build INSERT statement
                    query = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
                    
                    # Execute for each row
                    for row in rows:
                        values = [row.get(col) for col in columns]
                        await cur.execute(query, values)
                    
                    return {"status": "ok", "rows_inserted": len(rows)}
        
        elif backend == "duckdb":
            # Use duckdb to insert data
            import duckdb
            
            # Create connection
            db_path = config.get("database", ":memory:")
            conn = duckdb.connect(db_path)
            
            try:
                # Normalize data
                rows = data if isinstance(data, list) else [data]
                
                if not rows:
                    return {"status": "ok", "rows_inserted": 0}
                
                # Get column names
                columns = list(rows[0].keys())
                placeholders = ", ".join(["?"] * len(columns))
                columns_str = ", ".join(columns)
                
                # Build INSERT statement
                query = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
                
                # Execute for each row
                for row in rows:
                    values = [row.get(col) for col in columns]
                    conn.execute(query, values)
                
                return {"status": "ok", "rows_inserted": len(rows)}
            finally:
                conn.close()
        
        else:
            raise NotImplementedError(f"Sink backend '{backend}' not implemented")
    
    async def _execute_container(self, config: dict, args: dict) -> Any:
        """Execute code in a container (Kubernetes Job)."""
        raise NotImplementedError(
            "Container execution is not yet implemented in V2 worker. "
            "This feature requires Kubernetes Job creation and monitoring. "
            "Please use Python/HTTP tools or submit a feature request."
        )
    
    async def _execute_script(self, config: dict, args: dict) -> Any:
        """Execute external script (deprecated - use Python with script attribute)."""
        raise NotImplementedError(
            "Script tool kind is deprecated. Use 'python' tool kind with 'script' attribute instead. "
            "Example: tool: {kind: python, script: {uri: 'gs://bucket/script.py', source: {type: gcs, auth: credential}}}"
        )
    
    async def _emit_event(
        self,
        server_url: str,
        execution_id: int,
        step: str,
        name: str,
        payload: dict
    ):
        """Emit an event to the server."""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")
        
        event_data = {
            "execution_id": str(execution_id),
            "step": step,
            "name": name,
            "payload": payload,
            "worker_id": self.worker_id
        }
        
        try:
            response = await self._http_client.post(
                f"{server_url.rstrip('/')}/api/v2/events",
                json=event_data,
                timeout=10.0
            )
            response.raise_for_status()
            
            logger.debug(f"Emitted event {name} for {step} (execution {execution_id})")
            
        except Exception as e:
            logger.error(f"Failed to emit event {name}: {e}")
            raise


async def run_v2_worker(
    worker_id: str,
    nats_url: str = "nats://noetl:noetl@nats.nats.svc.cluster.local:4222",
    server_url: Optional[str] = None
):
    """Run a V2 worker instance."""
    # Initialize database pool for postgres tool execution
    from noetl.core.db.pool import init_pool, close_pool
    from noetl.core.common import get_pgdb_connection
    await init_pool(get_pgdb_connection())
    logger.info("Database pool initialized")
    
    worker = V2Worker(
        worker_id=worker_id,
        nats_url=nats_url,
        server_url=server_url
    )
    
    try:
        await worker.start()  # Should run forever
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.error(f"Worker error: {e}", exc_info=True)
        raise
    finally:
        await worker.cleanup()
        await close_pool()
        logger.info("Worker cleanup complete")


def run_worker_v2_sync(
    nats_url: str = "nats://noetl:noetl@nats.nats.svc.cluster.local:4222",
    server_url: Optional[str] = None
):
    """
    Synchronous entry point for CLI.
    
    Generates worker ID and runs async worker in event loop.
    """
    import uuid
    import sys
    
    # Write to stderr BEFORE any other imports that might redirect stdout
    sys.stderr.write("=== WORKER ENTRY POINT ===\n")
    sys.stderr.flush()
    
    print("=== V2 Worker Starting ===", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    
    try:
        
        # Get from environment or use defaults
        nats_url = os.getenv("NATS_URL", nats_url)
        server_url = server_url or os.getenv("SERVER_API_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        
        with open("/tmp/worker_config.txt", "w") as f:
            f.write(f"Worker ID: {worker_id}\n")
            f.write(f"NATS URL: {nats_url}\n")
            f.write(f"Server URL: {server_url}\n")
            f.flush()
        
        print(f"Worker ID: {worker_id}", flush=True)
        print(f"NATS URL: {nats_url}", flush=True)
        print(f"Server URL: {server_url}", flush=True)
        
        logger.info(f"Starting V2 worker with ID: {worker_id}")
        logger.info(f"NATS URL: {nats_url}")
        logger.info(f"Server URL: {server_url}")
        
        with open("/tmp/worker_before_run.txt", "w") as f:
            f.write(f"About to call asyncio.run at {datetime.now()}\n")
            f.flush()
        
        asyncio.run(run_v2_worker(worker_id, nats_url, server_url))
        
        with open("/tmp/worker_after_run.txt", "w") as f:
            f.write(f"asyncio.run returned at {datetime.now()}\n")
            f.flush()
        
    except KeyboardInterrupt:
        with open("/tmp/worker_interrupt.txt", "w") as f:
            f.write(f"Interrupted at {datetime.now()}\n")
            f.flush()
        print("Worker interrupted by user", flush=True)
        logger.info("Worker interrupted by user")
        sys.exit(0)
    except Exception as e:
        with open("/tmp/worker_error.txt", "w") as f:
            f.write(f"Error at {datetime.now()}: {e}\n")
            import traceback
            f.write(traceback.format_exc())
            f.flush()
        
        print(f"Worker failed: {e}", flush=True)
        logger.error(f"Worker failed to start: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
