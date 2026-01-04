"""
NoETL V2 Worker with NATS Integration

Event-driven worker that:
1. Subscribes to NATS for command notifications
2. Fetches command details from server queue API  
3. Executes based on tool.kind
4. Emits events back to server (POST /api/events)

NO backward compatibility - pure V2 implementation.
"""

import asyncio
import logging
import httpx
import os
from typing import Optional, Any
from datetime import datetime, timezone


from noetl.core.messaging import NATSCommandSubscriber
from noetl.core.logging_context import LoggingContext
from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


class V2Worker:
    """
    V2 Worker that receives command notifications from NATS and executes them.
    
    Architecture:
    - Subscribes to NATS subject for command notifications
    - Receives lightweight message with {execution_id, queue_id, step, server_url}
    - Fetches full command from server API
    - Executes tool based on tool.kind
    - Emits events to POST /api/events
    - NEVER directly updates queue table (server does this via events)
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
    
    async def start(self):
        """Start the worker NATS subscription."""
        from noetl.core.config import get_worker_settings
        worker_settings = get_worker_settings()
        self._running = True
        self._http_client = httpx.AsyncClient(timeout=30.0)
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
        
        # Subscribe to command notifications (this should never return)
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
                
                # Attempt to claim the command atomically
                claimed = await self._claim_command(server_url, execution_id, command_id)
                
                if not claimed:
                    logger.info(f"[EVENT] Command {command_id} already claimed by another worker - skipping")
                    return
                
                logger.info(f"[EVENT] Worker {self.worker_id} claimed command {command_id}")
                
                # Fetch command details from command.issued event
                command = await self._fetch_command_details(server_url, event_id)
                
                if not command:
                    logger.error(f"[EVENT] Failed to fetch command details for event_id={event_id}")
                    await self._emit_command_failed(server_url, execution_id, command_id, step, "Failed to fetch command details")
                    return
                
                # Execute the command
                await self._execute_command(command, server_url, command_id)
                
            except Exception as e:
                logger.exception(f"Error handling command notification: {e}")
    
    async def _claim_command(self, server_url: str, execution_id: int, command_id: str) -> bool:
        """
        Atomically claim a command by emitting command.claimed event.
        
        Uses idempotent event insertion - if another worker already claimed,
        the INSERT will fail and we return False.
        
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
                result = response.json()
                # If commands_generated > 0 or status is "ok", we claimed it
                # The server should prevent duplicate claims via unique constraint
                logger.info(f"[EVENT] Successfully claimed command {command_id}")
                return True
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
    
    async def _fetch_command(self, server_url: str, queue_id: int) -> Optional[dict]:
        """
        DEPRECATED: Old queue-based command fetching.
        
        Kept for backward compatibility but should not be used in event-driven architecture.
        
        Uses SELECT FOR UPDATE SKIP LOCKED pattern for distributed queue processing.
        This ensures:
        1. Row-level locking prevents multiple workers from processing same command
        2. SKIP LOCKED allows workers to skip already-locked rows
        3. Transaction isolation ensures visibility after commit
        
        Implements retry logic to handle PostgreSQL connection pooling delays.
        
        Returns command dict or None if not available.
        """
        logger.info(
            f"[QUEUE] Queue subsystem removed; _fetch_command is a no-op for queue_id={queue_id}"
        )
        return None
    
    async def _execute_case_sinks(
        self,
        case_blocks: list,
        response: Any,
        render_context: dict,
        server_url: str,
        execution_id: int,
        step: str
    ):
        """
        Execute sinks from case blocks immediately after tool execution.
        
        Evaluates case conditions against response and executes matching sinks.
        Reports sink execution back to server via events.
        """
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
        # Normalize response: if it has 'data' key, unwrap it for cleaner access
        current_result = (
            response.get("data")
            if isinstance(response, dict) and response.get("data") is not None
            else response
        )
        
        eval_context = {
            **render_context,
            'response': response,
            'result': current_result,  # Add result for {{ result }} templates
            'data': current_result,    # Add data for {{ data }} templates
            'this': response,          # Add this for {{ this }} (full response)
            'event': {'name': 'step.exit'},  # Use step.exit to match playbook conditions
            'error': response.get('error') if isinstance(response, dict) else None
        }
        
        # Check each case block
        for idx, case in enumerate(case_blocks):
            if not isinstance(case, dict):
                continue
                
            when_condition = case.get('when')
            then_block = case.get('then')
            
            if not when_condition or not then_block or not isinstance(then_block, dict):
                continue
            
            # Extract case components (order doesn't matter in YAML)
            collect_config = then_block.get('collect')
            sink_config = then_block.get('sink')
            retry_config = then_block.get('retry')
            
            # Skip if no sink to execute (we only care about sinks here)
            if not sink_config:
                continue
            
            logger.info(f"[SINK] Case block {idx} has sink, evaluating condition: {when_condition}")
            
            # Evaluate condition
            try:
                # when_condition is already a Jinja2 template (e.g., "{{ event.name == 'step.exit' }}")
                # so render it directly without wrapping it again
                template = jinja_env.from_string(when_condition)
                result = template.render(eval_context)
                # Result should be a boolean or string that evaluates to boolean
                if isinstance(result, bool):
                    condition_met = result
                elif isinstance(result, str):
                    condition_met = result.lower() in ('true', '1', 'yes')
                else:
                    condition_met = bool(result)
                
                logger.info(f"[SINK] Condition result: {result} -> {condition_met}")
                
                if not condition_met:
                    continue
                
                # Condition met - execute in semantic order: collect → sink → retry
                # Note: collect and retry are handled by server/engine, we only execute sink
                
                logger.info(f"[SINK] Executing sink for case {idx}")
                
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
                
                # Report sink execution via event
                sink_kind = sink_config.get('tool', {}).get('kind', 'unknown')
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "sink.executed",
                    {
                        "case_index": idx,
                        "sink_type": sink_kind,
                        "result": sink_result,
                        "has_collect": collect_config is not None,
                        "has_retry": retry_config is not None
                    }
                )
                    
            except Exception as e:
                logger.error(f"[SINK] Error executing sink for case {idx}: {e}", exc_info=True)
                # Report sink failure
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "sink.failed",
                    {
                        "case_index": idx,
                        "error": str(e)
                    }
                )
    
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
            response = await self._execute_tool(tool_kind, tool_config, args, step, render_context)
            
            logger.debug(f"[DEBUG] After tool execution for step: {step}")
            logger.debug(f"[DEBUG] case_blocks type: {type(case_blocks)}, value: {case_blocks}")
            logger.debug(f"[DEBUG] case_blocks is None: {case_blocks is None}")
            logger.debug(f"[DEBUG] case_blocks bool: {bool(case_blocks)}")
            if case_blocks:
                logger.debug(f"[DEBUG] case_blocks length: {len(case_blocks)}")
                for idx, cb in enumerate(case_blocks):
                    logger.debug(f"[DEBUG] case_block[{idx}]: {cb}")

            logger.debug(f"[DEBUG] context has_case={'case' in context} | case_blocks={case_blocks is not None} | case_count={len(case_blocks) if case_blocks else 0}")
            
            # SINK EXECUTION: Check for case blocks with sinks and execute immediately
            if case_blocks:
                await self._execute_case_sinks(
                    case_blocks,
                    response,
                    render_context,
                    server_url,
                    execution_id,
                    step
                )
            
            # Check if tool returned error status
            tool_error = None
            if isinstance(response, dict):
                if response.get('status') == 'error':
                    tool_error = response.get('error', 'Tool returned error status')
                # Also check nested data errors (for tools that return {data: {...}})
                elif isinstance(response.get('data'), dict):
                    for key, value in response['data'].items():
                        if isinstance(value, dict) and value.get('status') == 'error':
                            tool_error = f"{key}: {value.get('message', 'Unknown error')}"
                            break
            
            if tool_error:
                # Tool returned error - treat as failure
                logger.error(f"Tool execution failed for {step}: {tool_error}")
                
                # Emit call.error with error payload
                await self._emit_event(
                    server_url,
                    execution_id,
                    step,
                    "call.error",
                    {"error": tool_error}
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
                        "result": response
                    }
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
                            "result": response
                        }
                    )
                
                logger.error(f"[EVENT] Failed {step} for execution {execution_id}" + (f" command={command_id}" if command_id else ""))
                return  # Exit without emitting completed events
            
            # Tool succeeded - emit success events with error recovery
            try:
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
                        }
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
        render_context: dict
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
        """
        # Import tool executors
        from noetl.tools import (
            http,
            postgres,
            duckdb,
            python,
        )
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
        # Import async version of Python executor
        from noetl.tools.python import execute_python_task_async
        from jinja2 import Environment, BaseLoader
        from noetl.worker.keychain_resolver import populate_keychain_context
        
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
            
            context = await populate_keychain_context(
                task_config=task_config_combined,
                context=context,
                catalog_id=catalog_id,
                execution_id=execution_id,
                api_base_url=server_url,
                refresh_threshold_seconds=refresh_threshold
            )
        
        from jinja2 import Environment, BaseLoader
        from noetl.core.dsl.render import add_b64encode_filter
        from noetl.core.auth.token_resolver import register_token_functions
        
        jinja_env = Environment(loader=BaseLoader())
        jinja_env = add_b64encode_filter(jinja_env)  # Add custom filters including tojson
        register_token_functions(jinja_env, context)
        
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
                task_with = args  # Plugin uses 'task_with' for rendered params
                result = await execute_http_task(task_config, context, jinja_env, task_with)
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
        payload: dict
    ):
        """Emit an event to the server."""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")
        
        event_url = f"{server_url.rstrip('/')}/api/events"
        event_data = {
            "execution_id": str(execution_id),
            "step": step,
            "name": name,
            "payload": payload,
            "worker_id": self.worker_id
        }
        
        logger.info(f"[HTTP] POST {event_url} - Event: {name} for {step} (execution {execution_id})")
        
        try:
            response = await self._http_client.post(
                event_url,
                json=event_data,
                timeout=10.0
            )
            response.raise_for_status()
            
            logger.info(f"[HTTP] Event {name} sent successfully - Status: {response.status_code}")
            
        except Exception as e:
            logger.error(f"[HTTP] Failed to emit event {name} to {event_url}: {e}", exc_info=True)
            raise


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
