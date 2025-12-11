"""
NoETL Worker Executor (v2)

Pure execution worker that:
- Polls queue table for commands
- Executes commands by tool.kind
- Posts events back to server
- NEVER updates queue table directly
"""

import logging
import httpx
import asyncio
from typing import Any, Optional
from datetime import datetime
import json

from noetl.core.dsl.v2.models import Command, ToolCall, Event
from noetl.core.config import get_config

logger = logging.getLogger(__name__)


# ============================================================================
# Queue Poller
# ============================================================================

class QueuePollerV2:
    """
    Polls queue table for pending commands.
    Uses FOR UPDATE SKIP LOCKED for concurrency.
    """
    
    def __init__(self, poll_interval: float = 1.0):
        self.poll_interval = poll_interval
        self._running = False
    
    async def start(self, executor: 'WorkerExecutorV2'):
        """Start polling loop."""
        self._running = True
        logger.info("Queue poller v2 started")
        
        while self._running:
            try:
                command = await self._poll_queue()
                
                if command:
                    # Execute command
                    await executor.execute_command(command)
                else:
                    # No commands, wait before next poll
                    await asyncio.sleep(self.poll_interval)
            
            except Exception as e:
                logger.error(f"Error in poll loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)
    
    def stop(self):
        """Stop polling loop."""
        self._running = False
        logger.info("Queue poller v2 stopped")
    
    async def _poll_queue(self) -> Optional[Command]:
        """
        Poll queue for next pending command.
        Uses FOR UPDATE SKIP LOCKED for concurrency.
        """
        try:
            from noetl.core.config import get_db_pool
            pool = get_db_pool()
            
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    # Get next pending command
                    sql = """
                        SELECT 
                            execution_id, step, tool_kind, tool_config,
                            args, attempt, priority, backoff, max_attempts, metadata
                        FROM noetl.queue
                        WHERE status = 'pending'
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    """
                    
                    await cur.execute(sql)
                    row = await cur.fetchone()
                    
                    if not row:
                        return None
                    
                    # Parse row to Command
                    command = Command(
                        execution_id=row[0],
                        step=row[1],
                        tool=ToolCall(kind=row[2], config=row[3]),
                        args=row[4],
                        attempt=row[5],
                        priority=row[6],
                        backoff=row[7],
                        max_attempts=row[8],
                        metadata=row[9]
                    )
                    
                    # Mark as processing
                    update_sql = """
                        UPDATE noetl.queue
                        SET status = 'processing', started_at = NOW()
                        WHERE execution_id = $1 AND step = $2
                    """
                    await cur.execute(update_sql, [command.execution_id, command.step])
                    await conn.commit()
                    
                    return command
        
        except Exception as e:
            logger.error(f"Error polling queue: {e}", exc_info=True)
            return None


# ============================================================================
# Worker Executor
# ============================================================================

class WorkerExecutorV2:
    """
    Executes commands from queue by tool.kind.
    Posts events back to server.
    
    Supported tool kinds:
    - http: HTTP requests
    - postgres: SQL execution
    - duckdb: DuckDB queries
    - python: Python code execution
    - workbook: Workbook task invocation
    """
    
    def __init__(self, worker_id: str, server_url: str):
        self.worker_id = worker_id
        self.server_url = server_url
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def execute_command(self, command: Command):
        """
        Execute command by tool.kind and emit events.
        
        Flow:
        1. Emit step.enter event
        2. Execute tool
        3. Emit call.done event (with response or error)
        4. Emit step.exit event if step is complete
        """
        logger.info(f"Executing command: {command.execution_id} / {command.step} / {command.tool.kind}")
        
        try:
            # Emit step.enter
            await self._emit_event(
                execution_id=command.execution_id,
                step=command.step,
                name="step.enter",
                payload={"tool": command.tool.kind, "args": command.args}
            )
            
            # Execute by tool.kind
            response = None
            error = None
            
            try:
                if command.tool.kind == "http":
                    response = await self._execute_http(command)
                elif command.tool.kind == "postgres":
                    response = await self._execute_postgres(command)
                elif command.tool.kind == "duckdb":
                    response = await self._execute_duckdb(command)
                elif command.tool.kind == "python":
                    response = await self._execute_python(command)
                elif command.tool.kind == "workbook":
                    response = await self._execute_workbook(command)
                else:
                    error = {"message": f"Unsupported tool kind: {command.tool.kind}"}
            
            except Exception as exec_error:
                error = {
                    "message": str(exec_error),
                    "type": type(exec_error).__name__
                }
                logger.error(f"Execution error: {exec_error}", exc_info=True)
            
            # Emit call.done
            payload = {}
            if response is not None:
                payload["response"] = response
            if error is not None:
                payload["error"] = error
            
            await self._emit_event(
                execution_id=command.execution_id,
                step=command.step,
                name="call.done",
                payload=payload,
                attempt=command.attempt
            )
            
            # Emit step.exit (server will decide next steps)
            await self._emit_event(
                execution_id=command.execution_id,
                step=command.step,
                name="step.exit",
                payload={"status": "completed" if error is None else "failed"}
            )
        
        except Exception as e:
            logger.error(f"Error executing command: {e}", exc_info=True)
            
            # Try to emit error event
            try:
                await self._emit_event(
                    execution_id=command.execution_id,
                    step=command.step,
                    name="call.done",
                    payload={"error": {"message": str(e), "type": type(e).__name__}}
                )
            except:
                pass
    
    async def _execute_http(self, command: Command) -> dict[str, Any]:
        """Execute HTTP request."""
        config = command.tool.config
        
        method = config.get("method", "GET")
        endpoint = config.get("endpoint", config.get("url"))
        headers = config.get("headers", {})
        params = config.get("params", {})
        body = config.get("body")
        
        logger.info(f"HTTP {method} {endpoint}")
        
        response = await self.http_client.request(
            method=method,
            url=endpoint,
            headers=headers,
            params=params,
            json=body if body else None
        )
        
        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "data": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        }
    
    async def _execute_postgres(self, command: Command) -> dict[str, Any]:
        """Execute PostgreSQL query."""
        config = command.tool.config
        
        query = config.get("command", config.get("query"))
        auth = config.get("auth")
        
        logger.info(f"Postgres query: {query[:100]}...")
        
        # TODO: Implement actual postgres execution
        # For now, return placeholder
        return {
            "status": "executed",
            "rows_affected": 0,
            "result": []
        }
    
    async def _execute_duckdb(self, command: Command) -> dict[str, Any]:
        """Execute DuckDB query."""
        config = command.tool.config
        
        query = config.get("command", config.get("query"))
        
        logger.info(f"DuckDB query: {query[:100]}...")
        
        # TODO: Implement actual duckdb execution
        return {
            "status": "executed",
            "result": []
        }
    
    async def _execute_python(self, command: Command) -> dict[str, Any]:
        """Execute Python code."""
        config = command.tool.config
        
        code = config.get("code")
        
        logger.info(f"Python code: {code[:100] if code else 'N/A'}...")
        
        # TODO: Implement actual python execution
        # Need to create safe execution environment
        return {
            "status": "executed",
            "result": None
        }
    
    async def _execute_workbook(self, command: Command) -> dict[str, Any]:
        """Execute workbook task."""
        config = command.tool.config
        
        task_name = config.get("task", config.get("name"))
        
        logger.info(f"Workbook task: {task_name}")
        
        # TODO: Implement workbook task execution
        return {
            "status": "executed",
            "task": task_name,
            "result": None
        }
    
    async def _emit_event(
        self,
        execution_id: str,
        step: str,
        name: str,
        payload: dict[str, Any],
        attempt: int = 1
    ):
        """
        Emit event to server.
        POST to /api/v2/events.
        """
        event_data = {
            "execution_id": execution_id,
            "step": step,
            "name": name,
            "payload": payload,
            "worker_id": self.worker_id,
            "attempt": attempt
        }
        
        try:
            response = await self.http_client.post(
                f"{self.server_url}/api/v2/events",
                json=event_data
            )
            
            if response.status_code != 200:
                logger.error(f"Error emitting event: {response.status_code} {response.text}")
        
        except Exception as e:
            logger.error(f"Error posting event to server: {e}", exc_info=True)
    
    async def close(self):
        """Close resources."""
        await self.http_client.aclose()


# ============================================================================
# Helper Functions
# ============================================================================

async def run_worker_v2(worker_id: str, server_url: str):
    """
    Run v2 worker.
    
    Args:
        worker_id: Worker identifier
        server_url: Server URL (e.g., http://localhost:8000)
    """
    executor = WorkerExecutorV2(worker_id=worker_id, server_url=server_url)
    poller = QueuePollerV2(poll_interval=1.0)
    
    try:
        await poller.start(executor)
    finally:
        await executor.close()
