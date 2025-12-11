"""
NoETL V2 Worker

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
    - Receives lightweight message with queue_id and server_url
    - Fetches full command from server API
    - Executes tool based on tool.kind
    - Emits events to POST /api/v2/events
    - NEVER directly updates queue table
    """
    
    def __init__(
        self,
        worker_id: str,
        nats_url: str = "nats://noetl:noetl@nats.nats.svc.cluster.local:4222",
        server_url: Optional[str] = None
    ):
        self.worker_id = worker_id
        self.nats_url = nats_url
        self.server_url = server_url  # Can be overridden per command
        self._running = False
        self._http_client: Optional[httpx.AsyncClient] = None
        self._nats_subscriber: Optional[NATSCommandSubscriber] = None
    
    async def start(self):
        """Start the worker polling loop."""
        self._running = True
        self._http_client = httpx.AsyncClient(timeout=30.0)
        
        logger.info(f"V2 Worker {self.worker_id} starting...")
        logger.info(f"Server URL: {self.server_url}")
        logger.info(f"Poll interval: {self.poll_interval}s")
        
        try:
            while self._running:
                try:
                    await self._poll_and_execute()
                except Exception as e:
                    logger.error(f"Error in worker loop: {e}", exc_info=True)
                
                await asyncio.sleep(self.poll_interval)
        finally:
            if self._http_client:
                await self._http_client.aclose()
    
    def stop(self):
        """Stop the worker."""
        logger.info(f"V2 Worker {self.worker_id} stopping...")
        self._running = False
    
    async def _poll_and_execute(self):
        """Poll queue for commands and execute."""
        # Lease a command from queue
        command = await self._lease_command()
        
        if not command:
            return
        
        queue_id = command['queue_id']
        execution_id = command['execution_id']
        step = command['node_id']
        tool_kind = command['action']
        context = command['context']
        
        logger.info(f"Executing command {queue_id}: {step} ({tool_kind})")
        
        try:
            # Execute the tool
            result = await self._execute_tool(
                tool_kind=tool_kind,
                config=context.get('tool_config', {}),
                args=context.get('args', {}),
                step=step
            )
            
            # Emit call.done event (success)
            await self._emit_event(
                execution_id=execution_id,
                step=step,
                name="call.done",
                payload={
                    "response": result,
                    "meta": {
                        "queue_id": queue_id,
                        "tool_kind": tool_kind,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
            
            # Emit step.exit event
            await self._emit_event(
                execution_id=execution_id,
                step=step,
                name="step.exit",
                payload={
                    "result": result,
                    "meta": {
                        "queue_id": queue_id,
                        "completed": True
                    }
                }
            )
            
            logger.info(f"Command {queue_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Command {queue_id} failed: {e}", exc_info=True)
            
            # Emit call.done event (error)
            await self._emit_event(
                execution_id=execution_id,
                step=step,
                name="call.done",
                payload={
                    "error": {
                        "message": str(e),
                        "type": type(e).__name__,
                        "status": getattr(e, 'status_code', None)
                    },
                    "meta": {
                        "queue_id": queue_id,
                        "tool_kind": tool_kind,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
    
    async def _lease_command(self) -> Optional[dict]:
        """Lease a command from the queue table."""
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Find and lock an available command
                await cur.execute("""
                    UPDATE noetl.queue
                    SET status = 'running',
                        updated_at = %s
                    WHERE queue_id = (
                        SELECT queue_id
                        FROM noetl.queue
                        WHERE status = 'queued'
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING queue_id, execution_id, catalog_id, node_id,
                              action, context, attempts, max_attempts
                """, (datetime.now(timezone.utc),))
                
                result = await cur.fetchone()
                await conn.commit()
                
                return dict(result) if result else None
    
    async def _execute_tool(
        self,
        tool_kind: str,
        config: dict,
        args: dict,
        step: str
    ) -> Any:
        """Execute a tool based on kind."""
        if tool_kind == "python":
            return await self._execute_python(config, args)
        elif tool_kind == "http":
            return await self._execute_http(config, args)
        elif tool_kind == "postgres":
            return await self._execute_postgres(config, args)
        elif tool_kind == "duckdb":
            return await self._execute_duckdb(config, args)
        else:
            raise NotImplementedError(f"Tool kind '{tool_kind}' not implemented")
    
    async def _execute_python(self, config: dict, args: dict) -> Any:
        """Execute Python code."""
        code = config.get('code', '')
        
        if not code:
            raise ValueError("Python tool requires 'code' field")
        
        # Create execution environment
        exec_globals = {
            '__builtins__': __builtins__,
            'args': args,
            **args  # Make args available at top level
        }
        
        # Execute the code
        exec(code, exec_globals)
        
        # Get the main function
        if 'main' in exec_globals:
            main_func = exec_globals['main']
            
            # Call main with args if it accepts parameters
            import inspect
            sig = inspect.signature(main_func)
            
            if sig.parameters:
                # Pass args as kwargs
                if inspect.iscoroutinefunction(main_func):
                    result = await main_func(**args)
                else:
                    result = main_func(**args)
            else:
                # No parameters
                if inspect.iscoroutinefunction(main_func):
                    result = await main_func()
                else:
                    result = main_func()
            
            return result
        else:
            raise ValueError("Python code must define a 'main' function")
    
    async def _execute_http(self, config: dict, args: dict) -> Any:
        """Execute HTTP request."""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")
        
        method = config.get('method', 'GET').upper()
        endpoint = config.get('endpoint') or config.get('url')
        headers = config.get('headers', {})
        params = config.get('params', {})
        body = config.get('body')
        
        if not endpoint:
            raise ValueError("HTTP tool requires 'endpoint' or 'url'")
        
        # Make request
        response = await self._http_client.request(
            method=method,
            url=endpoint,
            headers=headers,
            params=params,
            json=body if body else None
        )
        
        # Return wrapped response
        return {
            "status": response.status_code,
            "data": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
            "headers": dict(response.headers)
        }
    
    async def _execute_postgres(self, config: dict, args: dict) -> Any:
        """Execute PostgreSQL query."""
        command = config.get('command') or config.get('query')
        auth = config.get('auth')
        
        if not command:
            raise ValueError("Postgres tool requires 'command' or 'query'")
        
        # For now, use default connection pool
        # TODO: Support auth-based connection pools
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(command, args if args else None)
                
                # Check if it's a SELECT query
                if command.strip().upper().startswith('SELECT'):
                    rows = await cur.fetchall()
                    return [dict(row) for row in rows]
                else:
                    await conn.commit()
                    return {"affected_rows": cur.rowcount}
    
    async def _execute_duckdb(self, config: dict, args: dict) -> Any:
        """Execute DuckDB query."""
        # TODO: Implement DuckDB execution
        raise NotImplementedError("DuckDB execution not yet implemented")
    
    async def _emit_event(
        self,
        execution_id: str,
        step: str,
        name: str,
        payload: dict
    ):
        """Emit an event to the server."""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")
        
        event_data = {
            "execution_id": execution_id,
            "step": step,
            "name": name,
            "payload": payload,
            "worker_id": self.worker_id
        }
        
        try:
            response = await self._http_client.post(
                f"{self.server_url}/api/v2/events",
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
    server_url: str = "http://localhost:8082",
    poll_interval: int = 2
):
    """Run a V2 worker instance."""
    worker = V2Worker(
        worker_id=worker_id,
        server_url=server_url,
        poll_interval=poll_interval
    )
    
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
        worker.stop()
    except Exception as e:
        logger.error(f"Worker error: {e}", exc_info=True)
        worker.stop()
        raise


def run_worker_v2_sync(server_url: str = "http://localhost:8082", poll_interval: int = 2):
    """
    Synchronous entry point for CLI.
    
    Generates worker ID and runs async worker in event loop.
    """
    import uuid
    
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    logger.info(f"Starting V2 worker with ID: {worker_id}")
    logger.info(f"Server URL: {server_url}")
    logger.info(f"Poll interval: {poll_interval}s")
    
    asyncio.run(run_v2_worker(worker_id, server_url, poll_interval))
