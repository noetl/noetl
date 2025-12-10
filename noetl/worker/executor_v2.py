"""
NoETL v2 Worker Executor - Command execution only, NO queue writing.

Workers:
1. Poll queue for Command records
2. Execute commands based on tool.kind
3. Emit events back to server
4. NEVER directly update queue table
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

import httpx
from jinja2 import BaseLoader, Environment, StrictUndefined

from noetl.core.logger import setup_logger
from noetl.core.dsl.v2.models import Command, EventName

logger = setup_logger(__name__, include_location=True)


class WorkerExecutorV2:
    """Execute commands and emit events."""
    
    def __init__(
        self,
        worker_id: str,
        server_url: str,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.worker_id = worker_id
        self.server_url = server_url.rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=60.0)
        self._jinja = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self._jinja.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False)
    
    async def execute_command(self, command: Command) -> None:
        """
        Execute a command and emit events.
        
        Args:
            command: Command to execute
        """
        start_time = time.time()
        
        try:
            logger.info(
                f"Worker {self.worker_id}: Executing command "
                f"execution={command.execution_id}, step={command.step}, "
                f"tool={command.tool.kind}, attempt={command.attempt}"
            )
            
            # Emit step.enter event
            await self._emit_event(
                execution_id=command.execution_id,
                step=command.step,
                name=EventName.STEP_ENTER.value,
                payload={"tool_kind": command.tool.kind, "attempt": command.attempt},
            )
            
            # Execute based on tool.kind
            result = await self._execute_tool(command)
            
            # Emit call.done event with result
            elapsed = time.time() - start_time
            await self._emit_event(
                execution_id=command.execution_id,
                step=command.step,
                name=EventName.CALL_DONE.value,
                payload={
                    "response": result,
                    "elapsed": elapsed,
                    "attempt": command.attempt,
                },
            )
            
            # Emit step.exit event
            await self._emit_event(
                execution_id=command.execution_id,
                step=command.step,
                name=EventName.STEP_EXIT.value,
                payload={"result": result, "elapsed": elapsed},
            )
            
            logger.info(
                f"Worker {self.worker_id}: Command completed "
                f"for step '{command.step}' in {elapsed:.2f}s"
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(
                f"Worker {self.worker_id}: Command failed "
                f"for step '{command.step}': {e}"
            )
            
            # Emit call.done with error
            await self._emit_event(
                execution_id=command.execution_id,
                step=command.step,
                name=EventName.CALL_DONE.value,
                payload={
                    "error": {
                        "message": str(e),
                        "type": type(e).__name__,
                        "status": getattr(e, "status_code", None),
                    },
                    "elapsed": elapsed,
                    "attempt": command.attempt,
                },
            )
    
    async def _execute_tool(self, command: Command) -> Dict[str, Any]:
        """
        Execute a tool based on kind.
        
        Args:
            command: Command with tool configuration
            
        Returns:
            Tool execution result
        """
        tool_kind = command.tool.kind
        config = command.tool.config
        
        if tool_kind == "http":
            return await self._execute_http(config, command.args)
        elif tool_kind in ["postgres", "duckdb"]:
            return await self._execute_sql(tool_kind, config, command.args)
        elif tool_kind == "python":
            return await self._execute_python(config, command.args)
        elif tool_kind == "workbook":
            return await self._execute_workbook(config, command.args)
        else:
            raise ValueError(f"Unknown tool kind: {tool_kind}")
    
    async def _execute_http(
        self, config: Dict[str, Any], args: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Execute HTTP request."""
        method = config.get("method", "GET").upper()
        url = config.get("endpoint") or config.get("url")
        headers = config.get("headers", {})
        params = config.get("params", {})
        data = config.get("data") or config.get("payload")
        
        if not url:
            raise ValueError("HTTP tool requires 'endpoint' or 'url'")
        
        logger.debug(f"HTTP {method} {url}")
        
        # Execute request
        response = await self.http_client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=data if data and method in ["POST", "PUT", "PATCH"] else None,
        )
        
        # Parse response
        try:
            response_data = response.json()
        except Exception:
            response_data = response.text
        
        return {
            "id": response.headers.get("x-request-id", "unknown"),
            "status": response.status_code,
            "data": response_data,
            "headers": dict(response.headers),
        }
    
    async def _execute_sql(
        self, tool_kind: str, config: Dict[str, Any], args: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Execute SQL command."""
        command = config.get("command") or config.get("query")
        auth = config.get("auth")
        
        if not command:
            raise ValueError("SQL tool requires 'command' or 'query'")
        
        logger.debug(f"{tool_kind.upper()}: {command[:100]}...")
        
        # TODO: Implement actual SQL execution
        # For now, return placeholder
        return {
            "status": "success",
            "tool": tool_kind,
            "rows_affected": 0,
            "message": f"SQL execution placeholder for {tool_kind}",
        }
    
    async def _execute_python(
        self, config: Dict[str, Any], args: Optional[Dict[str, Any]]
    ) -> Any:
        """Execute Python code."""
        code = config.get("code")
        
        if not code:
            raise ValueError("Python tool requires 'code'")
        
        logger.debug(f"Python: {code[:100]}...")
        
        # TODO: Implement actual Python execution
        # For now, return placeholder
        return {
            "status": "success",
            "message": "Python execution placeholder",
        }
    
    async def _execute_workbook(
        self, config: Dict[str, Any], args: Optional[Dict[str, Any]]
    ) -> Any:
        """Execute workbook task."""
        task_name = config.get("task")
        task_args = config.get("with", {})
        
        if not task_name:
            raise ValueError("Workbook tool requires 'task'")
        
        logger.debug(f"Workbook task: {task_name}")
        
        # TODO: Implement workbook task execution
        return {
            "status": "success",
            "task": task_name,
            "message": "Workbook execution placeholder",
        }
    
    async def _emit_event(
        self,
        execution_id: str,
        step: str,
        name: str,
        payload: Dict[str, Any],
    ) -> None:
        """
        Emit event to server.
        
        Args:
            execution_id: Execution identifier
            step: Step name
            name: Event name
            payload: Event payload
        """
        event_data = {
            "execution_id": execution_id,
            "step": step,
            "name": name,
            "payload": payload,
            "worker_id": self.worker_id,
        }
        
        try:
            response = await self.http_client.post(
                f"{self.server_url}/api/v2/events",
                json=event_data,
                timeout=10.0,
            )
            response.raise_for_status()
            logger.debug(f"Event emitted: {name} for step '{step}'")
        except Exception as e:
            logger.error(f"Failed to emit event: {e}")
            # Don't raise - event emission failures shouldn't stop execution


class QueuePollerV2:
    """Poll queue for commands to execute."""
    
    def __init__(
        self,
        worker_id: str,
        server_url: str,
        executor: WorkerExecutorV2,
        poll_interval: float = 1.0,
    ):
        self.worker_id = worker_id
        self.server_url = server_url.rstrip("/")
        self.executor = executor
        self.poll_interval = poll_interval
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self._running = False
    
    async def start(self) -> None:
        """Start polling loop."""
        self._running = True
        logger.info(f"Worker {self.worker_id}: Starting queue poller")
        
        while self._running:
            try:
                # Poll for available command
                command = await self._poll_queue()
                
                if command:
                    # Execute command
                    await self.executor.execute_command(command)
                else:
                    # No commands available, wait before next poll
                    await asyncio.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.exception(f"Error in polling loop: {e}")
                await asyncio.sleep(self.poll_interval)
    
    def stop(self) -> None:
        """Stop polling loop."""
        self._running = False
        logger.info(f"Worker {self.worker_id}: Stopping queue poller")
    
    async def _poll_queue(self) -> Optional[Command]:
        """
        Poll queue for next command.
        
        Returns:
            Command to execute, or None if queue is empty
        """
        try:
            # TODO: Implement actual queue polling from database
            # For now, return None (no commands)
            
            # In production, query:
            # SELECT * FROM noetl.queue
            # WHERE status = 'pending'
            # AND (assigned_worker_id IS NULL OR assigned_worker_id = %(worker_id)s)
            # ORDER BY priority DESC, created_at ASC
            # LIMIT 1
            # FOR UPDATE SKIP LOCKED
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to poll queue: {e}")
            return None
