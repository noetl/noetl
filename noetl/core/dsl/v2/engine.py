async def finalize_abandoned_execution(self, execution_id: str, reason: str = "Abandoned or timed out"):
    """
    Forcibly finalize an execution by emitting workflow.failed and playbook.failed events if not already completed.
    This should be called by a periodic task or admin action for stuck/running executions with no activity.
    """
    # Load state
    state = await self.state_store.load_state(execution_id)
    if not state:
        logger.error(f"[FINALIZE] No state found for execution {execution_id}")
        return
    if state.completed:
        logger.info(f"[FINALIZE] Execution {execution_id} already completed; skipping.")
        return

    # Find last step (if any)
    last_step = state.current_step or (list(state.step_results.keys())[-1] if state.step_results else None)
    logger.warning(f"[FINALIZE] Forcibly finalizing execution {execution_id} at step {last_step} due to: {reason}")

    from noetl.core.dsl.v2.models import Event, LifecycleEventPayload
    from datetime import datetime, timezone

    # Emit workflow.failed event
    workflow_failed_event = Event(
        execution_id=execution_id,
        step="workflow",
        name="workflow.failed",
        payload=LifecycleEventPayload(
            status="failed",
            final_step=last_step,
            result=None,
            error={"message": reason}
        ).model_dump(),
        timestamp=datetime.now(timezone.utc)
    )
    await self._persist_event(workflow_failed_event, state)

    # Emit playbook.failed event
    playbook_path = state.playbook.metadata.get("path", "playbook")
    playbook_failed_event = Event(
        execution_id=execution_id,
        step=playbook_path,
        name="playbook.failed",
        payload=LifecycleEventPayload(
            status="failed",
            final_step=last_step,
            result=None,
            error={"message": reason}
        ).model_dump(),
        timestamp=datetime.now(timezone.utc)
    )
    await self._persist_event(playbook_failed_event, state)

    # Mark state as completed
    state.completed = True
    await self.state_store.save_state(state)
    logger.info(f"[FINALIZE] Emitted terminal events for execution {execution_id}")
"""
NoETL V2 Execution Engine

Event-driven control flow engine that:
1. Consumes events from workers
2. Evaluates case/when/then rules  
3. Emits commands to queue table
4. Maintains execution state

No backward compatibility - pure v2 implementation.
"""

import logging
import os
from typing import Any, Optional
from datetime import datetime, timezone
from jinja2 import Template, Environment, StrictUndefined
from psycopg.types.json import Json

from noetl.core.dsl.v2.models import Event, Command, Playbook, Step, CaseEntry, ToolCall
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.cache import get_nats_cache

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


class ExecutionState:
    """Tracks state of a playbook execution."""
    
    def __init__(self, execution_id: str, playbook: Playbook, payload: dict[str, Any], catalog_id: Optional[int] = None, parent_execution_id: Optional[int] = None):
        self.execution_id = execution_id
        self.playbook = playbook
        self.payload = payload
        self.catalog_id = catalog_id  # Store catalog_id for event persistence
        self.parent_execution_id = parent_execution_id  # Track parent execution for sub-playbooks
        self.current_step: Optional[str] = None
        self.variables: dict[str, Any] = {}
        self.last_event_id: Optional[int] = None  # Track last persisted event ID
        self.step_event_ids: dict[str, int] = {}  # Track last event per step
        self.step_results: dict[str, Any] = {}
        self.completed_steps: set[str] = set()
        self.failed = False
        self.completed = False
        
        # Root event tracking for traceability
        self.root_event_id: Optional[int] = None  # First event (playbook.initialized) for full trace
        
        # Loop state tracking
        self.loop_state: dict[str, dict[str, Any]] = {}  # step_name -> {collection, index, item, mode}
        
        # Pagination state tracking for collect+retry pattern
        self.pagination_state: dict[str, dict[str, Any]] = {}  # step_name -> {collected_data: [], iteration_count: int}
        
        # Initialize workload variables
        if playbook.workload:
            self.variables.update(playbook.workload)
        
        # Merge payload
        # CRITICAL: If payload contains 'workload' or 'vars', it can overwrite sub-playbook state.
        # We only merge keys that are NOT 'workload' or 'vars' directly into self.variables
        # unless they are explicitly intended to be there.
        for k, v in payload.items():
            if k not in ("workload", "vars"):
                self.variables[k] = v
            else:
                # If it's workload/vars, deep merge instead of overwrite if they exist
                if k in self.variables and isinstance(self.variables[k], dict) and isinstance(v, dict):
                    self.variables[k].update(v)
                else:
                    self.variables[k] = v
    
    def get_step(self, step_name: str) -> Optional[Step]:
        """Get step by name."""
        for step in self.playbook.workflow:
            if step.step == step_name:
                return step
        return None
    
    def set_current_step(self, step_name: str):
        """Set current executing step."""
        self.current_step = step_name
    
    def mark_step_completed(self, step_name: str, result: Any = None):
        """Mark step as completed and store result in memory and transient."""
        self.completed_steps.add(step_name)
        if result is not None:
            self.step_results[step_name] = result
            self.variables[step_name] = result
            # Also persist to transient for rendering in subsequent steps
            # This is done async in the engine after calling mark_step_completed
    
    def is_step_completed(self, step_name: str) -> bool:
        """Check if step is completed."""
        return step_name in self.completed_steps
    
    def init_loop(self, step_name: str, collection: list[Any], iterator: str, mode: str = "sequential", event_id: Optional[int] = None):
        """Initialize loop state for a step.
        
        Args:
            step_name: Name of the step
            collection: Collection to iterate over
            iterator: Iterator variable name
            mode: Iteration mode (sequential or parallel)
            event_id: Event ID that initiated this loop instance (for uniqueness)
        """
        self.loop_state[step_name] = {
            "collection": collection,
            "iterator": iterator,
            "index": 0,
            "mode": mode,
            "completed": False,
            "results": [],  # Track iteration results for aggregation
            "failed_count": 0,  # Track failed iterations
            "event_id": event_id  # Track which event initiated this loop instance
        }
        logger.debug(f"Initialized loop for step {step_name}: {len(collection)} items, mode={mode}, event_id={event_id}")
    
    def get_next_loop_item(self, step_name: str) -> tuple[Any, int] | None:
        """Get next item from loop. Returns (item, index) or None if done."""
        if step_name not in self.loop_state:
            return None
        
        state = self.loop_state[step_name]
        if state["completed"]:
            return None
        
        collection = state["collection"]
        index = state["index"]
        
        if index >= len(collection):
            state["completed"] = True
            return None
        
        item = collection[index]
        state["index"] = index + 1
        return (item, index)
    
    def is_loop_done(self, step_name: str) -> bool:
        """Check if loop is completed."""
        if step_name not in self.loop_state:
            return True
        return self.loop_state[step_name]["completed"]
    
    def add_loop_result(self, step_name: str, result: Any, failed: bool = False):
        """Add iteration result to loop aggregation (local cache only)."""
        if step_name not in self.loop_state:
            return
        
        self.loop_state[step_name]["results"].append(result)
        if failed:
            self.loop_state[step_name]["failed_count"] += 1
        logger.debug(f"Added iteration result to loop {step_name}: {len(self.loop_state[step_name]['results'])} total")
        
        # Note: Distributed sync to NATS K/V happens in engine.handle_event()
    
    def get_loop_aggregation(self, step_name: str) -> dict[str, Any]:
        """Get aggregated loop results in standard format."""
        if step_name not in self.loop_state:
            return {"results": [], "stats": {"total": 0, "success": 0, "failed": 0}}
        
        loop_state = self.loop_state[step_name]
        total = len(loop_state["results"])
        failed = loop_state["failed_count"]
        success = total - failed
        
        return {
            "results": loop_state["results"],
            "stats": {
                "total": total,
                "success": success,
                "failed": failed
            }
        }
    
    def get_render_context(self, event: Event) -> dict[str, Any]:
        """Get context for Jinja2 rendering.
        
        Loop variables are added to state.variables in _create_command_for_step,
        so they will be available via **self.variables spread below.
        """
        logger.info(f"ENGINE: get_render_context called, catalog_id={self.catalog_id}, execution_id={self.execution_id}")
        
        # Protected system fields that should not be overridden by workload variables
        protected_fields = {"execution_id", "catalog_id", "job"}
        
        context = {
            "event": {
                "name": event.name,
                "payload": event.payload,
                "step": event.step,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            },
            # Note: variables includes loop vars, but we avoid top-level spreading 
            # to prevent state pollution in sub-playbooks
            "workload": self.variables,
            "vars": self.variables,
            **self.step_results,  # Make step results accessible (e.g., {{ process }})
        }
        
        # Add variables to context only if they don't collide with reserved keys
        # This provides a flatter namespace while protecting system fields
        for k, v in self.variables.items():
            if k not in context and k not in protected_fields:
                context[k] = v
        
        # Set protected fields AFTER spreading variables to ensure they are not overridden
        # CRITICAL: Convert IDs to strings to prevent JavaScript precision loss with Snowflake IDs
        context["execution_id"] = str(self.execution_id) if self.execution_id else None
        context["catalog_id"] = str(self.catalog_id) if self.catalog_id else None
        context["job"] = {
            "uuid": str(self.execution_id) if self.execution_id else None,
            "execution_id": str(self.execution_id) if self.execution_id else None,
            "id": str(self.execution_id) if self.execution_id else None
        }
        
        # Add loop metadata context if step has active loop
        if event.step and event.step in self.loop_state:
            loop_state = self.loop_state[event.step]
            context["loop"] = {
                "index": loop_state["index"] - 1 if loop_state["index"] > 0 else 0,  # Current item index
                "first": loop_state["index"] == 1,
                "length": len(loop_state["collection"]),
                "done": loop_state["completed"]
            }
            # Note: Iterator variable itself (e.g., {{ num }}) comes from state.variables
        
        # Add event-specific data
        if "response" in event.payload:
            context["response"] = event.payload["response"]
        elif "result" in event.payload:
            # Fallback: expose result as response for templates that expect {{ response.* }} on step.exit
            context["response"] = event.payload["result"]
        if "error" in event.payload:
            context["error"] = event.payload["error"]
        if "result" in event.payload:
            context["result"] = event.payload["result"]
        
        return context


class PlaybookRepo:
    """Repository for loading playbooks from catalog."""
    
    def __init__(self):
        self._cache: dict[str, Playbook] = {}
    
    async def load_playbook(self, path: str) -> Optional[Playbook]:
        """Load playbook from catalog by path."""
        # Check cache first
        if path in self._cache:
            return self._cache[path]
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT content, layout 
                    FROM noetl.catalog 
                    WHERE path = %s 
                    ORDER BY version DESC 
                    LIMIT 1
                """, (path,))
                row = await cur.fetchone()
            
                if not row:
                    logger.error(f"Playbook not found: {path}")
                    return None
                
                # Parse YAML content
                import yaml
                content_dict = yaml.safe_load(row["content"])
                
                # Validate it's v2
                if content_dict.get("apiVersion") != "noetl.io/v2":
                    logger.error(f"Playbook {path} is not v2 format")
                    return None
                
                # Parse into Pydantic model
                playbook = Playbook(**content_dict)
                self._cache[path] = playbook
                return playbook
    
    async def load_playbook_by_id(self, catalog_id: int) -> Optional[Playbook]:
        """Load playbook from catalog by ID."""
        # Check if we have it in cache
        cache_key = f"id:{catalog_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT content, layout, path
                    FROM noetl.catalog 
                    WHERE catalog_id = %s
                """, (catalog_id,))
                row = await cur.fetchone()
            
                if not row:
                    logger.error(f"Playbook not found: catalog_id={catalog_id}")
                    return None
                
                # Parse YAML content
                import yaml
                content_dict = yaml.safe_load(row["content"])
                
                # Validate it's v2
                if content_dict.get("apiVersion") != "noetl.io/v2":
                    logger.error(f"Playbook catalog_id={catalog_id} is not v2 format")
                    return None
                
                # Parse into Pydantic model
                playbook = Playbook(**content_dict)
                self._cache[cache_key] = playbook
                # Also cache by path for consistency
                if row.get("path"):
                    self._cache[row["path"]] = playbook
                return playbook


class StateStore:
    """Stores and retrieves execution state."""
    
    def __init__(self, playbook_repo: 'PlaybookRepo'):
        self._memory_cache: dict[str, ExecutionState] = {}
        self.playbook_repo = playbook_repo
    
    async def save_state(self, state: ExecutionState):
        """Save execution state."""
        self._memory_cache[state.execution_id] = state
        
        # Persist to workload table
        state_data = {
            "variables": state.variables,
            "step_results": state.step_results,
            "current_step": state.current_step,
            "completed_steps": list(state.completed_steps),
            "failed": state.failed,
            "completed": state.completed,
            "loop_state": state.loop_state,  # Include loop state for iteration result tracking
        }
        
        # Pure event-driven: State is fully reconstructable from events
        # No need to persist to workload table - it's redundant with event log
        # Just keep in memory cache for performance
        logger.debug(f"State cached in memory for execution {state.execution_id}")
    
    async def load_state(self, execution_id: str) -> Optional[ExecutionState]:
        """Load execution state from memory or reconstruct from events."""
        # Check memory first
        if execution_id in self._memory_cache:
            return self._memory_cache[execution_id]
        
        # Reconstruct state from events in database using event sourcing
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Get playbook info and workload from playbook.initialized event
                await cur.execute("""
                    SELECT catalog_id, result
                    FROM noetl.event
                    WHERE execution_id = %s AND event_type = 'playbook.initialized'
                    ORDER BY event_id
                    LIMIT 1
                """, (int(execution_id),))
                
                result = await cur.fetchone()
                if not result:
                    return None

                if isinstance(result, dict):
                    catalog_id = result.get("catalog_id")
                    event_result = result.get("result")
                else:
                    catalog_id = result[0]
                    event_result = result[1]
                if catalog_id is None:
                    return None
                
                # Extract workload from playbook.initialized event result
                # This contains the merged workload (playbook defaults + parent args)
                workload = {}
                if event_result and isinstance(event_result, dict):
                    workload = event_result.get("workload", {})
                    logger.debug(f"Restored workload from playbook.initialized event: {list(workload.keys()) if workload else 'empty'}")
                
                # Load playbook
                playbook = await self.playbook_repo.load_playbook_by_id(catalog_id)
                if not playbook:
                    return None
                
                # Create new state with restored workload
                # Note: We pass workload as the payload param so it merges properly
                # The ExecutionState.__init__ first loads playbook.workload, then merges payload
                # To avoid double-loading playbook defaults, we pass the full workload directly
                # and let the playbook.workload be overwritten
                state = ExecutionState(execution_id, playbook, workload, catalog_id)
                
                # Identify loop steps from playbook for initialization
                loop_steps = set()
                if hasattr(playbook, 'workflow') and playbook.workflow:
                    for step in playbook.workflow:
                        if hasattr(step, 'loop') and step.loop:
                            loop_steps.add(step.step)
                
                # Replay events to rebuild state (event sourcing)
                await cur.execute("""
                    SELECT node_name, event_type, result
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id
                """, (int(execution_id),))
                
                rows = await cur.fetchall()
                
                # Track loop iteration results during event replay
                loop_iteration_results = {}  # {step_name: [result1, result2, ...]}
                
                for row in rows:
                    if isinstance(row, dict):
                        node_name = row.get("node_name")
                        event_type = row.get("event_type")
                        result_data = row.get("result")
                    else:
                        node_name = row[0]
                        event_type = row[1]
                        result_data = row[2]
                    
                    # For loop steps, collect iteration results from step.exit events
                    if event_type == 'step.exit' and result_data and node_name in loop_steps:
                        if node_name not in loop_iteration_results:
                            loop_iteration_results[node_name] = []
                        loop_iteration_results[node_name].append(result_data)
                    
                    # Restore step results from step.exit events (final result only)
                    if event_type == 'step.exit' and result_data:
                        state.mark_step_completed(node_name, result_data)
                
                # Initialize loop_state for loop steps with collected iteration results
                for step_name in loop_steps:
                    # Count iterations by counting step.exit events for this step
                    # This gives us the current loop index when reconstructing state
                    iteration_count = len(loop_iteration_results.get(step_name, []))
                    
                    if step_name not in state.loop_state:
                        state.loop_state[step_name] = {
                            "collection": [],
                            "index": iteration_count,  # Start from number of completed iterations
                            "completed": False,
                            "results": loop_iteration_results.get(step_name, []),
                            "failed_count": 0,
                            "aggregation_finalized": False
                        }
                        logger.info(f"[STATE-LOAD] Initialized loop_state for {step_name}: index={iteration_count} (from {iteration_count} completed iterations)")
                    else:
                        # Restore collected results and update index
                        state.loop_state[step_name]["results"] = loop_iteration_results.get(step_name, [])
                        state.loop_state[step_name]["index"] = iteration_count
                        logger.info(f"[STATE-LOAD] Updated loop_state for {step_name}: index={iteration_count}")
                
                # Cache and return
                self._memory_cache[execution_id] = state
                return state
    
    def get_state(self, execution_id: str) -> Optional[ExecutionState]:
        """Get state from memory cache (sync)."""
        return self._memory_cache.get(execution_id)


class ControlFlowEngine:
    """
    V2 Control Flow Engine.
    
    Processes events and applies case/when/then rules to determine next actions.
    Pure event-driven architecture with no backward compatibility.
    """
    
    def __init__(self, playbook_repo: PlaybookRepo, state_store: StateStore):
        self.playbook_repo = playbook_repo
        self.state_store = state_store
        self.jinja_env = Environment(undefined=StrictUndefined)
    
    def _render_value_recursive(self, value: Any, context: dict[str, Any]) -> Any:
        """Recursively render templates in nested data structures."""
        if isinstance(value, str) and "{{" in value:
            return self._render_template(value, context)
        elif isinstance(value, dict):
            return {k: self._render_value_recursive(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._render_value_recursive(item, context) for item in value]
        else:
            return value
    
    def _render_template(self, template_str: str, context: dict[str, Any]) -> Any:
        """Render Jinja2 template."""
        if not isinstance(template_str, str) or "{{" not in template_str:
            return template_str
            
        try:
            # Check if this is a simple variable reference like {{ varname }} or {{ obj.attr }}
            # If so, evaluate and return the actual object instead of string representation
            import re
            # Improved regex to handle optional spaces and nested attributes
            simple_var_match = re.match(r'^\{\{\s*([\w.]+)\s*\}\}$', template_str.strip())
            if simple_var_match:
                var_path = simple_var_match.group(1)
                # Navigate dot notation: workload.api_url → context['workload']['api_url']
                value = context
                parts = var_path.split('.')
                
                # OPTIMIZATION: Check top-level directly first
                if len(parts) == 1:
                    part = parts[0]
                    if part in context:
                        return context[part]
                
                for part in parts:
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        # Path doesn't resolve, fall back to Jinja rendering
                        break
                else:
                    # Successfully navigated full path
                    return value
            
            # Standard Jinja2 rendering
            template = self.jinja_env.from_string(template_str)
            result = template.render(**context)
            
            # Try to parse as boolean for conditions
            if result.lower() in ("true", "false"):
                return result.lower() == "true"
            
            return result
        except Exception as e:
            logger.error(f"Template rendering error: {e} | Template: {template_str} | Context keys: {list(context.keys())}")
            raise
    
    def _evaluate_condition(self, when_expr: str, context: dict[str, Any]) -> bool:
        """Evaluate when condition."""
        try:
            # Render the condition
            result = self._render_template(when_expr, context)
            
            # Convert to boolean
            if isinstance(result, bool):
                logger.info(f"[COND] Evaluated '{when_expr}' => {result}")
                return result
            if isinstance(result, str):
                is_true = result.lower() in ("true", "1", "yes")
                logger.info(f"[COND] Evaluated '{when_expr}' => '{result}' => {is_true}")
                return is_true
            bool_result = bool(result)
            logger.info(f"[COND] Evaluated '{when_expr}' => {result} (type={type(result)}) => {bool_result}")
            return bool_result
        except Exception as e:
            logger.error(f"Condition evaluation error: {e} | Condition: {when_expr}")
            return False
    
    async def _process_case_rules(
        self,
        state: ExecutionState,
        step_def: Step,
        event: Event
    ) -> list[Command]:
        """Process case rules for a given event and return matching commands."""
        commands = []
        context = state.get_render_context(event)
        
        if step_def.case:
            logger.info(f"[CASE-EVAL] Step {event.step} has {len(step_def.case)} case rules, evaluating for event {event.name}")
            for idx, case_entry in enumerate(step_def.case):
                # Evaluate condition
                logger.info(f"[CASE-EVAL] Evaluating case {idx}: {case_entry.when}")
                if self._evaluate_condition(case_entry.when, context):
                    logger.info(f"[CASE-MATCH] Step {event.step}, event {event.name}: matched case {idx}: {case_entry.when}")
                    
                    # Process then actions
                    new_commands = await self._process_then_actions(
                        case_entry.then,
                        state,
                        event
                    )
                    commands.extend(new_commands)
                    logger.info(f"[CASE-MATCH] Generated {len(new_commands)} commands from case rule")
                    
                    # First match wins - don't evaluate remaining cases
                    break
                else:
                    logger.debug(f"[CASE-EVAL] Case {idx} did not match: {case_entry.when}")
        
        return commands
    
    async def _process_then_actions(
        self, 
        then_block: dict | list,
        state: ExecutionState,
        event: Event
    ) -> list[Command]:
        """Process actions in a then block."""
        commands: list[Command] = []
        
        # Normalize to list
        actions = then_block if isinstance(then_block, list) else [then_block]
        
        context = state.get_render_context(event)
        max_pages_env = os.getenv("NOETL_PAGINATION_MAX_PAGES", "100")
        try:
            max_pages = max(1, int(max_pages_env))
        except ValueError:
            max_pages = 100
        
        for action in actions:
            if not isinstance(action, dict):
                continue

            handled_pagination_retry = False
            
            # Handle different action types
            if "next" in action:
                # Transition to next step(s)
                next_items = action["next"]
                if not isinstance(next_items, list):
                    next_items = [next_items]
                
                for next_item in next_items:
                    if isinstance(next_item, str):
                        # Simple step name
                        target_step = next_item
                        args = {}
                    elif isinstance(next_item, dict):
                        # {step: name, args: {...}}
                        target_step = next_item.get("step")
                        args = next_item.get("args", {})
                        
                        # Render args
                        rendered_args = {}
                        for key, value in args.items():
                            if isinstance(value, str) and "{{" in value:
                                rendered_args[key] = self._render_template(value, context)
                            else:
                                rendered_args[key] = value
                        args = rendered_args
                    else:
                        continue
                    
                    # Auto-inject loop_results when transitioning from loop.done event
                    # The loop step acts as an aggregator, and its result should be passed as loop_results
                    if event.name == "loop.done" and event.step in state.step_results:
                        loop_result = state.step_results[event.step]
                        if "loop_results" not in args:
                            args["loop_results"] = loop_result
                            logger.info(f"Auto-injected loop_results for {target_step} from loop step {event.step}")
                    
                    # Get target step definition
                    step_def = state.get_step(target_step)
                    if not step_def:
                        logger.error(f"Target step not found: {target_step}")
                        continue
                    
                    # Create command for target step
                    command = await self._create_command_for_step(
                        state, step_def, args
                    )
                    if command:
                        commands.append(command)
            
            elif "set" in action:
                # Set variables
                set_data = action["set"]
                for key, value in set_data.items():
                    if isinstance(value, str) and "{{" in value:
                        state.variables[key] = self._render_template(value, context)
                    else:
                        state.variables[key] = value
            
            elif "result" in action:
                # Set step result
                result_spec = action["result"]
                if isinstance(result_spec, dict) and "from" in result_spec:
                    from_key = result_spec["from"]
                    if from_key in state.variables:
                        state.mark_step_completed(event.step, state.variables[from_key])
                else:
                    state.mark_step_completed(event.step, result_spec)
            
            elif "fail" in action:
                # Mark execution as failed
                state.failed = True
                logger.info(f"Execution {state.execution_id} marked as failed")
            
            if "collect" in action:
                # Collect data for pagination accumulation
                collect_spec = action["collect"]
                strategy = collect_spec.get("strategy", "append")  # append, extend, replace
                path = collect_spec.get("path")  # Path to extract from response
                into_var = collect_spec.get("into", "_collected_pages")  # Target variable name (reserved for future vars usage)

                # Initialize pagination state for this step if needed
                step_name = event.step
                if step_name not in state.pagination_state:
                    state.pagination_state[step_name] = {
                        "collected_data": [],
                        "iteration_count": 0,
                        "pending_retry": False
                    }

                # Extract data from response using path
                result_data = event.payload.get("response")
                if result_data is None and "result" in event.payload:
                    result_data = event.payload["result"]

                if result_data is None:
                    logger.warning(f"[COLLECT] No response or result payload to collect for step {step_name}")
                else:
                    data_to_collect = result_data
                    if path and isinstance(result_data, dict):
                        for part in path.split("."):
                            if isinstance(data_to_collect, dict) and part in data_to_collect:
                                data_to_collect = data_to_collect[part]
                            else:
                                logger.warning(f"Path {path} not found in result for collect")
                                data_to_collect = None
                                break

                    if data_to_collect is not None:
                        # Collect data based on strategy
                        collected = state.pagination_state[step_name]["collected_data"]
                        if strategy == "append":
                            collected.append(data_to_collect)
                        elif strategy == "extend" and isinstance(data_to_collect, list):
                            collected.extend(data_to_collect)
                        elif strategy == "replace":
                            state.pagination_state[step_name]["collected_data"] = [data_to_collect]

                        state.pagination_state[step_name]["iteration_count"] += 1
                        # If this collect matched a terminal page (no retry), clear pending flag
                        state.pagination_state[step_name]["pending_retry"] = False
                        logger.info(
                            f"[COLLECT] Accumulated {len(collected)} items for step {step_name} "
                            f"(iteration {state.pagination_state[step_name]['iteration_count']})"
                        )
                        if state.pagination_state[step_name]["iteration_count"] >= max_pages:
                            state.pagination_state[step_name]["pending_retry"] = False
                            logger.warning(
                                f"[PAGINATION] Reached max_pages={max_pages} for step {step_name}; stopping pagination retries"
                            )

            # Pagination retry (params/url/etc) can coexist with collect
            pagination_retry_spec = action.get("retry") if isinstance(action, dict) else None
            if pagination_retry_spec and isinstance(pagination_retry_spec, dict) and any(
                key in pagination_retry_spec for key in ["params", "url", "method", "headers", "body", "data"]
            ):
                retry_spec = pagination_retry_spec
                handled_pagination_retry = True

                # Hard cap pagination retries to avoid infinite loops
                iteration_count = state.pagination_state.get(event.step, {}).get("iteration_count", 0)
                if iteration_count >= max_pages:
                    state.pagination_state.setdefault(event.step, {}).setdefault("pending_retry", False)
                    state.pagination_state[event.step]["pending_retry"] = False
                    logger.warning(
                        f"[PAGINATION] Skip retry for {event.step}: iteration_count={iteration_count} reached max_pages={max_pages}"
                    )
                    continue

                # Get current step definition
                step_def = state.get_step(event.step)
                if not step_def:
                    logger.error(f"Cannot retry: step {event.step} not found")
                    continue

                # Extract updated parameters from retry spec
                updated_args = {}

                # Process params field (most common for HTTP pagination)
                if "params" in retry_spec:
                    params = retry_spec["params"]
                    rendered_params = {}
                    for key, value in params.items():
                        if isinstance(value, str) and "{{" in value:
                            rendered_params[key] = self._render_template(value, context)
                        else:
                            rendered_params[key] = value

                    # HTTP tool expects runtime pagination overrides under args['params']
                    updated_args["params"] = rendered_params

                # Process other updatable fields
                for field in ["url", "method", "headers", "body", "data"]:
                    if field in retry_spec:
                        value = retry_spec[field]
                        if isinstance(value, str) and "{{" in value:
                            updated_args[field] = self._render_template(value, context)
                        else:
                            updated_args[field] = value

                # For looped steps, keep the same item by rewinding the index before command creation
                loop_state = state.loop_state.get(event.step)
                rewind_applied = False
                if loop_state and loop_state["index"] > 0:
                    loop_state["index"] -= 1
                    rewind_applied = True
                    logger.info(
                        f"[RETRY] Rewound loop index for step {event.step} to reuse current item "
                        f"(index now {loop_state['index']})"
                    )

                # Create retry command with updated args (same step)
                command = await self._create_command_for_step(state, step_def, updated_args)

                # If creation failed, restore index
                if not command and rewind_applied and loop_state:
                    loop_state["index"] += 1
                if command:
                    state.pagination_state.setdefault(event.step, {}).setdefault("pending_retry", False)
                    state.pagination_state[event.step]["pending_retry"] = True
                    commands.append(command)
                    logger.info(
                        f"[RETRY] Created pagination retry command for {event.step} with updated params: {list(updated_args.keys())}"
                    )

            if "call" in action:
                # Call/invoke a step with new arguments
                call_spec = action["call"]
                target_step = call_spec.get("step")
                args = call_spec.get("args", {})
                
                if not target_step:
                    logger.warning("Call action missing 'step' attribute")
                    continue
                
                # Render args
                rendered_args = {}
                for key, value in args.items():
                    if isinstance(value, str) and "{{" in value:
                        rendered_args[key] = self._render_template(value, context)
                    else:
                        rendered_args[key] = value
                
                # Get target step definition
                step_def = state.get_step(target_step)
                if not step_def:
                    logger.error(f"Call target step not found: {target_step}")
                    continue
                
                # Create command for target step
                command = await self._create_command_for_step(state, step_def, rendered_args)
                if command:
                    commands.append(command)
                    logger.info(f"Call action: invoking step {target_step}")
            
            if "retry" in action and not handled_pagination_retry:
                # Retry current step with optional backoff
                retry_spec = action["retry"]
                delay = retry_spec.get("delay", 0)
                max_attempts = retry_spec.get("max_attempts", 3)
                backoff = retry_spec.get("backoff", "linear")  # linear, exponential
                
                # Get current attempt from event.attempt (Event model field)
                current_attempt = event.attempt if event.attempt else 1
                
                # Check if max attempts exceeded
                if current_attempt >= max_attempts:
                    logger.warning(
                        f"[RETRY-EXHAUSTED] Step {event.step} has reached max retry attempts "
                        f"({current_attempt}/{max_attempts}). Skipping retry action."
                    )
                    continue
                
                # Get current step
                step_def = state.get_step(event.step)
                if not step_def:
                    logger.error(f"Retry: current step not found: {event.step}")
                    continue
                
                # Create retry command with incremented attempt counter
                command = await self._create_command_for_step(state, step_def, {})
                if command:
                    # Increment attempt counter
                    command.attempt = current_attempt + 1
                    command.max_attempts = max_attempts
                    command.retry_delay = delay
                    command.retry_backoff = backoff
                    commands.append(command)
                    logger.info(
                        f"[RETRY-ACTION] Re-attempting step {event.step} "
                        f"(attempt {command.attempt}/{max_attempts})"
                    )

            # Sink action can co-exist with next/retry, so handle separately
            if "sink" in action:
                # WORKER-SIDE EXECUTION: Sinks are now executed immediately by the worker
                # after tool execution via _execute_case_sinks() method.
                # The case blocks are passed to the worker in the command context.
                # No need to create separate sink commands here - the worker handles it inline.
                logger.info(f"[CASE-SINK] Sink action detected in case block - will be executed by worker immediately")
                # Skip sink command creation - worker handles this
                pass
        
        return commands
    
    async def _create_command_for_step(
        self,
        state: ExecutionState,
        step: Step,
        args: dict[str, Any]
    ) -> Optional[Command]:
        """Create a command to execute a step."""
        # Check if step has loop configuration
        if step.loop:
            logger.debug(f"[CREATE-CMD] Step {step.step} has loop: in={step.loop.in_}, iterator={step.loop.iterator}, mode={step.loop.mode}")
            # Get collection to iterate
            context = state.get_render_context(Event(
                execution_id=state.execution_id,
                step=step.step,
                name="loop_init",
                payload={}
            ))
            
            # Render collection expression
            collection_expr = step.loop.in_
            collection = self._render_template(collection_expr, context)
            
            if not isinstance(collection, list):
                logger.warning(f"Loop collection is not a list: {type(collection)}, converting")
                collection = list(collection) if hasattr(collection, '__iter__') else [collection]
            
            # Get completed count from NATS K/V (authoritative) or local fallback
            # Use last event_id for this step as the loop instance identifier
            # If no event_id yet (first time), use execution_id as fallback
            loop_event_id = state.step_event_ids.get(step.step)
            if loop_event_id is None:
                # For new loops, use execution_id as identifier until first event is created
                loop_event_id = f"exec_{state.execution_id}"
                logger.debug(f"[LOOP-INIT] No event_id yet for {step.step}, using execution fallback: {loop_event_id}")
            
            nats_cache = await get_nats_cache()
            nats_loop_state = await nats_cache.get_loop_state(
                str(state.execution_id),
                step.step,
                event_id=str(loop_event_id)
            )
            
            # Use NATS count if available (authoritative for distributed execution)
            if nats_loop_state:
                completed_count = len(nats_loop_state.get("results", []))
                logger.debug(f"[LOOP-NATS] Got completed count from NATS K/V: {completed_count}")
            else:
                # Initialize loop state if not present (first iteration)
                if step.step not in state.loop_state:
                    state.init_loop(step.step, collection, step.loop.iterator, step.loop.mode, event_id=loop_event_id)
                    logger.info(f"Initialized loop for {step.step} with {len(collection)} items, event_id={loop_event_id}")
                    
                    # Store initial state in NATS K/V with event_id for instance uniqueness
                    await nats_cache.set_loop_state(
                        str(state.execution_id),
                        step.step,
                        {
                            "collection_size": len(collection),
                            "results": [],
                            "iterator": step.loop.iterator,
                            "mode": step.loop.mode,
                            "event_id": loop_event_id
                        },
                        event_id=str(loop_event_id)
                    )
                
                loop_state = state.loop_state[step.step]
                completed_count = len(loop_state.get("results", []))
                logger.debug(f"[LOOP-LOCAL] Got completed count from local cache: {completed_count}")
            
            logger.info(f"[LOOP] Step {step.step}: {completed_count}/{len(collection)} iterations completed")
            
            # Check if we have more items to process
            if completed_count >= len(collection):
                # Loop completed
                logger.info(f"[LOOP] Loop completed for {step.step}: {completed_count}/{len(collection)} iterations")
                return None  # No command, will generate loop.done event
            
            # Get next item by index (stateless - just use completed_count as index)
            item = collection[completed_count]
            logger.info(f"[LOOP] Creating command for loop iteration {completed_count} of step {step.step}, item={item}")
            
            # Add loop variables to state for Jinja2 template rendering
            state.variables[step.loop.iterator] = item
            state.variables["loop_index"] = completed_count
            logger.info(f"[LOOP] Added to state.variables: {step.loop.iterator}={item}, loop_index={completed_count}")
        
        # Build tool config - extract all fields from ToolSpec
        tool_dict = step.tool.model_dump()
        tool_config = {k: v for k, v in tool_dict.items() if k != "kind"}
        
        # Build args separately - for step inputs
        step_args = {}
        if step.args:
            step_args.update(step.args)
        
        # Merge transition args
        step_args.update(args)
        
        # Get render context for Jinja2 templates
        context = state.get_render_context(Event(
            execution_id=state.execution_id,
            step=step.step,
            name="command_creation",
            payload={}
        ))
        
        # Debug: Log state for verify_result step
        if step.step == "verify_result":
            gcs_result = state.step_results.get('run_python_from_gcs', 'NOT_FOUND')
            logger.error(f"DEBUG verify_result: step_results={list(state.step_results.keys())} | variables={list(state.variables.keys())} | step_args={step_args} | run_python_from_gcs={gcs_result}")
        
        # Debug: Log loop variables in context
        if step.loop:
            logger.warning(f"[LOOP-DEBUG] Step {step.step}: context_keys={list(context.keys())} | iterator='{step.loop.iterator}'={context.get(step.loop.iterator, 'NOT_FOUND')} | loop_index={context.get('loop_index', 'NOT_FOUND')} | state.variables={state.variables}")
        
        # Render Jinja2 templates in tool config
        # CRITICAL: Use recursive render_template to handle nested dicts/lists like params: {latitude: "{{ city.lat }}"}
        from noetl.core.dsl.render import render_template as recursive_render
        
        # Use existing engine environment to benefit from cached filters and settings
        rendered_tool_config = recursive_render(self.jinja_env, tool_config, context)
        
        # Render Jinja2 templates in args (also use recursive rendering for nested structures)
        rendered_args = recursive_render(self.jinja_env, step_args, context)
        
        # Extract case blocks from step definition (if present) for worker-side execution
        case_blocks = None
        if step.case:
            # Convert Pydantic models to dicts for serialization
            case_blocks = [case_entry.model_dump() for case_entry in step.case]
            logger.info(f"[CASE] Including {len(case_blocks)} case blocks in command for step '{step.step}'")
        
        command = Command(
            execution_id=state.execution_id,
            step=step.step,
            tool=ToolCall(
                kind=step.tool.kind,
                config=rendered_tool_config  # Tool-specific config (code, url, query, etc.)
            ),
            args=rendered_args,  # Rendered step input arguments
            render_context=context,  # Pass full context for plugin template rendering
            case=case_blocks,  # Pass case blocks to worker for immediate execution
            attempt=1,
            priority=0
        )
        
        return command
    
    async def _process_vars_block(self, event: Event, state: ExecutionState, step_def: Step) -> None:
        """
        Process vars block from step definition after step completion.
        
        Extracts variables using templates like {{ result.field }} and stores them
        in the transient table for access via {{ vars.var_name }} in subsequent steps.
        
        Args:
            event: The step.exit event
            state: Current execution state
            step_def: Step definition containing optional vars block
        """
        vars_block = step_def.vars
        if not vars_block or not isinstance(vars_block, dict):
            logger.debug(f"[VARS] No vars block for step '{event.step}'")
            return
        
        logger.info(f"[VARS] Processing vars block for step '{event.step}': {list(vars_block.keys())}")
        
        try:
            # Import TransientVars for storage
            from noetl.worker.transient import TransientVars

            # Build context for template rendering
            # The 'result' key points to the step's output for current step vars extraction
            eval_ctx = state.get_render_context(event)

            rendered_vars = {}

            for var_name, var_template in vars_block.items():
                try:
                    if isinstance(var_template, str):
                        rendered_value = self._render_template(var_template, eval_ctx)

                        # Try to parse as JSON if it looks like JSON
                        if isinstance(rendered_value, str) and rendered_value.strip().startswith(("{", "[")):
                            try:
                                import json
                                rendered_value = json.loads(rendered_value)
                            except Exception:
                                pass  # Keep string if not valid JSON
                    else:
                        # Non-string values pass through
                        rendered_value = var_template

                    rendered_vars[var_name] = rendered_value
                    logger.info(f"[VARS] Rendered '{var_name}' = {rendered_value}")
                except Exception as e:
                    logger.warning(f"[VARS] Failed to render '{var_name}': {e}")
                    continue

            if not rendered_vars:
                logger.debug(f"[VARS] No vars successfully rendered for step '{event.step}'")
                return

            # Store variables in transient table
            count = await TransientVars.set_multiple(
                variables=rendered_vars,
                execution_id=event.execution_id,
                var_type="step_result",
                source_step=event.step
            )

            # Also add to state.variables for immediate template access
            state.variables.update(rendered_vars)

            logger.info(f"[VARS] Stored {count} variables from step '{event.step}'")

        except Exception as e:
            logger.exception(f"[VARS] Error processing vars block for step '{event.step}': {e}")
    
    async def handle_event(self, event: Event, already_persisted: bool = False) -> list[Command]:
        """
        Handle an event and return commands to enqueue.
        
        This is the core engine method called by the API.
        
        Args:
            event: The event to process
            already_persisted: If True, skip persisting the event (it was already persisted by caller)
        """
        logger.info(f"[ENGINE] handle_event called: event.name={event.name}, step={event.step}, execution={event.execution_id}, already_persisted={already_persisted}")
        commands: list[Command] = []
        
        # Load execution state (from memory cache or reconstruct from events)
        state = await self.state_store.load_state(event.execution_id)
        if not state:
            logger.error(f"Execution state not found: {event.execution_id}")
            return commands
        
        # Get current step
        if not event.step:
            logger.error("Event missing step name")
            return commands
        
        # Handle synthetic steps (like sink commands)
        # These are created dynamically and don't exist in the workflow
        # They execute and emit events, but don't need orchestration
        if event.step.endswith('_sink'):
            logger.debug(f"Synthetic sink step: {event.step} - persisting event without orchestration")
            # Persist the event but don't generate commands (no orchestration needed)
            # Skip if already persisted by API caller
            if not already_persisted:
                await self._persist_event(event, state)
            return commands
        
        step_def = state.get_step(event.step)
        if not step_def:
            logger.error(f"Step not found: {event.step}")
            return commands
        
        # Update current step
        state.set_current_step(event.step)
        
        # Store step result if this is a step.exit event
        logger.info(f"[LOOP_DEBUG] Checking step.exit: name={event.name}, has_result={'result' in event.payload}, payload_keys={list(event.payload.keys())}")
        if event.name == "step.exit" and "result" in event.payload:
            logger.info(f"[LOOP_DEBUG] step.exit with result for {event.step}, step_def.loop={step_def.loop}, in_loop_state={event.step in state.loop_state}")
            # Skip aggregation if a pagination retry is pending (same loop item will repeat)
            pending_retry = state.pagination_state.get(event.step, {}).get("pending_retry", False)
            if pending_retry:
                logger.info(f"[LOOP_DEBUG] Pending pagination retry for {event.step}; skipping result aggregation and loop advance")
            # If pagination collected data for this step, merge it into the current result before aggregation
            # and reset pagination state for the next iteration/run when no retry is pending.
            pagination_state = state.pagination_state.get(event.step)
            if pagination_state and not pending_retry:
                collected_data = pagination_state.get("collected_data", [])
                if collected_data:
                    current_result = event.payload.get("result", {})

                    pagination_summary = {
                        "pages_collected": pagination_state.get("iteration_count", 0),
                        "all_items": collected_data,
                    }

                    flattened_items: list[Any] = []
                    for item in collected_data:
                        if isinstance(item, list):
                            flattened_items.extend(item)
                        else:
                            flattened_items.append(item)

                    if isinstance(current_result, dict):
                        current_result["_pagination"] = pagination_summary
                        current_result["_all_collected_items"] = flattened_items
                    else:
                        current_result = {
                            "original_result": current_result,
                            "_pagination": pagination_summary,
                            "_all_collected_items": flattened_items,
                        }

                    event.payload["result"] = current_result
                    logger.info(
                        f"[PAGINATION] Merged collected pagination data into result for {event.step}: "
                        f"{len(flattened_items)} total items over {pagination_state.get('iteration_count', 0)} pages"
                    )

                # Reset pagination state for next iteration/run to avoid bleed-over
                state.pagination_state[event.step] = {
                    "collected_data": [],
                    "iteration_count": 0,
                    "pending_retry": False,
                }
            # If in a loop, add iteration result to aggregation (for ALL iterations)
            if step_def.loop and event.step in state.loop_state and not pending_retry:
                # Check if loop aggregation already finalized (loop_done happened)
                loop_state = state.loop_state[event.step]
                logger.info(f"[LOOP_DEBUG] Loop state: completed={loop_state.get('completed')}, finalized={loop_state.get('aggregation_finalized')}, results_count={len(loop_state.get('results', []))}")
                if not loop_state.get("aggregation_finalized", False):
                    failed = event.payload.get("status", "").upper() == "FAILED"
                    state.add_loop_result(event.step, event.payload["result"], failed=failed)
                    logger.info(f"Added iteration result to loop aggregation for step {event.step}")
                    
                    # Sync to distributed NATS K/V cache for multi-server deployments
                    try:
                        nats_cache = await get_nats_cache()
                        # Get event_id from loop state to identify this loop instance
                        loop_event_id = loop_state.get("event_id")
                        success = await nats_cache.append_loop_result(
                            str(state.execution_id),
                            event.step,
                            event.payload["result"],
                            event_id=str(loop_event_id) if loop_event_id else None
                        )
                        if success:
                            logger.debug(f"[LOOP-NATS] Synced iteration result to NATS K/V for {event.step}, event_id={loop_event_id}")
                        else:
                            logger.error(f"[LOOP-NATS] Failed to sync loop result to NATS K/V for {event.step}, event_id={loop_event_id}")
                    except Exception as e:
                        logger.error(f"[LOOP-NATS] Error syncing to NATS K/V: {e}", exc_info=True)
                else:
                    logger.info(f"Loop aggregation already finalized for {event.step}, skipping result storage")
            elif not pending_retry:
                # Not in loop or loop done - store as normal step result
                state.mark_step_completed(event.step, event.payload["result"])
                logger.debug(f"Stored result for step {event.step} in state")
        
        # CRITICAL: For call.done events, temporarily add response to state
        # This allows subsequent steps to access the result before step.exit
        if event.name == "call.done" and "response" in event.payload:
            state.mark_step_completed(event.step, event.payload["response"])
            logger.debug(f"Temporarily stored call.done response for step {event.step} in state")
        
        # Get render context (needed for case evaluation and other logic)
        context = state.get_render_context(event)
        
        # CRITICAL: Process case rules FIRST for ALL events (not just step.exit)
        # This allows steps to react to call.done, call.error, and other mid-step events
        case_commands = await self._process_case_rules(state, step_def, event)
        commands.extend(case_commands)
        
        # Handle loop.item events - continue loop iteration
        # Only process if case didn't generate commands
        if not commands and event.name == "loop.item" and step_def.loop:
            logger.debug(f"Processing loop.item event for {event.step}")
            command = await self._create_command_for_step(state, step_def, {})
            if command:
                commands.append(command)
                logger.debug(f"Created command for next loop iteration")
            else:
                # Loop completed, would emit loop.done below
                logger.debug(f"Loop iteration complete, will check for loop.done")
        
        # Check if step has completed loop - emit loop.done event
        # Check on step.exit regardless of whether case generated commands
        # (case may have matched call.done and generated sink/next commands)
        logger.info(f"[LOOP-DEBUG] Checking step.exit: step={event.step}, event.name={event.name}, has_loop={step_def.loop is not None}")
        if step_def.loop and event.name == "step.exit":
            logger.info(f"[LOOP-DEBUG] Entering loop completion check for {event.step}")
            pagination_retry_pending = state.pagination_state.get(event.step, {}).get("pending_retry", False)
            if pagination_retry_pending:
                logger.info(f"[LOOP_DEBUG] Pagination retry pending for {event.step}; skipping loop completion/next iteration")
            else:
                # Get loop state from NATS K/V (distributed cache) or local fallback
                nats_cache = await get_nats_cache()
                loop_state = state.loop_state.get(event.step)
                loop_event_id = loop_state.get("event_id") if loop_state else None
                nats_loop_state = await nats_cache.get_loop_state(
                    str(state.execution_id),
                    event.step,
                    event_id=str(loop_event_id) if loop_event_id else None
                )
                
                if not loop_state and not nats_loop_state:
                    logger.warning(f"No loop state for step {event.step}")
                else:
                    # Use NATS count if available (authoritative), otherwise local cache
                    if nats_loop_state:
                        completed_count = len(nats_loop_state.get("results", []))
                        logger.debug(f"[LOOP-NATS] Got count from NATS K/V: {completed_count}")
                    elif loop_state:
                        completed_count = len(loop_state.get("results", []))
                        logger.debug(f"[LOOP-LOCAL] Got count from local cache: {completed_count}")
                    else:
                        completed_count = 0
                    
                    # Only render collection if not already cached (expensive operation)
                    if loop_state and not loop_state.get("collection"):
                        context = state.get_render_context(event)
                        collection = self._render_template(step_def.loop.in_, context)
                        if not isinstance(collection, list):
                            collection = list(collection) if hasattr(collection, '__iter__') else [collection]
                        loop_state["collection"] = collection
                        logger.info(f"[LOOP-SETUP] Rendered collection for {event.step}: {len(collection)} items")
                        
                        # Store initial loop state in NATS K/V with event_id
                        loop_event_id = loop_state.get("event_id")
                        await nats_cache.set_loop_state(
                            str(state.execution_id),
                            event.step,
                            {
                                "collection_size": len(collection),
                                "results": [],
                                "iterator": loop_state.get("iterator"),
                                "mode": loop_state.get("mode"),
                                "event_id": loop_event_id
                            },
                            event_id=str(loop_event_id) if loop_event_id else None
                        )
                    
                    collection_size = len(loop_state["collection"]) if loop_state else (nats_loop_state.get("collection_size", 0) if nats_loop_state else 0)
                    logger.info(f"[LOOP-CHECK] Step {event.step}: {completed_count}/{collection_size} iterations completed")
                    
                    if completed_count < collection_size:
                        # More items to process - create next iteration command if not already created
                        if not any(cmd.step == event.step for cmd in commands):
                            logger.info(f"[LOOP] Creating next iteration command for {event.step}")
                            command = await self._create_command_for_step(state, step_def, {})
                            if command:
                                commands.append(command)
                            else:
                                logger.error(f"[LOOP] Failed to create command for next iteration of {event.step}")
                    else:
                        # Loop done - create aggregated result and store as step result
                        logger.info(f"[LOOP] Loop completed for step {event.step}, creating aggregated result")
                        
                        # Mark loop as completed in local state
                        if loop_state:
                            loop_state["completed"] = True
                            loop_state["aggregation_finalized"] = True
                            # CRITICAL: Re-initialize results from authoritative source (NATS K/V) 
                            # if we are about to create aggregated result, to ensure no duplicates 
                            # or stale data from memory cache.
                            if nats_loop_state:
                                loop_state["results"] = nats_loop_state.get("results", [])
                                logger.info(f"[LOOP-SYNC] Re-initialized local results from NATS K/V: {len(loop_state['results'])} items")
                        
                        # Get aggregated loop results
                        loop_aggregation = state.get_loop_aggregation(event.step)
                        
                        # Check if step has pagination data to merge
                        if event.step in state.pagination_state:
                            pagination_data = state.pagination_state[event.step]
                            if pagination_data["collected_data"]:
                                # Merge pagination data into aggregated result
                                loop_aggregation["pagination"] = {
                                    "collected_items": pagination_data["collected_data"],
                                    "iteration_count": pagination_data["iteration_count"]
                                }
                                logger.info(f"Merged pagination data into loop result: {pagination_data['iteration_count']} iterations")
                        
                        # Store aggregated result as the step result
                        # This makes it available to next steps via {{ loop_step_name }}
                        state.mark_step_completed(event.step, loop_aggregation)
                        logger.info(f"Stored aggregated loop result for {event.step}: {loop_aggregation['stats']}")
                        
                        # Process loop.done event through case matching
                        loop_done_event = Event(
                            execution_id=event.execution_id,
                            step=event.step,
                            name="loop.done",
                            payload={
                                "status": "completed",
                                "iterations": state.loop_state[event.step]["index"],
                                "result": loop_aggregation  # Include aggregated result in payload
                            }
                        )
                        loop_done_commands = await self._process_case_rules(state, step_def, loop_done_event)
                        commands.extend(loop_done_commands)
        
        # Process vars block if present (extract variables from step result after completion)
        if event.name == "step.exit" and step_def:
            logger.info(f"[VARS_DEBUG] step.exit event for step '{event.step}', step_def.vars={getattr(step_def, 'vars', None)}")
            await self._process_vars_block(event, state, step_def)
        
        # If step.exit event and no case/loop matched, use structural next as fallback
        if event.name == "step.exit" and step_def.next and not commands:
            # Check if step failed - don't process next if it did
            step_status = event.payload.get("status", "").upper()
            if step_status == "FAILED":
                logger.info(f"[STRUCTURAL-NEXT] Step {event.step} failed, skipping structural next")
            # Only proceed to next if loop is done (or no loop) and step didn't fail
            elif not step_def.loop or state.is_loop_done(event.step):
                logger.info(f"[STRUCTURAL-NEXT] No case matched for step.exit, using structural next: {step_def.next}")
                # Handle structural next
                next_items = step_def.next
                if isinstance(next_items, str):
                    next_items = [next_items]
                
                for next_item in next_items:
                    if isinstance(next_item, str):
                        target_step = next_item
                    elif isinstance(next_item, dict):
                        target_step = next_item.get("step")
                    else:
                        continue
                    
                    next_step_def = state.get_step(target_step)
                    if next_step_def:
                        command = await self._create_command_for_step(state, next_step_def, {})
                        if command:
                            commands.append(command)
                            logger.info(f"[STRUCTURAL-NEXT] Created command for step {target_step}")

        # Finalize pagination data if step.exit and no retry commands were generated
        if event.name == "step.exit" and event.step in state.pagination_state and not (step_def and step_def.loop):
            # Check if any commands were created for this step (retry)
            has_retry = any(cmd.step == event.step for cmd in commands)
            
            if not has_retry:
                # No retry, so pagination is complete - merge collected data into step result
                pagination_data = state.pagination_state[event.step]
                if pagination_data["collected_data"]:
                    current_result = event.payload.get("result", {})
                    
                    # Create pagination summary
                    pagination_summary = {
                        "pages_collected": pagination_data["iteration_count"],
                        "all_items": pagination_data["collected_data"]
                    }
                    
                    # Flatten if data is nested lists
                    flattened_items = []
                    for item in pagination_data["collected_data"]:
                        if isinstance(item, list):
                            flattened_items.extend(item)
                        else:
                            flattened_items.append(item)
                    
                    # Add to result
                    if isinstance(current_result, dict):
                        current_result["_pagination"] = pagination_summary
                        current_result["_all_collected_items"] = flattened_items
                    else:
                        current_result = {
                            "original_result": current_result,
                            "_pagination": pagination_summary,
                            "_all_collected_items": flattened_items
                        }
                    
                    # Update the step result with pagination data
                    state.mark_step_completed(event.step, current_result)
                    logger.info(f"[PAGINATION] Finalized pagination for {event.step}: {len(flattened_items)} total items collected over {pagination_data['iteration_count']} pages")
        
        # Check for completion (only emit once) - prepare completion events but persist after current event
        # Completion triggers when step.exit occurs with no commands generated AND step has no routing
        # This handles explicit terminal steps (no next/case blocks) only
        # OR when a step fails with no error handler (no commands generated despite having routing)
        completion_events = []
        logger.info(f"COMPLETION CHECK: event={event.name}, step={event.step}, commands={len(commands)}, completed={state.completed}, has_next={bool(step_def.next if step_def else False)}, has_case={bool(step_def.case if step_def else False)}, has_error={bool(event.payload.get('error'))}")
        
        # Check if step failed
        has_error = event.payload.get("error") is not None
        
        # Only trigger completion if:
        # 1. step.exit event
        # 2. No commands generated
        # 3. EITHER: Step has NO next or case blocks (true terminal step)
        #    OR: Step failed with no error handling (has error but no commands)
        # 4. Not already completed
        is_terminal_step = step_def and not step_def.next and not step_def.case
        is_failed_with_no_handler = has_error and not commands
        
        if event.name == "step.exit" and not commands and (is_terminal_step or is_failed_with_no_handler) and not state.completed:
            # No more commands to execute - workflow and playbook are complete (or failed)
            state.completed = True
            # Check if step failed by looking at error in payload
            from noetl.core.dsl.v2.models import LifecycleEventPayload
            completion_status = "failed" if has_error else "completed"
            
            # Persist current event FIRST to get its event_id for parent_event_id
            # Skip if already persisted by API caller
            if not already_persisted:
                await self._persist_event(event, state)
            
            # Now create completion events with current event as parent
            # This ensures proper ordering: step.exit -> workflow_completion -> playbook_completion
            current_event_id = state.last_event_id
            
            # First, prepare workflow completion event
            workflow_completion_event = Event(
                execution_id=event.execution_id,
                step="workflow",
                name=f"workflow.{completion_status}",
                payload=LifecycleEventPayload(
                    status=completion_status,
                    final_step=event.step,
                    result=event.payload.get("result"),
                    error=event.payload.get("error")
                ).model_dump(),
                timestamp=datetime.now(timezone.utc),
                parent_event_id=current_event_id
            )
            completion_events.append(workflow_completion_event)
            logger.info(f"Workflow {completion_status}: execution_id={event.execution_id}, final_step={event.step}, parent_event_id={current_event_id}")
            
            # Then, prepare playbook completion event as final lifecycle event (parent is workflow_completion)
            # We'll set parent after persisting workflow_completion
            playbook_completion_event = Event(
                execution_id=event.execution_id,
                step=state.playbook.metadata.get("path", "playbook"),
                name=f"playbook.{completion_status}",
                payload=LifecycleEventPayload(
                    status=completion_status,
                    final_step=event.step,
                    result=event.payload.get("result"),
                    error=event.payload.get("error")
                ).model_dump(),
                timestamp=datetime.now(timezone.utc),
                parent_event_id=None  # Will be set after workflow_completion is persisted
            )
            completion_events.append(playbook_completion_event)
            logger.info(f"Playbook {completion_status}: execution_id={event.execution_id}, final_step={event.step}")
        
        # Save state
        await self.state_store.save_state(state)
        
        # Persist current event to database (if not already done for completion case)
        # Skip if event was already persisted by API caller
        if not completion_events and not already_persisted:
            await self._persist_event(event, state)
        
        # Persist completion events in order with proper parent_event_id chain
        for i, completion_event in enumerate(completion_events):
            if i > 0:
                # Set parent to previous completion event
                completion_event.parent_event_id = state.last_event_id
            await self._persist_event(completion_event, state)
        
        # CRITICAL: Stop generating commands if this is a failure event
        # Check AFTER persisting and completion events so they're all stored
        # Only check if we haven't already generated completion events (avoid duplicate stopping logic)
        if not completion_events:
            if event.name == "command.failed":
                logger.error(f"[FAILURE] Received command.failed event for step {event.step}, stopping execution")
                return []  # Return empty commands list to stop workflow
            
            if event.name == "step.exit":
                step_status = event.payload.get("status", "").upper()
                if step_status == "FAILED":
                    logger.error(f"[FAILURE] Step {event.step} failed, stopping execution")
                    return []  # Return empty commands list to stop workflow
        
        return commands
    
    async def _persist_event(self, event: Event, state: ExecutionState):
        """Persist event to database."""
        # Use catalog_id from state, or lookup from existing events
        catalog_id = state.catalog_id
        
        if not catalog_id:
            # Fallback: lookup from existing events
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT catalog_id FROM noetl.event 
                        WHERE execution_id = %s 
                        LIMIT 1
                    """, (int(event.execution_id),))
                    result = await cur.fetchone()
                    catalog_id = result['catalog_id'] if result else None
        
        if not catalog_id:
            logger.error(f"Cannot persist event - no catalog_id for execution {event.execution_id}")
            return
        
        # Determine parent_event_id
        # Use event.parent_event_id if explicitly set (for completion events)
        # Otherwise, use default logic based on step or last event
        parent_event_id = event.parent_event_id
        if parent_event_id is None:
            if event.step:
                # For step events, parent is the last event in this step
                parent_event_id = state.step_event_ids.get(event.step)
            if not parent_event_id:
                # Otherwise, parent is the last event overall
                parent_event_id = state.last_event_id
        
        # Calculate duration for completion events
        # Set to 0 for other events to avoid NULL/undefined in UI
        duration_ms = 0
        event_timestamp = event.timestamp or datetime.now(timezone.utc)
        
        if event.name == "step.exit" and event.step:
            # Query for the corresponding step.enter event
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT created_at FROM noetl.event 
                        WHERE execution_id = %s 
                          AND node_id = %s 
                          AND event_type = 'step.enter'
                        ORDER BY event_id DESC
                        LIMIT 1
                    """, (int(event.execution_id), event.step))
                    enter_event = await cur.fetchone()
                    if enter_event and enter_event['created_at']:
                        start_time = enter_event['created_at']
                        # Ensure both timestamps are timezone-aware for subtraction
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        if event_timestamp.tzinfo is None:
                            event_timestamp = event_timestamp.replace(tzinfo=timezone.utc)
                        duration_ms = int((event_timestamp - start_time).total_seconds() * 1000)
        
        elif "completed" in event.name or "failed" in event.name:
            # For workflow/playbook completion events, calculate total duration from workflow_initialized
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    # Determine which initialization event to use based on completion type
                    init_event_type = "workflow_initialized" if "workflow_" in event.name else "playbook_initialized"
                    
                    await cur.execute("""
                        SELECT created_at FROM noetl.event 
                        WHERE execution_id = %s 
                          AND event_type = %s
                        ORDER BY event_id ASC
                        LIMIT 1
                    """, (int(event.execution_id), init_event_type))
                    init_event = await cur.fetchone()
                    if init_event and init_event['created_at']:
                        start_time = init_event['created_at']
                        # Ensure both timestamps are timezone-aware for subtraction
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        if event_timestamp.tzinfo is None:
                            event_timestamp = event_timestamp.replace(tzinfo=timezone.utc)
                        duration_ms = int((event_timestamp - start_time).total_seconds() * 1000)
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Generate event_id
                event_id = await get_snowflake_id()
                
                # Store root_event_id on first event
                if event.name == "playbook_initialized" and state.root_event_id is None:
                    state.root_event_id = event_id
                
                # Build traceability metadata
                # CRITICAL: Convert all IDs to strings to prevent JavaScript precision loss with Snowflake IDs
                meta = {
                    "execution_id": str(event.execution_id),
                    "catalog_id": str(catalog_id) if catalog_id else None,
                    "root_event_id": str(state.root_event_id) if state.root_event_id else None,
                    "event_chain": [
                        str(state.root_event_id) if state.root_event_id else None,
                        str(parent_event_id) if parent_event_id else None,
                        str(event_id)
                    ] if state.root_event_id else [str(event_id)]
                }
                
                # Add parent execution link if present
                if state.parent_execution_id:
                    meta["parent_execution_id"] = str(state.parent_execution_id)
                
                # Add step-specific metadata
                if event.step:
                    meta["step"] = event.step
                    if event.step in state.step_event_ids:
                        meta["previous_step_event_id"] = str(state.step_event_ids[event.step])
                
                # Merge with existing context metadata
                context_data = event.payload.get("context", {})
                if isinstance(context_data, dict):
                    # CRITICAL: Convert all IDs to strings to prevent JavaScript precision loss with Snowflake IDs
                    context_data["execution_id"] = str(event.execution_id)
                    context_data["catalog_id"] = str(catalog_id) if catalog_id else None
                    context_data["root_event_id"] = str(state.root_event_id) if state.root_event_id else None
                
                # Determine status: Use payload status if provided, otherwise infer from event name
                payload_status = event.payload.get("status")
                if payload_status:
                    # Worker explicitly set status - use it (handles errors properly)
                    status = payload_status.upper() if isinstance(payload_status, str) else str(payload_status).upper()
                else:
                    # Fallback to event name-based status for events without explicit status
                    status = "FAILED" if "failed" in event.name else "COMPLETED" if ("step.exit" == event.name or "completed" in event.name) else "RUNNING"
                
                await cur.execute("""
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, parent_event_id, parent_execution_id, event_type,
                        node_id, node_name, status, context, result, 
                        error, stack_trace, worker_id, duration, meta, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    int(event.execution_id),
                    catalog_id,
                    event_id,
                    parent_event_id,
                    state.parent_execution_id,
                    event.name,
                    event.step,
                    event.step,
                    status,
                    Json(context_data) if context_data else None,
                    Json(event.payload.get("result")) if event.payload.get("result") else None,
                    Json(event.payload.get("error")) if event.payload.get("error") else None,
                    event.payload.get("stack_trace"),
                    event.worker_id,
                    duration_ms,
                    Json(meta),
                    event_timestamp
                ))
            await conn.commit()
        
        # Update tracking for next event
        state.last_event_id = event_id
        if event.step:
            state.step_event_ids[event.step] = event_id
    
    async def start_execution(
        self,
        playbook_path: str,
        payload: dict[str, Any],
        catalog_id: Optional[int] = None,
        parent_execution_id: Optional[int] = None
    ) -> tuple[str, list[Command]]:
        """
        Start a new playbook execution.
        
        Args:
            playbook_path: Path to playbook in catalog
            payload: Input data for execution
            catalog_id: Optional catalog ID
            parent_execution_id: Optional parent execution ID for sub-playbooks
        
        Returns (execution_id, initial_commands).
        """
        # Generate execution ID
        execution_id = str(await get_snowflake_id())
        
        # Load playbook - use catalog_id if provided to load specific version
        if catalog_id:
            playbook = await self.playbook_repo.load_playbook_by_id(catalog_id)
        else:
            playbook = await self.playbook_repo.load_playbook(playbook_path)
        
        if not playbook:
            raise ValueError(f"Playbook not found: catalog_id={catalog_id} path={playbook_path}")
        
        # Create execution state with catalog_id and parent_execution_id
        state = ExecutionState(execution_id, playbook, payload, catalog_id, parent_execution_id)
        await self.state_store.save_state(state)
        
        # Process keychain section before workflow starts
        if playbook.keychain and catalog_id:
            logger.info(f"ENGINE: Processing keychain section with {len(playbook.keychain)} entries")
            from noetl.server.keychain_processor import process_keychain_section
            try:
                keychain_data = await process_keychain_section(
                    keychain_section=playbook.keychain,
                    catalog_id=catalog_id,
                    execution_id=int(execution_id),
                    workload_vars=state.variables
                )
                if keychain_data:
                    # Expose keychain entries directly and under 'keychain' namespace for rendering
                    state.variables.update(keychain_data)
                    state.variables.setdefault("keychain", {}).update(keychain_data)
                logger.info(f"ENGINE: Keychain processing complete, created {len(keychain_data)} entries")
            except Exception as e:
                logger.error(f"ENGINE: Failed to process keychain section: {e}")
                # Don't fail execution, keychain errors will surface when workers try to resolve
        
        # Find start step
        start_step = state.get_step("start")
        if not start_step:
            raise ValueError("Playbook must have a 'start' step")
        
        # Emit playbook.initialized event (playbook loaded and validated)
        # CRITICAL: Strip massive result objects from workload to prevent state pollution in sub-playbooks
        # Only keep genuine workload variables
        workload_snapshot = {}
        for k, v in state.variables.items():
            # Skip step result objects (they are usually dicts with 'id', 'status', 'data' keys)
            if isinstance(v, dict) and 'status' in v and ('data' in v or 'error' in v):
                continue
            # Skip large result proxies or objects
            if k in state.step_results:
                continue
            workload_snapshot[k] = v

        from noetl.core.dsl.v2.models import LifecycleEventPayload
        playbook_init_event = Event(
            execution_id=execution_id,
            step=playbook_path,
            name="playbook.initialized",
            payload=LifecycleEventPayload(
                status="initialized",
                final_step=None,
                result={"workload": workload_snapshot, "playbook_path": playbook_path}
            ).model_dump(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await self._persist_event(playbook_init_event, state)
        
        # Emit workflow.initialized event (workflow execution starting)
        workflow_init_event = Event(
            execution_id=execution_id,
            step="workflow",
            name="workflow.initialized",
            payload=LifecycleEventPayload(
                status="initialized",
                final_step=None,
                result={"first_step": "start", "playbook_path": playbook_path, "workload": workload_snapshot}
            ).model_dump(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await self._persist_event(workflow_init_event, state)
        
        # Create initial command for start step
        start_command = await self._create_command_for_step(state, start_step, payload)
        
        commands = [start_command] if start_command else []
        
        return execution_id, commands
