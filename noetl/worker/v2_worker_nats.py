"""
NoETL V2 Worker with NATS Integration

Pure event-sourced worker that:
1. Subscribes to NATS JetStream for command notifications (event_id references)
2. Fetches command details from GET /api/commands/{event_id} (reads command.issued event)
3. Executes based on tool.kind
4. Emits events back to server (POST /api/events)

Single source of truth: event table. No queue table.
"""

import asyncio
import logging
import httpx
import os
from collections import OrderedDict
from typing import Optional, Any
from datetime import datetime, timezone


from noetl.core.messaging import NATSCommandSubscriber
from noetl.core.logging_context import LoggingContext
from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)

# Pre-import tool executors at module level to avoid 5s cold-start delay
# These were previously imported inside _execute_tool() causing slow first execution
from noetl.tools import http, postgres, duckdb, python
from noetl.tools.http import execute_http_task
from noetl.tools.postgres import execute_postgres_task
from noetl.tools.duckdb import execute_duckdb_task
from noetl.tools.snowflake import execute_snowflake_task
from noetl.tools.gcs import execute_gcs_task
from noetl.tools.transfer import execute_transfer_action
from noetl.tools.transfer.snowflake_transfer import execute_snowflake_transfer_action
from noetl.tools.script import execute_script_task
from noetl.core.secrets import execute_secrets_task
from noetl.core.storage import execute_sink_task
from noetl.core.workflow.workbook import execute_workbook_task
from noetl.core.workflow.playbook import execute_playbook_task
from noetl.tools.python import execute_python_task_async
from jinja2 import Environment, BaseLoader
from noetl.worker.keychain_resolver import populate_keychain_context
from noetl.worker.case_evaluator import CaseEvaluator, build_eval_context


# Module-level template cache for worker - avoids compiling same templates repeatedly
class _WorkerTemplateCache:
    """LRU cache for compiled Jinja2 templates in worker. Memory bounded."""

    def __init__(self, max_size: int = 500):
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size
        self._env = None  # Lazy initialization
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get_env(self):
        """Get or create Jinja2 environment."""
        if self._env is None:
            from jinja2 import Environment
            self._env = Environment()
        return self._env

    def get_or_compile(self, template_str: str) -> Any:
        """Get compiled template from cache or compile and cache it."""
        if template_str in self._cache:
            self._cache.move_to_end(template_str)
            self._hits += 1
            return self._cache[template_str]

        self._misses += 1
        compiled = self.get_env().from_string(template_str)

        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
            self._evictions += 1

        self._cache[template_str] = compiled

        # Log stats periodically
        if self._misses % 100 == 0:
            logger.debug(
                f"[TEMPLATE-CACHE] Worker stats: size={len(self._cache)}/{self._max_size}, "
                f"hits={self._hits}, misses={self._misses}, hit_rate={self._hits / (self._hits + self._misses) * 100:.1f}%"
            )

        return compiled

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": (self._hits / total * 100) if total > 0 else 0.0
        }


_template_cache = _WorkerTemplateCache(max_size=500)


class V2Worker:
    """
    V2 Worker that receives command notifications from NATS and executes them.
    
    Architecture (Pure Event Sourcing):
    - Subscribes to NATS JetStream for command notifications
    - Receives lightweight message with {execution_id, event_id, command_id, step, server_url}
    - Fetches full command from GET /api/commands/{event_id} (reads command.issued event)
    - Executes tool based on tool.kind
    - Emits events to POST /api/events (command.completed or command.failed)
    - Single source of truth: event table. No queue table.
    """
    
    def __init__(
        self,
        worker_id: str,
        nats_url: Optional[str] = None,
        server_url: Optional[str] = None
    ):
        from noetl.core.config import get_worker_settings
        worker_settings = get_worker_settings()
        self.worker_id = worker_id
        self.nats_url = nats_url or worker_settings.nats_url
        self.server_url = server_url  # Fallback, usually comes from notification
        self._running = False
        self._http_client: Optional[httpx.AsyncClient] = None
        self._nats_subscriber: Optional[NATSCommandSubscriber] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._registered = False
    
    async def _register_worker(self, server_url: str) -> bool:
        """Register this worker in the runtime table via API."""
        try:
            hostname = os.environ.get("HOSTNAME", os.environ.get("POD_NAME", "unknown"))
            register_url = f"{server_url.rstrip('/')}/api/worker/pool/register"
            
            payload = {
                "name": self.worker_id,
                "component_type": "worker_pool",
                "runtime": "python",
                "status": "ready",
                "capacity": 1,  # Single worker instance
                "pid": os.getpid(),
                "hostname": hostname,
                "labels": {
                    "nats_consumer": os.environ.get("NOETL_WORKER_NATS_CONSUMER", "noetl_worker_pool"),
                },
                "meta": {
                    "nats_url": self.nats_url,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
            }
            
            response = await self._http_client.post(register_url, json=payload, timeout=10.0)
            if response.status_code == 200:
                self._registered = True
                logger.debug(f"Worker {self.worker_id} registered in runtime table")
                return True
            else:
                logger.warning(f"Worker registration failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.warning(f"Worker registration error: {e}")
            return False
    
    async def _deregister_worker(self, server_url: str) -> bool:
        """Deregister this worker from the runtime table via API."""
        try:
            deregister_url = f"{server_url.rstrip('/')}/api/worker/pool/deregister"
            
            payload = {
                "name": self.worker_id,
                "component_type": "worker_pool",
            }
            
            response = await self._http_client.post(deregister_url, json=payload, timeout=10.0)
            if response.status_code == 200:
                self._registered = False
                logger.debug(f"Worker {self.worker_id} deregistered from runtime table")
                return True
            else:
                logger.warning(f"Worker deregistration failed: {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Worker deregistration error: {e}")
            return False
    
    async def _heartbeat_loop(self, server_url: str):
        """Background task to send heartbeat updates to runtime table."""
        logger.info(f"Worker {self.worker_id} heartbeat loop started (interval: 15s)")
        
        while self._running:
            try:
                await asyncio.sleep(15)  # Heartbeat every 15 seconds
                
                if not self._running:
                    break
                
                # Re-register acts as heartbeat (upsert updates heartbeat timestamp)
                await self._register_worker(server_url)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat error: {e}")
                await asyncio.sleep(5)  # Back off on error
        
        logger.info(f"Worker {self.worker_id} heartbeat loop stopped")
    
    async def start(self):
        """Start the worker NATS subscription."""
        from noetl.core.config import get_worker_settings
        worker_settings = get_worker_settings()
        self._running = True
        self._http_client = httpx.AsyncClient(timeout=worker_settings.http_client_timeout)
        self._nats_subscriber = NATSCommandSubscriber(
            nats_url=self.nats_url,
            subject=worker_settings.nats_subject,
            consumer_name=worker_settings.nats_consumer,
            stream_name=worker_settings.nats_stream
        )
        
        logger.info(f"Worker {self.worker_id} starting (NATS: {self.nats_url})")
        
        # Connect to NATS
        await self._nats_subscriber.connect()
        logger.info("Connected to NATS and subscribing to command notifications")
        
        # Register worker in runtime table
        server_url = self.server_url or worker_settings.server_url
        if server_url:
            await self._register_worker(server_url)
            # Start heartbeat background task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(server_url))
        else:
            logger.warning("No server_url configured - worker registration skipped")
        
        # Subscribe to command notifications (this should never return)
        await self._nats_subscriber.subscribe(self._handle_command_notification)
    
    async def cleanup(self):
        """Cleanup resources."""
        self._running = False
        
        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Deregister from runtime table
        from noetl.core.config import get_worker_settings
        worker_settings = get_worker_settings()
        server_url = self.server_url or worker_settings.server_url
        if server_url and self._http_client and self._registered:
            await self._deregister_worker(server_url)
        
        if self._nats_subscriber:
            await self._nats_subscriber.close()
        if self._http_client:
            await self._http_client.aclose()
        
        # Close all connection pools
        try:
            from noetl.tools.postgres.pool import close_all_plugin_pools
            await close_all_plugin_pools()
            logger.info("Closed all Postgres connection pools")
        except Exception as e:
            logger.warning(f"Error closing connection pools: {e}")
        
        logger.info(f"Worker {self.worker_id} stopped")
    
    def stop(self):
        """Stop the worker."""
        self._running = False
    
    async def _monitor_pool_health(self):
        """
        Background task to monitor connection pool health.
        
        Runs every 5 minutes to:
        - Check pool statistics
        - Log warnings for unhealthy pools
        - Report pool metrics
        """
        logger.info("Started connection pool health monitor")
        
        while self._running:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                if not self._running:
                    break
                
                from noetl.tools.postgres.pool import get_plugin_pool_stats
                stats = get_plugin_pool_stats()
                
                if not stats:
                    continue
                
                # Log summary
                logger.info(f"Connection pool health check: {len(stats)} active pools")
                
                for pool_key, pool_stats in stats.items():
                    if "error" in pool_stats:
                        logger.warning(f"Pool {pool_key}: {pool_stats['error']}")
                        continue
                    
                    # Check for warning conditions
                    waiting = pool_stats.get('waiting', 0)
                    available = pool_stats.get('available', 0)
                    age = pool_stats.get('age_seconds', 0)
                    
                    if waiting > 5:
                        logger.warning(
                            f"Pool {pool_stats['name']}: {waiting} requests waiting, "
                            f"{available} connections available"
                        )
                    
                    if age > 3600:  # 1 hour
                        logger.info(
                            f"Pool {pool_stats['name']}: Active for {age}s, "
                            f"will be refreshed on next use"
                        )
                    
                    # Log healthy pool stats at debug level
                    logger.debug(
                        f"Pool {pool_stats['name']}: "
                        f"size={pool_stats.get('size')}, "
                        f"available={available}, "
                        f"waiting={waiting}, "
                        f"age={age}s"
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in pool health monitor: {e}", exc_info=True)
                await asyncio.sleep(60)  # Back off on error
        
        logger.info("Stopped connection pool health monitor")
    
    async def _check_execution_cancelled(self, server_url: str, execution_id: int) -> bool:
        """
        Check if an execution has been cancelled.
        
        Queries the server for execution.cancelled events.
        
        Returns True if execution is cancelled and should not proceed.
        """
        try:
            # Query execution cancellation status via API
            response = await self._http_client.get(
                f"{server_url.rstrip('/')}/api/executions/{execution_id}/cancellation-check",
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("cancelled", False):
                    logger.info(f"[CANCEL] Execution {execution_id} has been cancelled - skipping command")
                    return True
            return False
        except Exception as e:
            # If we can't check, continue with execution (fail-open)
            logger.warning(f"[CANCEL] Could not check cancellation status for {execution_id}: {e}")
            return False
    
    async def _handle_command_notification(self, notification: dict):
        """
        Handle command notification from NATS (Event-Driven).
        
        Notification contains: {execution_id, event_id, command_id, step, server_url}
        
        Event-driven flow:
        1. Check if command already claimed
        2. Attempt atomic claim via command.claimed event
        3. If claim succeeds, fetch command details and execute
        4. If claim fails, another worker got it - silently skip
        """
        with LoggingContext(logger, notification=notification, execution_id = notification.get("execution_id")):
            try:
                execution_id = notification["execution_id"]
                event_id = notification["event_id"]
                command_id = notification["command_id"]
                step = notification["step"]
                server_url = notification["server_url"]
                
                logger.info(f"[EVENT] Worker {self.worker_id} received notification: exec={execution_id}, command={command_id}, step={step}")
                
                # Check if execution has been cancelled before claiming
                if await self._check_execution_cancelled(server_url, execution_id):
                    logger.info(f"[CANCEL] Execution {execution_id} cancelled - skipping command {command_id}")
                    return
                
                # Attempt to claim the command atomically
                claimed = await self._claim_command(server_url, execution_id, command_id)
                
                if not claimed:
                    logger.info(f"[EVENT] Command {command_id} already claimed by another worker - skipping")
                    return
                
                logger.info(f"[EVENT] Worker {self.worker_id} claimed command {command_id}")
                
                # Check again after claiming (in case cancellation happened during claim)
                if await self._check_execution_cancelled(server_url, execution_id):
                    logger.info(f"[CANCEL] Execution {execution_id} cancelled after claim - aborting command {command_id}")
                    await self._emit_event(
                        server_url, execution_id, step, "command.cancelled",
                        {"command_id": command_id, "reason": "Execution cancelled"},
                        actionable=False, informative=True
                    )
                    return
                
                # Fetch command details from command.issued event
                command = await self._fetch_command_details(server_url, event_id)
                
                if not command:
                    logger.error(f"[EVENT] Failed to fetch command details for event_id={event_id}")
                    await self._emit_command_failed(server_url, execution_id, command_id, step, "Failed to fetch command details")
                    return
                
                # Execute the command
                import time
                t_command_start = time.perf_counter()
                await self._execute_command(command, server_url, command_id)
                t_command_end = time.perf_counter()
                logger.info(f"[PERF] _execute_command for {step} took {t_command_end - t_command_start:.4f}s")
                
            except Exception as e:
                logger.exception(f"Error handling command notification: {e}")
    
    async def _claim_command(self, server_url: str, execution_id: int, command_id: str) -> bool:
        """
        Atomically claim a command by emitting command.claimed event.
        
        Server checks if command is already claimed - returns 409 Conflict if so.
        
        Returns True if this worker successfully claimed the command.
        """
        try:
            response = await self._http_client.post(
                    f"{server_url.rstrip('/')}/api/events",
                json={
                    "execution_id": str(execution_id),
                    "step": command_id.split(":")[1] if ":" in command_id else "unknown",  # Extract step from command_id
                    "name": "command.claimed",
                    "payload": {
                        "command_id": command_id,
                        "worker_id": self.worker_id
                    },
                    "meta": {
                        "worker_id": self.worker_id,
                        "command_id": command_id
                    },
                    "worker_id": self.worker_id
                }
            )
            
            if response.status_code == 200:
                logger.info(f"[EVENT] Successfully claimed command {command_id}")
                return True
            elif response.status_code == 409:
                # Command already claimed by another worker - this is expected in multi-worker setup
                logger.info(f"[EVENT] Command {command_id} already claimed by another worker, skipping")
                return False
            else:
                logger.warning(f"[EVENT] Failed to claim command {command_id}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"[EVENT] Error claiming command {command_id}: {e}")
            return False
    
    async def _fetch_command_details(self, server_url: str, event_id: int) -> Optional[dict]:
        """
        Fetch command details from server API.
        
        Uses the /api/commands/{event_id} endpoint to get command configuration
        from the command.issued event.
        """
        try:
            response = await self._http_client.get(
                f"{server_url.rstrip('/')}/api/commands/{event_id}"
            )
            
            if response.status_code == 404:
                logger.error(f"[EVENT] No command.issued event found for event_id={event_id}")
                return None
            
            if response.status_code != 200:
                logger.error(f"[EVENT] Failed to fetch command details: {response.status_code} - {response.text}")
                return None
            
            command = response.json()
            logger.info(f"[EVENT] Fetched command details: step={command.get('node_name')}, tool={command.get('action')}")
            return command
            
        except Exception as e:
            logger.error(f"[EVENT] Error fetching command details: {e}", exc_info=True)
            return None
    
    async def _emit_command_failed(self, server_url: str, execution_id: int, command_id: str, step: str, error_msg: str):
        """Emit command.failed event."""
        try:
            await self._http_client.post(
                f"{server_url.rstrip('/')}/api/events",
                json={
                    "execution_id": str(execution_id),
                    "step": step,
                    "name": "command.failed",
                    "payload": {
                        "command_id": command_id,
                        "error": error_msg
                    },
                    "meta": {
                        "worker_id": self.worker_id,
                        "command_id": command_id
                    },
                    "worker_id": self.worker_id
                }
            )
        except Exception as e:
            logger.error(f"[EVENT] Failed to emit command.failed: {e}")
    
    async def _fetch_execution_variables(
        self,
        server_url: str,
        execution_id: int
    ) -> dict:
        """
        Fetch all execution variables from server API.
        
        Returns dict with variable names as keys and their values.
        Used for case condition evaluation when variables are referenced.
        """
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{server_url}/api/vars/{execution_id}",
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Extract just the values from metadata structure
                    # API returns: {variables: {name: {value, type, source_step, ...}}}
                    variables = data.get('variables', {})
                    return {name: meta.get('value') for name, meta in variables.items()}
                else:
                    logger.warning(f"[VARS] Failed to fetch variables: {response.status_code}")
                    return {}
        except Exception as e:
            logger.error(f"[VARS] Error fetching variables: {e}")
            return {}
    
    async def _evaluate_case_blocks_with_event(
        self,
        case_blocks: list,
        response: dict,
        render_context: dict,
        server_url: str,
        execution_id: int,
        step: str,
        event_name: str = "call.done",
        error: str = None
    ) -> dict | None:
        """
        Enhanced case evaluation with explicit event context.
        
        Evaluates case conditions against:
        - Event context (event.name == 'call.done' or 'call.error')
        - Data context (response.status_code, result.field, error, etc.)
        
        This allows case blocks to handle both success and error scenarios:
        
        case:
          - when: "{{ event.name == 'call.error' and response.status_code == 429 }}"
            then:
              retry:
                delay: "{{ response.headers.get('Retry-After', 60) }}"
          - when: "{{ event.name == 'call.done' }}"
            then:
              sink: ...
        
        Args:
            case_blocks: List of case conditions
            response: Tool response/result
            render_context: Full render context
            server_url: Server API URL
            execution_id: Execution ID
            step: Step name
            event_name: Event name ('call.done' or 'call.error')
            error: Optional error message for call.error events
            
        Returns:
            Action dict {type: 'next'|'retry'|'sink', details: {...}} or None
        """
        from jinja2 import Environment
        
        if not case_blocks or not isinstance(case_blocks, list):
            return None
        
        logger.info(f"[CASE-EVAL] Evaluating {len(case_blocks)} case blocks | event={event_name} | has_error={error is not None}")
        
        # Create Jinja environment for condition evaluation
        jinja_env = Environment()
        
        # Build hybrid evaluation context with both event and data
        eval_context = {
            **render_context,
            'response': response,
            'result': response,
            'this': response,
            'event': {
                'name': event_name,  # 'call.done' or 'call.error'
                'type': 'tool.completed' if event_name == 'call.done' else 'tool.error',
                'step': step
            },
            'error': error
        }
        
        # Add HTTP-specific context if available
        if isinstance(response, dict):
            # Add status_code to top level for convenience
            if 'status_code' in response:
                eval_context['status_code'] = response['status_code']
            # Add data.status_code for nested HTTP responses
            if isinstance(response.get('data'), dict) and 'status_code' in response['data']:
                eval_context['status_code'] = response['data']['status_code']
        
        # Track if we need to fetch variables from server
        variables_fetched = False
        
        # Check each case block
        for idx, case in enumerate(case_blocks):
            if not isinstance(case, dict):
                continue
            
            when_condition = case.get('when')
            then_block = case.get('then')
            
            if not when_condition or not then_block:
                continue
            
            # Evaluate condition with hybrid context (with retry on missing variables)
            max_retries = 2  # Allow one retry with server variable lookup
            for attempt in range(max_retries):
                try:
                    # Use cached template for performance
                    template = _template_cache.get_or_compile(when_condition)
                    condition_result = template.render(eval_context)
                    
                    # Parse boolean result (Jinja2 returns string)
                    # Jinja2's `and` operator returns the actual value, not "True/False"
                    # e.g., {{ cond1 and some_string }} returns the string if truthy
                    # So we evaluate truthiness: non-empty strings that aren't falsy values
                    result_stripped = condition_result.strip()
                    result_lower = result_stripped.lower()
                    matches = bool(result_stripped) and result_lower not in ['false', '0', 'no', 'none', '']
                    
                    logger.info(f"[CASE-EVAL] Case {idx} condition: {when_condition[:100]}... = {matches}")
                    
                    if not matches:
                        # Condition not met - break retry loop and try next case
                        break
                    
                    # Case matched - extract action
                    logger.info(f"[CASE-EVAL] Case {idx} matched (event={event_name})! Extracting action")
                    
                    # Normalize then_block to list of action dicts
                    # then_block can be: dict, list of dicts, or list with 'next' key
                    if isinstance(then_block, dict):
                        # Single dict - could be {next: [...]} or {sink: ...} etc
                        if 'next' in then_block:
                            # Special case: {next: [...]} format
                            then_action_list = [then_block]
                        else:
                            # Regular action dict - wrap in list
                            then_action_list = [then_block]
                    elif isinstance(then_block, list):
                        then_action_list = then_block
                    else:
                        then_action_list = []
                    
                    # Process actions in order: sink, then routing (retry/next)
                    has_sink = False
                    has_retry = False
                    has_next = False
                    retry_config = None
                    next_steps = None
                    set_config = None
                    
                    for action in then_action_list:
                        if not isinstance(action, dict):
                            continue
                        
                        if 'sink' in action:
                            has_sink = True
                        if 'retry' in action:
                            has_retry = True
                            # Get raw retry config (may contain Jinja2 templates)
                            raw_retry_config = action['retry']
                            
                            # Render retry args templates with current context
                            # This ensures page numbers and other dynamic values are computed NOW
                            retry_config = {}
                            for key, value in raw_retry_config.items():
                                if key == 'args' and isinstance(value, dict):
                                    # Recursively render args
                                    rendered_args = {}
                                    for arg_key, arg_value in value.items():
                                        if isinstance(arg_value, dict):
                                            # Recursively render nested dicts (e.g., params)
                                            rendered_nested = {}
                                            for nested_key, nested_value in arg_value.items():
                                                if isinstance(nested_value, str) and '{{' in nested_value:
                                                    template = _template_cache.get_or_compile(nested_value)
                                                    rendered_nested[nested_key] = template.render(eval_context)
                                                else:
                                                    rendered_nested[nested_key] = nested_value
                                            rendered_args[arg_key] = rendered_nested
                                        elif isinstance(arg_value, str) and '{{' in arg_value:
                                            template = _template_cache.get_or_compile(arg_value)
                                            rendered_args[arg_key] = template.render(eval_context)
                                        else:
                                            rendered_args[arg_key] = arg_value
                                    retry_config[key] = rendered_args
                                else:
                                    retry_config[key] = value
                            
                            logger.info(f"[CASE-EVAL] Rendered retry config: {retry_config}")
                        if 'next' in action:
                            has_next = True
                            next_steps = action['next']
                        if 'set' in action:
                            set_config = action['set']
                    
                    # Execute sink first if present (semantic order: sink → retry/next)
                    if has_sink:
                        logger.info(f"[CASE-EVAL] Case {idx} has sink action - executing via _execute_case_sinks")
                        await self._execute_case_sinks(
                            [case],
                            response,
                            render_context,
                            server_url,
                            execution_id,
                            step,
                            event_name="call.done"
                        )
                    
                    # Handle retry locally in the worker (don't send to server)
                    if has_retry:
                        logger.info(f"[CASE-EVAL] Case {idx} triggered retry - returning retry action for local handling")
                        return {
                            'type': 'retry',
                            'config': retry_config,
                            'case_index': idx,
                            'triggered_by': event_name
                        }
                    
                    if has_next:
                        if isinstance(next_steps, list) and len(next_steps) > 0:
                            return {
                                'type': 'next',
                                'steps': next_steps,
                                'case_index': idx,
                                'triggered_by': event_name
                            }
                    
                    if set_config:
                        logger.info(f"[CASE-EVAL] Case {idx} has set action - updating variables")
                        return {
                            'type': 'set',
                            'config': set_config,
                            'case_index': idx,
                            'triggered_by': event_name
                        }
                    
                    # Sink executed but no routing action - continue normal flow
                    if has_sink:
                        return None
                    
                    # Successfully evaluated - break retry loop
                    break
                    
                except Exception as e:
                    # Check if error is due to missing variable reference
                    error_msg = str(e)
                    if ('undefined' in error_msg.lower() or 'not defined' in error_msg.lower()) and attempt == 0 and not variables_fetched:
                        # First attempt failed due to missing variable - fetch from server
                        logger.warning(f"[CASE-EVAL] Missing variable in condition, fetching from server: {error_msg}")
                        
                        # Fetch variables from server API
                        server_vars = await self._fetch_execution_variables(server_url, execution_id)
                        
                        if server_vars:
                            logger.info(f"[CASE-EVAL] Fetched {len(server_vars)} variables from server: {list(server_vars.keys())}")
                            # Merge into eval_context under 'vars' namespace
                            eval_context['vars'] = server_vars
                            variables_fetched = True
                            # Continue to retry with enriched context
                            continue
                        else:
                            logger.error(f"[CASE-EVAL] Failed to fetch variables from server")
                            break
                    else:
                        # Other error or retry exhausted
                        logger.error(f"[CASE-EVAL] Error evaluating case {idx} (attempt {attempt + 1}): {e}")
                        break
        
        # No matching case with routing action
        logger.info(f"[CASE-EVAL] No matching case with routing action found for event={event_name}")
        return None
    
    async def _evaluate_case_blocks(
        self,
        case_blocks: list,
        response: dict,
        render_context: dict,
        server_url: str,
        execution_id: int,
        step: str
    ) -> dict | None:
        """
        Hybrid case evaluation: Worker-side evaluation with both event and data context.
        
        Evaluates case conditions against:
        - Event context (event.name, event.type, etc.)
        - Data context (response.status_code, result.field, error, etc.)
        
        Returns action to take: {type: 'next'|'retry'|'sink', details: {...}}
        If no case matches or only sink actions, returns None.
        
        NOTE: This is a backward-compatible wrapper. New code should use
        _evaluate_case_blocks_with_event for explicit event context.
        """
        # Delegate to enhanced method with default call.done context
        return await self._evaluate_case_blocks_with_event(
            case_blocks=case_blocks,
            response=response,
            render_context=render_context,
            server_url=server_url,
            execution_id=execution_id,
            step=step,
            event_name="call.done",
            error=response.get('error') if isinstance(response, dict) else None
        )
    
    async def _fetch_execution_variables(
        self,
        server_url: str,
        execution_id: int
    ) -> dict:
        """
        Fetch all execution variables from server API.
        
        Returns dict with variable names as keys and their values.
        Used for case condition evaluation when variables are referenced.
        """
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{server_url}/api/vars/{execution_id}",
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Extract just the values from metadata structure
                    # API returns: {variables: {name: {value, type, source_step, ...}}}
                    variables = data.get('variables', {})
                    return {name: meta.get('value') for name, meta in variables.items()}
                else:
                    logger.warning(f"[VARS] Failed to fetch variables: {response.status_code}")
                    return {}
        except Exception as e:
            logger.error(f"[VARS] Error fetching variables: {e}")
            return {}
    
    async def _evaluate_case_blocks(
        self,
        case_blocks: list,
        response: dict,
        render_context: dict,
        server_url: str,
        execution_id: int,
        step: str
    ) -> dict | None:
        """
        Hybrid case evaluation: Worker-side evaluation with both event and data context.
        
        Evaluates case conditions against:
        - Event context (event.name, event.type, etc.)
        - Data context (response.status_code, result.field, error, etc.)
        
        Returns action to take: {type: 'next'|'retry'|'sink', details: {...}}
        If no case matches or only sink actions, returns None.
        """
        from jinja2 import Environment
        
        if not case_blocks or not isinstance(case_blocks, list):
            return None
        
        logger.info(f"[CASE-EVAL] Evaluating {len(case_blocks)} case blocks with hybrid context")
        
        # Create Jinja environment for condition evaluation
        jinja_env = Environment()
        
        # Build hybrid evaluation context with both event and data
        # Support both event-source (event.name) and data-source (response.status_code) evaluation
        eval_context = {
            **render_context,
            'response': response,
            'result': response,
            'this': response,
            'event': {
                'name': 'call.done',  # Event name for post-call evaluation
                'type': 'tool.completed',
                'step': step
            },
            'error': response.get('error') if isinstance(response, dict) else None
        }
        
        # Track if we need to fetch variables from server
        variables_fetched = False
        
        # Check each case block
        for idx, case in enumerate(case_blocks):
            if not isinstance(case, dict):
                continue
            
            when_condition = case.get('when')
            then_block = case.get('then')
            
            if not when_condition or not then_block:
                continue
            
            # Evaluate condition with hybrid context (with retry on missing variables)
            max_retries = 2  # Allow one retry with server variable lookup
            for attempt in range(max_retries):
                try:
                    # Use cached template for performance
                    template = _template_cache.get_or_compile(when_condition)
                    condition_result = template.render(eval_context)
                    
                    # Parse boolean result (Jinja2 returns string)
                    # Jinja2's `and` operator returns the actual value, not "True/False"
                    # e.g., {{ cond1 and some_string }} returns the string if truthy
                    # So we evaluate truthiness: non-empty strings that aren't falsy values
                    result_stripped = condition_result.strip()
                    result_lower = result_stripped.lower()
                    matches = bool(result_stripped) and result_lower not in ['false', '0', 'no', 'none', '']
                    
                    logger.info(f"[CASE-EVAL] Case {idx} condition: {when_condition[:100]}... = {matches}")
                    
                    if not matches:
                        # Condition not met - break retry loop and try next case
                        break
                    
                    # Case matched - extract action
                    logger.info(f"[CASE-EVAL] Case {idx} matched! Extracting action from then block")
                    
                    # Normalize then_block to dict format
                    then_actions = then_block if isinstance(then_block, dict) else {}
                    
                    # Check for routing actions (next, retry)
                    if 'next' in then_actions:
                        next_steps = then_actions['next']
                        if isinstance(next_steps, list) and len(next_steps) > 0:
                            return {
                                'type': 'next',
                                'steps': next_steps,
                                'case_index': idx
                            }
                    
                    if 'retry' in then_actions:
                        retry_config = then_actions['retry']
                        return {
                            'type': 'retry',
                            'config': retry_config,
                            'case_index': idx
                        }
                    
                    # Check for sink action (handled separately)
                    if 'sink' in then_actions:
                        logger.info(f"[CASE-EVAL] Case {idx} has sink action - will execute via _execute_case_sinks")
                        # Execute sink immediately
                        await self._execute_case_sinks(
                            [case],
                            response,
                            render_context,
                            server_url,
                            execution_id,
                            step,
                            event_name=event_name
                        )
                        # Return None to continue normal flow (sink doesn't affect routing)
                        return None
                    
                    # Successfully evaluated - break retry loop
                    break
                    
                except Exception as e:
                    # Check if error is due to missing variable reference
                    error_msg = str(e)
                    if ('undefined' in error_msg.lower() or 'not defined' in error_msg.lower()) and attempt == 0 and not variables_fetched:
                        # First attempt failed due to missing variable - fetch from server
                        logger.warning(f"[CASE-EVAL] Missing variable in condition, fetching from server: {error_msg}")
                        
                        # Fetch variables from server API
                        server_vars = await self._fetch_execution_variables(server_url, execution_id)
                        
                        if server_vars:
                            logger.info(f"[CASE-EVAL] Fetched {len(server_vars)} variables from server: {list(server_vars.keys())}")
                            # Merge into eval_context under 'vars' namespace
                            eval_context['vars'] = server_vars
                            variables_fetched = True
                            # Continue to retry with enriched context
                            continue
                        else:
                            logger.error(f"[CASE-EVAL] Failed to fetch variables from server")
                            break
                    else:
                        # Other error or retry exhausted
                        logger.error(f"[CASE-EVAL] Error evaluating case {idx} (attempt {attempt + 1}): {e}")
                        break
        
        # No matching case with routing action
        logger.info(f"[CASE-EVAL] No matching case with routing action found")
        return None
    
    async def _execute_case_sinks(
        self,
        case_blocks: list,
        response: Any,
        render_context: dict,
        server_url: str,
        execution_id: int,
        step: str,
        event_name: str = "call.done"
    ):
        """
        DEPRECATED: This function is no longer used.

        Sink execution is now handled by the server through inline task commands.
        Named tasks in then: blocks (like sink: {tool: ...}) are processed by the
        server's _process_then_actions and executed as separate commands.

        This function is kept as a no-op for compatibility with existing call sites.
        """
        # DISABLED: Sink execution is now handled by the server through inline task commands
        # See: engine.py _process_then_actions (lines 985-997) where named tasks are processed
        logger.debug(f"[SINK] _execute_case_sinks called but disabled - sinks handled by server")
        return

        import asyncio
        from jinja2 import Environment
        from noetl.tools.postgres import execute_postgres_task

        # Check if case_blocks provided
        if not case_blocks or not isinstance(case_blocks, list):
            return
        
        logger.info(f"[SINK] Checking {len(case_blocks)} case blocks for sinks")
        
        # Create Jinja environment for condition evaluation
        jinja_env = Environment()
        
        # Build evaluation context with response
        # Support both call.done and step.exit event names in conditions
        # The engine uses step.exit for post-step sinks, so we provide both
        
        # Extract result from response for template access
        # Keep response structure intact so templates can access result.data
        # (HTTP responses are {id, status, data: [...]})
        
        eval_context = {
            **render_context,
            'response': response,
            'result': response,  # Keep full response structure for {{ result.data }} access
            'this': response,    # Add this for {{ this }} (full response)
            'event': {'name': event_name},
            'error': response.get('error') if isinstance(response, dict) else None
        }
        
        # Check each case block
        for idx, case in enumerate(case_blocks):
            if not isinstance(case, dict):
                continue
                
            when_condition = case.get('when')
            then_block = case.get('then')
            
            if not when_condition or not then_block:
                continue
            
            # Normalize then_block to list format (supports both dict and list)
            then_actions = then_block if isinstance(then_block, list) else [then_block]
            
            # Look for sink in any of the then actions
            sink_config = None
            collect_config = None
            retry_config = None
            
            for action in then_actions:
                if not isinstance(action, dict):
                    continue
                if 'sink' in action:
                    sink_config = action['sink']
                if 'collect' in action:
                    collect_config = action['collect']
                if 'retry' in action:
                    retry_config = action['retry']
            
            # Skip if no sink to execute (we only care about sinks here)
            if not sink_config:
                continue
            
            logger.info(f"[SINK] Case block {idx} has sink, evaluating condition: {when_condition}")
            logger.info(f"[SINK] eval_context keys: {list(eval_context.keys())}")
            logger.info(f"[SINK] event.name: {eval_context.get('event', {}).get('name', 'NOT_FOUND')}")
            logger.info(f"[SINK] response defined: {'response' in eval_context}, response: {eval_context.get('response', 'NOT_FOUND')}")
            
            # Evaluate condition
            try:
                # when_condition is already a Jinja2 template (e.g., "{{ event.name == 'step.exit' }}")
                # so render it directly without wrapping it again - use cached template for performance
                template = _template_cache.get_or_compile(when_condition)
                result = template.render(eval_context)
                # Result should be a boolean or string that evaluates to boolean
                # Jinja2's `and` operator returns the actual value, not "True/False"
                # e.g., {{ cond1 and some_string }} returns the string if truthy
                if isinstance(result, bool):
                    condition_met = result
                elif isinstance(result, str):
                    result_stripped = result.strip()
                    result_lower = result_stripped.lower()
                    condition_met = bool(result_stripped) and result_lower not in ('false', '0', 'no', 'none', '')
                else:
                    condition_met = bool(result)

                logger.info(f"[SINK] Condition result: {result} -> {condition_met}")
                
                if not condition_met:
                    continue
                
                # Condition met - execute in semantic order: collect → sink → retry
                # Note: collect and retry are handled by server/engine, we only execute sink
                
                logger.info(f"[SINK] Executing sink for case {idx}")
                
                # Extract sink type for events
                sink_tool = sink_config.get('tool', {})
                if isinstance(sink_tool, str):
                    sink_kind = sink_tool
                    sink_table = None
                else:
                    sink_kind = sink_tool.get('kind', 'unknown')
                    sink_table = sink_tool.get('table')
                
                # Emit sink.start event
                await self._emit_event(
                    server_url,
                    execution_id,
                    f"{step}.sink",
                    "sink.start",
                    {
                        "case_index": idx,
                        "sink_type": sink_kind,
                        "sink_table": sink_table
                    },
                    actionable=False,
                    informative=True
                )
                
                # Use the centralized sink executor instead of postgres-only handling
                from noetl.core.storage import execute_sink_task
                
                # Build sink task config for execute_sink_task
                # The sink config is already structured under 'tool:' key
                sink_task_config = {
                    'sink': sink_config  # Pass the entire sink configuration
                }
                
                logger.info(f"[SINK] Delegating to execute_sink_task with config: {sink_task_config}")
                logger.info(f"[SINK] Context keys: {list(eval_context.keys()) if isinstance(eval_context, dict) else type(eval_context)}")
                logger.info(f"[SINK] Workload in context: {'workload' in eval_context}")
                
                # Execute sink via centralized executor (supports all tool types)
                loop = asyncio.get_running_loop()
                sink_result = await loop.run_in_executor(
                    None,
                    lambda: execute_sink_task(
                        sink_task_config,
                        eval_context,
                        jinja_env,
                        None  # task_with - not needed for case sinks
                    )
                )
                
                logger.info(f"[SINK] Sink executed successfully: {sink_result}")
                
                # Extract summary from sink result
                sink_summary = self._extract_sink_summary(sink_result, sink_kind, sink_table)
                
                # Emit sink.done event with summary
                await self._emit_event(
                    server_url,
                    execution_id,
                    f"{step}.sink",
                    "sink.done",
                    {
                        "case_index": idx,
                        "sink_type": sink_kind,
                        "summary": sink_summary,
                        "has_collect": collect_config is not None,
                        "has_retry": retry_config is not None
                    },
                    actionable=False,
                    informative=True
                )
                    
            except Exception as e:
                logger.error(f"[SINK] Error executing sink for case {idx}: {e}", exc_info=True)
                
                # Emit sink.error event
                await self._emit_event(
                    server_url,
                    execution_id,
                    f"{step}.sink",
                    "sink.error",
                    {
                        "case_index": idx,
                        "sink_type": sink_config.get('tool', {}).get('kind', 'unknown') if isinstance(sink_config.get('tool'), dict) else sink_config.get('tool', 'unknown'),
                        "error": str(e)
                    },
                    actionable=False,
                    informative=True
                )
    
    def _extract_sink_summary(
        self,
        sink_result: dict,
        sink_kind: str,
        sink_table: Optional[str] = None
    ) -> dict:
        """
        Extract summary information from sink result.
        
        Args:
            sink_result: Result from execute_sink_task
            sink_kind: Sink type (postgres, duckdb, http, etc.)
            sink_table: Optional table name
            
        Returns:
            Dictionary with summary information
        """
        summary = {
            "sink_type": sink_kind,
            "table": sink_table,
            "status": sink_result.get('status', 'unknown')
        }
        
        # Extract rows_affected from result data
        if isinstance(sink_result, dict):
            result_data = sink_result.get('data', {})
            result_meta = sink_result.get('meta', {})
            
            # Try to extract row count from various places
            if isinstance(result_data, dict):
                # Check for saved/rows_affected in data
                summary['rows_affected'] = (
                    result_data.get('rows_affected') or
                    result_data.get('saved') or
                    result_data.get('row_count') or
                    result_meta.get('rows_affected', 0)
                )
                
                # Extract execution time if available
                if 'execution_time' in result_data:
                    summary['execution_time'] = result_data['execution_time']
                elif 'elapsed' in result_data:
                    summary['execution_time'] = result_data['elapsed']
            
            # Add any additional metadata
            if isinstance(result_meta, dict):
                summary['tool_info'] = result_meta.get('tool_info', {})
        
        return summary
    
    async def _execute_command(self, command: dict, server_url: str, command_id: str = None):
        """Execute a command and emit events."""
        execution_id = command["execution_id"]
        step = command.get("node_name") or command.get("step")
        tool_kind = command.get("action") or command.get("tool_kind")
        context = command["context"]
        
        # Store execution_id for sub-playbook calls
        self._current_execution_id = execution_id
        
        tool_config = context.get("tool_config", {})
        args = context.get("args", {})
        render_context = context.get("render_context", {})  # Full render context from engine
        case_blocks = context.get("case")  # Case blocks from server for immediate execution
        spec = context.get("spec")  # Step behavior spec (case_mode, eval_mode)

        # Extract case evaluation settings from spec
        case_mode = "exclusive"  # Default: first match wins (XOR-split)
        eval_mode = "on_entry"   # Default: evaluate once
        if spec:
            case_mode = spec.get("case_mode", "exclusive")
            eval_mode = spec.get("eval_mode", "on_entry")
            logger.info(f"[SPEC] Step '{step}' has spec: case_mode={case_mode}, eval_mode={eval_mode}")
        
        # CRITICAL: Merge tool_config.args with top-level args
        # In V2 DSL, step args are often defined within the tool block
        # e.g., tool: {kind: python, args: {name: "value"}, script: {...}}
        # The engine puts these in tool_config.args, but the worker needs them in args
        if "args" in tool_config:
            # Merge with top-level args taking precedence
            merged_args = {**tool_config["args"], **args}
            args = merged_args
            logger.debug(f"Args config: merged_from_tool_config | result={args}")
        else:
            logger.debug(f"Args config: using_top_level | args={args}")
        
        logger.info(f"[EVENT] Executing {step} (tool={tool_kind}) for execution {execution_id}" + (f" command={command_id}" if command_id else ""))
        
        # Ensure execution_id is in render_context for keychain resolution
        if "execution_id" not in render_context:
            render_context["execution_id"] = execution_id
        
        try:
            # Emit command.started event (for event-driven tracking)
            if command_id:
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "command.started",
                    {"command_id": command_id, "worker_id": self.worker_id}
                )
            
            # Emit step.enter event
            await self._emit_event(
                server_url,
                execution_id,
                step,
                "step.enter",
                {"status": "started"}
            )
            
            # Execute tool
            import time
            t_tool_start = time.perf_counter()
            response = await self._execute_tool(tool_kind, tool_config, args, step, render_context, case_blocks=case_blocks)
            t_tool_end = time.perf_counter()
            logger.info(f"[PERF] Tool execution for {step} took {t_tool_end - t_tool_start:.4f}s")
            
            # Note: _internal_data will be cleaned up later (after case sink execution)
            # We keep it in response temporarily so sinks can access the full data
            
            # CRITICAL: Log case blocks at INFO level for debugging
            logger.info(f"[CASE-CHECK] After tool execution for step: {step} | case_blocks present: {case_blocks is not None} | type: {type(case_blocks)}")
            if case_blocks:
                logger.info(f"[CASE-CHECK] case_blocks length: {len(case_blocks)} | value: {case_blocks}")
            
            logger.debug(f"[DEBUG] After tool execution for step: {step}")
            logger.debug(f"[DEBUG] case_blocks type: {type(case_blocks)}, value: {case_blocks}")
            logger.debug(f"[DEBUG] case_blocks is None: {case_blocks is None}")
            logger.debug(f"[DEBUG] case_blocks bool: {bool(case_blocks)}")
            if case_blocks:
                logger.debug(f"[DEBUG] case_blocks length: {len(case_blocks)}")
                for idx, cb in enumerate(case_blocks):
                    logger.debug(f"[DEBUG] case_block[{idx}]: {cb}")

            logger.debug(f"[DEBUG] context has_case={'case' in context} | case_blocks={case_blocks is not None} | case_count={len(case_blocks) if case_blocks else 0}")
            
            # Check if tool returned error status FIRST (before case evaluation)
            # This allows case blocks to handle errors via call.error event
            tool_error = None
            error_response = None
            if isinstance(response, dict):
                if response.get('status') == 'error':
                    tool_error = response.get('error', 'Tool returned error status')
                    error_response = response
                # Also check nested data errors (for tools that return {data: {...}})
                elif isinstance(response.get('data'), dict):
                    for key, value in response['data'].items():
                        if isinstance(value, dict) and value.get('status') == 'error':
                            tool_error = f"{key}: {value.get('message', 'Unknown error')}"
                            error_response = response
                            break
            
            # HYBRID CASE EVALUATION: Worker-side evaluation with both event and data context
            # Evaluate case blocks for BOTH success (call.done) and error (call.error) scenarios
            # Uses CaseEvaluator with proper exclusive/inclusive mode support
            case_action = None
            if case_blocks:
                logger.info(f"[CASE-CHECK] Evaluating case blocks for {step} | mode={case_mode} | has_error={tool_error is not None}")

                # Build evaluation context based on success or error
                eval_event_name = "call.error" if tool_error else "call.done"
                eval_response = error_response if tool_error else response

                # Build evaluation context with all necessary data
                eval_context = build_eval_context(
                    render_context=render_context,
                    response=eval_response,
                    step=step,
                    event_name=eval_event_name,
                    error=tool_error
                )

                # Create evaluator with step's case_mode (default: exclusive)
                evaluator = CaseEvaluator(case_mode=case_mode, eval_mode=eval_mode)
                eval_result = evaluator.evaluate(case_blocks, eval_context, eval_event_name)

                # Process sink actions (execute immediately)
                for action in eval_result.actions:
                    if action.type == "sink":
                        logger.info(f"[CASE-SINK] Executing sink from case {action.case_index}")
                        await self._execute_case_sinks(
                            [case_blocks[action.case_index]],
                            eval_response,
                            render_context,
                            server_url,
                            execution_id,
                            step,
                            event_name="call.done"
                        )

                # Convert routing action to legacy format for compatibility
                if eval_result.routing_action:
                    ra = eval_result.routing_action
                    if ra.type == "next":
                        case_action = {
                            'type': 'next',
                            'steps': ra.config.get('steps', []),
                            'case_index': ra.case_index,
                            'triggered_by': ra.triggered_by
                        }
                    elif ra.type == "retry":
                        case_action = {
                            'type': 'retry',
                            'config': ra.config,
                            'case_index': ra.case_index,
                            'triggered_by': ra.triggered_by
                        }
                    elif ra.type == "set":
                        case_action = {
                            'type': 'set',
                            'config': ra.config,
                            'case_index': ra.case_index,
                            'triggered_by': ra.triggered_by
                        }
                
                # If case action resulted in routing (next/retry), report and handle
                if case_action and case_action.get('type') in ['next', 'retry']:
                    logger.info(f"[CASE-ACTION] Case evaluation triggered {case_action['type']} action for {step}")
                    
                    # ARCHITECTURE PRINCIPLE #3:
                    # Report case action to server via ACTIONABLE event
                    # Server will issue new command with rendered args from case_action.config
                    # This follows server-worker-server control loop pattern
                    await self._emit_event(
                        server_url,
                        execution_id,
                        step,
                        "case.evaluated",
                        {
                            "action": case_action,
                            "result": eval_response,  # Data reference only (no full payload)
                            "triggered_by": eval_event_name
                        },
                        actionable=True,  # Server should process this for routing
                        informative=True
                    )
                    
                    # Emit appropriate event based on success or error
                    if tool_error:
                        await self._emit_event(
                            server_url,
                            execution_id,
                            step,
                            "call.error",
                            {
                                "error": tool_error,
                                "response": error_response,
                                "case_handled": True
                            },
                            actionable=True,  # Case evaluated - server may route/retry
                            informative=True
                        )
                    else:
                        await self._emit_event(
                            server_url,
                            execution_id,
                            step,
                            "call.done",
                            response,
                            actionable=True,
                            informative=True
                        )
                    
                    await self._emit_event(
                        server_url,
                        execution_id,
                        step,
                        "step.exit",
                        {
                            "status": "COMPLETED" if not tool_error else "CASE_HANDLED",
                            "result": eval_response,
                            "case_action": case_action
                        },
                        actionable=True,  # Server should handle routing
                        informative=True
                    )
                    
                    # Emit command.completed
                    if command_id:
                        await self._emit_event(
                            server_url,
                            execution_id,
                            step,
                            "command.completed",
                            {
                                "command_id": command_id,
                                "worker_id": self.worker_id,
                                "result": eval_response,
                                "case_action": case_action
                            },
                            actionable=False,  # Informational - case.evaluated has action
                            informative=True
                        )
                    
                    logger.info(f"[EVENT] Completed {step} with case action for execution {execution_id}")
                    return  # Exit - server will handle routing based on case_action
            
            # No case action handled it - check for unhandled tool errors
            if tool_error:
                # Tool returned error - treat as failure (no case handled it)
                logger.error(f"Tool execution failed for {step}: {tool_error}")
                
                # Emit call.error with error payload - ACTIONABLE for server to handle
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "call.error",
                    {"error": tool_error, "response": error_response},
                    actionable=True,  # Server should evaluate case blocks or fail
                    informative=True
                )
                
                # Emit step.exit with failed status
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "step.exit",
                    {
                        "status": "FAILED",  # Uppercase to match database status values
                        "error": tool_error,
                        "result": error_response
                    },
                    actionable=True,  # Server may want to handle failure
                    informative=True
                )
                
                # Emit command.failed event
                if command_id:
                    await self._emit_event(
                        server_url,
                        execution_id,
                        step,
                        "command.failed",
                        {
                            "command_id": command_id,
                            "worker_id": self.worker_id,
                            "error": tool_error,
                            "result": error_response
                        },
                        actionable=False,  # Informational
                        informative=True
                    )
                
                logger.error(f"[EVENT] Failed {step} for execution {execution_id}" + (f" command={command_id}" if command_id else ""))
                return  # Exit without emitting completed events
            
            # Tool succeeded - emit success events with error recovery
            try:
                # Clean up _internal_data and data before emitting events (sink-driven pattern)
                # This prevents large payloads from being stored in events/NATS
                if isinstance(response, dict):
                    response_data = response.get('data', {})
                    if isinstance(response_data, dict):
                        # Remove _internal_data (actual response for sink execution)
                        internal_data = response_data.pop('_internal_data', None)
                        # Also remove 'data' field which is a duplicate for backwards compat
                        response_data.pop('data', None)
                        
                        if internal_data:
                            logger.info(
                                f"[SINK-DRIVEN] Removed _internal_data and data before event emission | "
                                f"payload_size_reduction: ~{len(str(internal_data))} bytes"
                            )
                            logger.info(f"[SINK-DRIVEN] Response now contains only reference: {response_data.get('data_reference', {})}")
                
                # Emit call.done event - ACTIONABLE so server evaluates routing
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "call.done",
                    {"response": response},
                    actionable=True,  # Server should evaluate next/case routing
                    informative=True
                )
                
                # Emit step.exit event
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "step.exit",
                    {"result": response, "status": "completed"},
                    actionable=True,  # Server evaluates routing
                    informative=True
                )
                
                # Emit command.completed event (for event-driven tracking)
                if command_id:
                    await self._emit_event(
                        server_url,
                        execution_id,
                        step,
                        "command.completed",
                        {
                            "command_id": command_id,
                            "worker_id": self.worker_id,
                            "result": response
                        },
                        actionable=False,  # Informational only
                        informative=True
                    )
                
                logger.info(f"[EVENT] Completed {step} for execution {execution_id}" + (f" command={command_id}" if command_id else ""))
                
            except Exception as emit_error:
                # Event emission failed - try to report failure
                logger.exception(f"Failed to emit success events for {step}: {emit_error}")
                try:
                    # Attempt to emit command.failed to mark execution as failed
                    if command_id:
                        await self._emit_event(
                            server_url,
                            execution_id,
                            step,
                            "command.failed",
                            {
                                "command_id": command_id,
                                "worker_id": self.worker_id,
                                "error": f"Event emission failed: {str(emit_error)}"
                            }
                        )
                except Exception as recovery_error:
                    logger.exception(f"Failed to emit recovery failure event: {recovery_error}")
                # Re-raise so the command handler knows it failed
                raise emit_error
            
        except Exception as e:
            logger.error(f"Execution error for {step}: {e}", exc_info=True)
            
            # Emit error event
            await self._emit_event(
                server_url,
                execution_id,
                step,
                "call.error",
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
            
            # Emit command.failed event (for event-driven tracking)
            if command_id:
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "command.failed",
                    {
                        "command_id": command_id,
                        "worker_id": self.worker_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                )
            
            # Pure event-driven: No queue table operations needed
    
    async def _execute_tool(
        self,
        tool_kind: str,
        config: dict,
        args: dict,
        step: str,
        render_context: dict,
        case_blocks: Optional[list] = None
    ) -> Any:
        """
        Execute tool using noetl/tools/* implementations.
        
        This delegates to the mature tool system which includes:
        - Script loading (GCS, S3, HTTP, file)
        - Authentication resolution and caching
        - Pagination and retry logic
        - Event callbacks for progress tracking
        - Template rendering
        - Error handling
        
        Args:
            tool_kind: Tool type (http, postgres, python, etc.)
            config: Tool configuration
            args: Tool arguments
            step: Step name
            render_context: Full render context with workload, step results, etc.
            case_blocks: Optional case blocks for sink-driven result references
        """
        # Tool executors are pre-imported at module level for fast execution
        
        # Use render_context from engine (includes workload, step results, execution_id, etc.)
        # This allows plugins to render Jinja2 templates with full state
        context = render_context if render_context else {"args": args, "step": step}
        
        logger.info(f"WORKER: Initial context keys={list(context.keys())} | execution_id={context.get('execution_id')} | catalog_id={context.get('catalog_id')}")
        
        # Note: catalog_id should come from server in render_context
        # Worker does NOT query noetl database - only executes tool steps
        
        # Add job metadata to context for {{ job.uuid }} templates
        if "job" not in context:
            context["job"] = {
                "uuid": context.get("execution_id", ""),
                "execution_id": context.get("execution_id", "")
            }
        
        # Resolve keychain references before tool execution
        # This scans the config for {{ keychain.* }} references and populates context['keychain']
        catalog_id = context.get('catalog_id')
        execution_id = context.get('execution_id')
        if catalog_id:
            # Combine config and args into single dict for scanning
            task_config_combined = {**config, **args}
            server_url = context.get('server_url', 'http://noetl.noetl.svc.cluster.local:8082')
            
            # Get refresh threshold from settings
            from noetl.core.config import get_worker_settings
            worker_settings = get_worker_settings()
            refresh_threshold = worker_settings.keychain_refresh_threshold
            
            import time
            k_start = time.perf_counter()
            context = await populate_keychain_context(
                task_config=task_config_combined,
                context=context,
                catalog_id=catalog_id,
                execution_id=execution_id,
                api_base_url=server_url,
                refresh_threshold_seconds=refresh_threshold
            )
            k_end = time.perf_counter()
            logger.info(f"[PERF] populate_keychain_context took {k_end - k_start:.4f}s")
        
        import time
        t_jinja_start = time.perf_counter()
        from jinja2 import Environment, BaseLoader
        from noetl.core.dsl.render import add_b64encode_filter
        from noetl.core.auth.token_resolver import register_token_functions
        
        jinja_env = Environment(loader=BaseLoader())
        jinja_env = add_b64encode_filter(jinja_env)  # Add custom filters including tojson
        register_token_functions(jinja_env, context)
        t_jinja_end = time.perf_counter()
        logger.info(f"[PERF] Jinja2 setup took {t_jinja_end - t_jinja_start:.4f}s")
        
        # Map V2 config format to plugin task_config format
        # Plugins use different field names than V2 DSL
        # For workbook tool, preserve 'name' field from config (it's the workbook action name)
        # For other tools, add 'name' as step name for logging
        task_config = {**config, "args": args}
        if "name" not in config:
            task_config["name"] = step
        
        if tool_kind == "python":
            # Use plugin's execute_python_task_async (not the sync wrapper!)
            # This includes:
            # - Script loading (GCS/S3/HTTP/file)
            # - Base64 code support
            # - Kwargs unpacking
            # - Error handling
            result = await execute_python_task_async(task_config, context, jinja_env, args)
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            # Normalize result - plugin returns dict, may need to extract 'data' or 'result'
            if isinstance(result, dict):
                return result.get('data', result.get('result', result))
            return result
            
        elif tool_kind == "http":
            # Check if retry config has pagination/success-driven repeats (next_call or collect)
            # If so, use execute_with_retry which handles per-iteration sinks
            retry_config = config.get('retry') if isinstance(config, dict) else None
            has_pagination_retry = False
            if isinstance(retry_config, list):
                for idx, policy in enumerate(retry_config):
                    if isinstance(policy, dict) and 'then' in policy:
                        then_block = policy['then']
                        has_next_call = 'next_call' in then_block if isinstance(then_block, dict) else False
                        has_collect = 'collect' in then_block if isinstance(then_block, dict) else False
                        if isinstance(then_block, dict) and (has_next_call or has_collect):
                            has_pagination_retry = True
                            break
            
            logger.debug(f"HTTP TOOL: config_keys={list(config.keys()) if isinstance(config, dict) else 'not dict'} | retry={retry_config is not None} | policies={len(retry_config) if isinstance(retry_config, list) else 0} | has_pagination={has_pagination_retry}")
            
            if has_pagination_retry:
                logger.info("HTTP tool using execute_with_retry for pagination sink support")
                # Use retry-aware executor which handles per-iteration sinks
                from noetl.core.runtime.retry import execute_with_retry
                
                # Create executor function that wraps async execute_http_task
                def http_executor(cfg, ctx, env, task_w):
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        # No running loop - create one
                        return asyncio.run(execute_http_task(cfg, ctx, env, task_w or {}))
                    else:
                        # Running in existing loop - run in executor to avoid blocking
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            future = pool.submit(
                                lambda: asyncio.run(execute_http_task(cfg, ctx, env, task_w or {}))
                            )
                            return future.result()
                
                # Execute with retry handler (supports per-iteration sinks)
                result = execute_with_retry(
                    http_executor,
                    task_config,
                    step,
                    context,
                    jinja_env,
                    args
                )
                
                # Check if retry handler returned error status
                if isinstance(result, dict) and result.get('status') == 'error':
                    return result
                # Normalize result
                if isinstance(result, dict):
                    return result.get('data', result)
                return result
            else:
                # No pagination retry - use direct execution (original path)
                # Use plugin's execute_http_task which includes:
                # - Auth resolution and credential caching
                # - Template rendering
                # - Response processing
                
                # Extract sink_config from case_blocks if present
                sink_config = None
                if case_blocks and isinstance(case_blocks, list):
                    for case in case_blocks:
                        if not isinstance(case, dict):
                            continue
                        then_block = case.get('then')
                        if not then_block:
                            continue
                        # Normalize then_block to list
                        then_actions = then_block if isinstance(then_block, list) else [then_block]
                        # Look for sink in any then action
                        for action in then_actions:
                            if isinstance(action, dict) and 'sink' in action:
                                sink_config = action['sink']
                                logger.info(f"[SINK-DRIVEN] Extracted sink config from case blocks: {sink_config.get('tool', {}).get('kind')}")
                                break
                        if sink_config:
                            break
                
                task_with = args  # Plugin uses 'task_with' for rendered params
                result = await execute_http_task(task_config, context, jinja_env, task_with, sink_config=sink_config)
                # Check if plugin returned error status
                if isinstance(result, dict) and result.get('status') == 'error':
                    # Keep error response intact (worker needs status field to detect error)
                    return result
                # Normalize result
                if isinstance(result, dict):
                    return result.get('data', result)
                return result
            
        elif tool_kind == "postgres":
            # Use plugin's execute_postgres_task (sync function - run in executor)
            # Pass full tool config as task_with to ensure auth is available
            task_with = {**config, **args}  # Merge config (has auth) with args
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, 
                lambda: execute_postgres_task(task_config, context, jinja_env, task_with)
            )
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            return result.get('data', result) if isinstance(result, dict) else result
            
        elif tool_kind == "duckdb":
            # Use plugin's execute_duckdb_task (sync function - run in executor)
            # Pass full tool config as task_with to ensure auth is available
            task_with = {**config, **args}  # Merge config (has auth) with args
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_duckdb_task(task_config, context, jinja_env, task_with)
            )
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            return result.get('data', result) if isinstance(result, dict) else result

        elif tool_kind == "ducklake":
            # Use plugin's execute_ducklake_task (sync function - run in executor)
            from noetl.tools.ducklake import execute_ducklake_task
            # Pass full tool config as task_with to ensure auth is available
            task_with = {**config, **args}  # Merge config (has auth) with args
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_ducklake_task(task_config, context, jinja_env, task_with)
            )
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            return result.get('data', result) if isinstance(result, dict) else result

        elif tool_kind == "snowflake":
            # Use plugin's execute_snowflake_task (sync wrapper)
            # Pass full tool config as task_with to ensure auth is available
            task_with = {**config, **args}  # Merge config (has auth) with args
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_snowflake_task(task_config, context, jinja_env, task_with)
            )
            if isinstance(result, dict) and result.get('status') == 'error':
                return result
            return result.get('data', result) if isinstance(result, dict) else result

        elif tool_kind == "transfer":
            # Generic transfer action (may delegate to Snowflake/Postgres executors)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_transfer_action(task_config, context, jinja_env, args)
            )
            if isinstance(result, dict) and result.get('status') == 'error':
                return result
            return result.get('data', result) if isinstance(result, dict) else result

        elif tool_kind == "snowflake_transfer":
            # Explicit snowflake_transfer action (legacy specialized executor)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_snowflake_transfer_action(task_config, context, jinja_env, args)
            )
            if isinstance(result, dict) and result.get('status') == 'error':
                return result
            return result.get('data', result) if isinstance(result, dict) else result

        elif tool_kind == "script":
            # Execute script as Kubernetes job (async plugin)
            result = await execute_script_task(task_config, context, jinja_env, args)
            if isinstance(result, dict) and result.get('status') == 'error':
                return result
            return result
            
        elif tool_kind == "secrets":
            # Use plugin's execute_secrets_task (sync function - run in executor)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_secrets_task(task_config, context, jinja_env)
            )
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            return result.get('data', result) if isinstance(result, dict) else result
            
        elif tool_kind == "sink":
            # Use plugin's execute_sink_task (sync function - run in executor)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_sink_task(task_config, context, jinja_env)
            )
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            return result.get('data', result) if isinstance(result, dict) else result
            
        elif tool_kind == "workbook":
            # Call async execute_workbook_task directly (don't use executor for async functions)
            result = await execute_workbook_task(task_config, context, jinja_env, args)
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            return result.get('data', result) if isinstance(result, dict) else result
            
        elif tool_kind == "playbook":
            # Use plugin's execute_playbook_task (sync function - run in executor)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_playbook_task(task_config, context, jinja_env, args)
            )
            return result
            
        elif tool_kind == "gcs":
            # Use plugin's execute_gcs_task (sync function - run in executor)
            task_with = {**config, **args}  # Merge config (has source, destination, credential) with args
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: execute_gcs_task(task_config, context, jinja_env, task_with)
            )
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                # Keep error response intact (worker needs status field to detect error)
                return result
            return result.get('data', result) if isinstance(result, dict) else result
            
        elif tool_kind == "container":
            # Container execution - keep inline for now as it's V2-specific
            return await self._execute_container(config, args)
            
        elif tool_kind == "script":
            # Script loading is now handled by python plugin via 'script' field
            # This is a legacy fallback
            return await self._execute_script(config, args)

        elif tool_kind == "gateway":
            # Gateway tool for async callbacks to API gateway
            from noetl.tools.gateway import execute_gateway_task
            task_with = {**config, **args}
            result = await execute_gateway_task(task_config, context, jinja_env, task_with)
            # Check if plugin returned error status
            if isinstance(result, dict) and result.get('status') == 'error':
                return result
            return result.get('data', result) if isinstance(result, dict) else result

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
        logger.info(f"HTTP {method} request to URL: {url} | headers={headers} | params={params}")
        
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
            from noetl.core.common import get_pgdb_connection
            import psycopg
            
            conn_params = get_pgdb_connection()
            async with await psycopg.AsyncConnection.connect(**conn_params) as conn:
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
        server_url = os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        # Get current execution_id to pass as parent
        parent_execution_id = getattr(self, '_current_execution_id', None)
        
        payload = {"path": path, "payload": args}
        if parent_execution_id:
            payload["parent_execution_id"] = parent_execution_id
        
        response = await self._http_client.post(
            f"{server_url}/api/execute",
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
                    f"{server_url}/api/executions/{execution_id}",
                    timeout=10.0
                )
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    state_completed = bool(status_data.get("completed"))
                    state_failed = bool(status_data.get("failed"))
                    
                    if state_completed or state_failed:
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
            from noetl.core.common import get_pgdb_connection
            import psycopg
            
            conn_params = get_pgdb_connection()
            async with await psycopg.AsyncConnection.connect(**conn_params) as conn:
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
        payload: dict,
        actionable: bool = False,
        informative: bool = True,
        correlation: dict = None,
        inputs: dict = None
    ):
        """
        Emit an event to the server using the v2 API schema with retry logic.
        
        Implements ResultRef pattern for efficient result storage:
        - Small results (< inline_max_bytes) stored directly in output_inline
        - Large results stored as artifacts with output_ref pointer
        - Correlation keys (iteration, page, attempt) for tracking
        - Actionable/informative flags for control flow
        
        Args:
            server_url: Server API URL
            execution_id: Execution identifier
            step: Step name
            name: Event name (e.g., call.done, step.exit)
            payload: Event payload data
            actionable: If True, server should take action (evaluate case, route)
            informative: If True, event is for logging/observability
            correlation: Optional correlation keys dict (iteration, page, attempt)
            inputs: Optional rendered input snapshot
        """
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")
        
        event_url = f"{server_url.rstrip('/')}/api/events"
        
        # Build event data - server handles result storage (kind: data|ref|refs)
        event_data = {
            "execution_id": str(execution_id),
            "step": step,
            "name": name,
            "payload": payload,
            "worker_id": self.worker_id,
            "actionable": actionable,
            "informative": informative,
        }
            
        # Add correlation keys if provided
        if correlation:
            event_data["correlation"] = correlation
        
        from noetl.core.config import get_worker_settings
        worker_settings = get_worker_settings()
        
        max_retries = 3
        base_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"[HTTP] POST {event_url} - Event: {name} for {step} (execution {execution_id}) - Attempt {attempt + 1}/{max_retries}")
                
                response = await self._http_client.post(
                    event_url,
                    json=event_data,
                    timeout=worker_settings.http_event_timeout
                )
                response.raise_for_status()
                
                logger.info(f"[HTTP] Event {name} sent successfully - Status: {response.status_code}")
                return  # Success - exit retry loop
                
            except Exception as e:
                is_last_attempt = (attempt == max_retries - 1)
                
                if is_last_attempt:
                    logger.error(f"[HTTP] Failed to emit event {name} after {max_retries} attempts: {e}", exc_info=True)
                    raise RuntimeError(f"Event emission failed after {max_retries} retries: {e}") from e
                else:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"[HTTP] Event {name} emission failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)


async def run_v2_worker(
    worker_id: str,
    nats_url: str = "nats://noetl:noetl@nats.nats.svc.cluster.local:4222",
    server_url: Optional[str] = None
):
    """Run a V2 worker instance."""
    # Set environment variable to indicate worker context (for TransientVars API routing)
    os.environ["NOETL_WORKER_MODE"] = "true"
    
    # No database pool initialization - worker uses server API for all noetl schema access
    # Only tool steps (postgres, duckdb) access external databases with their own credentials
    logger.info("V2 Worker uses server API for variables, events, and context (no direct DB access)")
    
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
    
    try:
        
        # Get from environment or use defaults
        nats_url = os.getenv("NATS_URL", nats_url)
        server_url = server_url or os.getenv("NOETL_SERVER_URL", "http://noetl.noetl.svc.cluster.local:8082")
        
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        
        with open("/tmp/worker_config.txt", "w") as f:
            f.write(f"Worker ID: {worker_id}\n")
            f.write(f"NATS URL: {nats_url}\n")
            f.write(f"Server URL: {server_url}\n")
            f.flush()
        
        logger.info(f"Starting V2 worker {worker_id} | NATS={nats_url} | Server={server_url}")
        
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
        logger.info("Worker interrupted by user")
        sys.exit(0)
    except Exception as e:
        with open("/tmp/worker_error.txt", "w") as f:
            f.write(f"Error at {datetime.now()}: {e}\n")
            import traceback
            f.write(traceback.format_exc())
            f.flush()
        
        logger.error(f"Worker failed to start: {e}", exc_info=True)
        sys.exit(1)
