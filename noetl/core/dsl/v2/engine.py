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
from typing import Any, Optional
from datetime import datetime, timezone
from jinja2 import Template, Environment, StrictUndefined
from psycopg.types.json import Json

from noetl.core.dsl.v2.models import Event, Command, Playbook, Step, CaseEntry, ToolCall
from noetl.core.db.pool import get_pool_connection, get_snowflake_id

logger = logging.getLogger(__name__)


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
        
        # Event tracking for parent_event_id
        self.last_event_id: Optional[int] = None  # Track last event_id for parent linkage
        self.step_event_ids: dict[str, int] = {}  # step_name -> last event_id for that step
        
        # Root event tracking for traceability
        self.root_event_id: Optional[int] = None  # First event (playbook.initialized) for full trace
        
        # Loop state tracking
        self.loop_state: dict[str, dict[str, Any]] = {}  # step_name -> {collection, index, item, mode}
        
        # Initialize workload variables
        if playbook.workload:
            self.variables.update(playbook.workload)
        
        # Merge payload
        self.variables.update(payload)
    
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
    
    def init_loop(self, step_name: str, collection: list[Any], iterator: str, mode: str = "sequential"):
        """Initialize loop state for a step."""
        self.loop_state[step_name] = {
            "collection": collection,
            "iterator": iterator,
            "index": 0,
            "mode": mode,
            "completed": False
        }
        logger.debug(f"Initialized loop for step {step_name}: {len(collection)} items, mode={mode}")
    
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
            "workload": self.variables,
            "vars": self.variables,
            **self.variables,  # Make variables accessible at top level (includes loop vars)
            **self.step_results,  # Make step results accessible (e.g., {{ process }})
        }
        
        # Set protected fields AFTER spreading variables to ensure they are not overridden
        context["execution_id"] = self.execution_id
        context["catalog_id"] = self.catalog_id
        context["job"] = {
            "uuid": self.execution_id,
            "execution_id": self.execution_id,
            "id": self.execution_id
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
                # Get playbook info from first event
                await cur.execute("""
                    SELECT catalog_id, node_id
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id
                    LIMIT 1
                """, (int(execution_id),))
                
                result = await cur.fetchone()
                if not result:
                    return None
                
                catalog_id = result[0]  # First column
                
                # Load playbook
                playbook = await self.playbook_repo.load_playbook_by_id(catalog_id)
                if not playbook:
                    return None
                
                # Create new state
                state = ExecutionState(execution_id, playbook, {}, catalog_id)
                
                # Replay events to rebuild state (event sourcing)
                await cur.execute("""
                    SELECT node_name, event_type, result
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id
                """, (int(execution_id),))
                
                rows = await cur.fetchall()
                for row in rows:
                    node_name = row[0]
                    event_type = row[1]
                    result_data = row[2]
                    
                    # Restore step results from step.exit events
                    if event_type == 'step.exit' and result_data:
                        state.mark_step_completed(node_name, result_data)
                
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
        try:
            # Check if this is a simple variable reference like {{ varname }} or {{ obj.attr }}
            # If so, evaluate and return the actual object instead of string representation
            import re
            simple_var_match = re.match(r'^\{\{\s*([\w.]+)\s*\}\}$', template_str.strip())
            if simple_var_match:
                var_path = simple_var_match.group(1)
                # Navigate dot notation: workload.numbers → context['workload']['numbers']
                value = context
                for part in var_path.split('.'):
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
            
            template = self.jinja_env.from_string(template_str)
            result = template.render(**context)
            
            # Try to parse as boolean for conditions
            if result.lower() in ("true", "false"):
                return result.lower() == "true"
            
            return result
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            logger.error(f"Template: {template_str}")
            logger.error(f"Context keys: {list(context.keys())}")
            raise
    
    def _evaluate_condition(self, when_expr: str, context: dict[str, Any]) -> bool:
        """Evaluate when condition."""
        try:
            # Render the condition
            result = self._render_template(when_expr, context)
            
            # Convert to boolean
            if isinstance(result, bool):
                return result
            if isinstance(result, str):
                return result.lower() in ("true", "1", "yes")
            return bool(result)
        except Exception as e:
            logger.error(f"Condition evaluation error: {e}")
            logger.error(f"Condition: {when_expr}")
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
            logger.debug(f"[CASE-EVAL] Step {event.step} has {len(step_def.case)} case rules, evaluating for event {event.name}")
            for idx, case_entry in enumerate(step_def.case):
                # Evaluate condition
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
        
        for action in actions:
            if not isinstance(action, dict):
                continue
            
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
                    
                    # Get target step definition
                    step_def = state.get_step(target_step)
                    if not step_def:
                        logger.error(f"Target step not found: {target_step}")
                        continue
                    
                    # Create command for target step
                    command = self._create_command_for_step(
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
            
            elif "collect" in action:
                # Collect data into context variable
                collect_spec = action["collect"]
                from_path = collect_spec.get("from")
                into_var = collect_spec.get("into")
                mode = collect_spec.get("mode", "append")
                
                if from_path and into_var:
                    # Get source data
                    if isinstance(from_path, str) and "{{" in from_path:
                        source_data = self._render_template(from_path, context)
                    else:
                        source_data = from_path
                    
                    # Initialize target if needed
                    if into_var not in state.variables:
                        state.variables[into_var] = []
                    
                    # Collect based on mode
                    if mode == "append":
                        if not isinstance(state.variables[into_var], list):
                            state.variables[into_var] = [state.variables[into_var]]
                        state.variables[into_var].append(source_data)
                    elif mode == "extend":
                        if isinstance(source_data, list):
                            state.variables[into_var].extend(source_data)
                        else:
                            state.variables[into_var].append(source_data)
            
            elif "call" in action:
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
                command = self._create_command_for_step(state, step_def, rendered_args)
                if command:
                    commands.append(command)
                    logger.info(f"Call action: invoking step {target_step}")
            
            elif "retry" in action:
                # Retry current step with optional backoff
                retry_spec = action["retry"]
                delay = retry_spec.get("delay", 0)
                max_attempts = retry_spec.get("max_attempts", 3)
                backoff = retry_spec.get("backoff", "linear")  # linear, exponential
                
                # Get current attempt from event.meta or event.attempt (fallback)
                current_attempt = 1
                if event.meta and "attempt" in event.meta:
                    current_attempt = event.meta["attempt"]
                elif event.attempt:
                    current_attempt = event.attempt
                
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
                command = self._create_command_for_step(state, step_def, {})
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
            
            elif "sink" in action:
                # Persist step result to storage backend
                sink_spec = action["sink"]
                backend = sink_spec.get("backend", "postgres")
                table = sink_spec.get("table")
                data_source = sink_spec.get("from", "{{ response }}")
                
                if not table:
                    logger.warning("Sink action missing 'table' attribute")
                    continue
                
                # Render data source recursively (handles dicts, lists, strings)
                data = self._render_value_recursive(data_source, context)
                
                # Create sink command (uses special sink tool kind)
                # Note: sink executor expects 'tool' not 'backend'
                sink_command = Command(
                    execution_id=state.execution_id,
                    step=f"{event.step}_sink",
                    tool=ToolCall(
                        kind="sink",
                        config={
                            "tool": backend,  # executor expects 'tool' field
                            "table": table,
                            "data": data,
                            "auth": sink_spec.get("auth")
                        }
                    ),
                    args={}
                )
                commands.append(sink_command)
                logger.info(f"Sink action: persisting to {backend}.{table}")
        
        return commands
    
    def _create_command_for_step(
        self,
        state: ExecutionState,
        step: Step,
        args: dict[str, Any]
    ) -> Optional[Command]:
        """Create a command to execute a step."""
        # Debug: Check if step has loop
        logger.warning(f"[CREATE-CMD] Step {step.step} has loop? {step.loop is not None}")
        if step.loop:
            logger.warning(f"[CREATE-CMD] Loop config: in={step.loop.in_}, iterator={step.loop.iterator}, mode={step.loop.mode}")
        
        # Check if step has loop configuration
        if step.loop and step.step not in state.loop_state:
            # Initialize loop on first encounter
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
            
            state.init_loop(step.step, collection, step.loop.iterator, step.loop.mode)
            logger.info(f"Initialized loop for {step.step} with {len(collection)} items")
        
        # If step has loop, check for next item
        if step.loop:
            next_item = state.get_next_loop_item(step.step)
            if next_item is None:
                # Loop completed
                logger.info(f"[LOOP] Loop completed for step {step.step}")
                return None  # No command, will generate loop.done event
            
            item, index = next_item
            logger.info(f"[LOOP] Creating command for loop iteration {index} of step {step.step}, item={item}")
            
            # CRITICAL: Add loop variables to state.variables for Jinja2 template rendering
            # Do NOT add to args dict - let templates {{ num }} be rendered from context
            state.variables[step.loop.iterator] = item
            state.variables["loop_index"] = index
            logger.info(f"[LOOP] Added to state.variables: {step.loop.iterator}={item}, loop_index={index}")
        
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
            logger.error(f"DEBUG: Creating command for verify_result")
            logger.error(f"DEBUG: state.step_results keys: {list(state.step_results.keys())}")
            logger.error(f"DEBUG: state.variables keys: {list(state.variables.keys())}")
            logger.error(f"DEBUG: step_args: {step_args}")
            if 'run_python_from_gcs' in state.step_results:
                logger.error(f"DEBUG: run_python_from_gcs result: {state.step_results['run_python_from_gcs']}")
        
        # Debug: Log loop variables in context
        if step.loop:
            logger.warning(f"[LOOP-DEBUG] Step {step.step} render context keys: {list(context.keys())}")
            logger.warning(f"[LOOP-DEBUG] Iterator '{step.loop.iterator}' value in context: {context.get(step.loop.iterator, 'NOT FOUND')}")
            logger.warning(f"[LOOP-DEBUG] loop_index value in context: {context.get('loop_index', 'NOT FOUND')}")
            logger.warning(f"[LOOP-DEBUG] state.variables: {state.variables}")
        
        # Render Jinja2 templates in tool config
        # CRITICAL: Use recursive render_template to handle nested dicts/lists like params: {latitude: "{{ city.lat }}"}
        from noetl.core.dsl.render import render_template as recursive_render
        from jinja2 import Environment, BaseLoader
        
        env = Environment(loader=BaseLoader())
        rendered_tool_config = recursive_render(env, tool_config, context)
        
        # Render Jinja2 templates in args (also use recursive rendering for nested structures)
        rendered_args = recursive_render(env, step_args, context)
        
        command = Command(
            execution_id=state.execution_id,
            step=step.step,
            tool=ToolCall(
                kind=step.tool.kind,
                config=rendered_tool_config  # Tool-specific config (code, url, query, etc.)
            ),
            args=rendered_args,  # Rendered step input arguments
            render_context=context,  # Pass full context for plugin template rendering
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
            from jinja2 import BaseLoader, Environment
            
            # Build context for template rendering
            # The 'result' key points to the step's output for current step vars extraction
            eval_ctx = state.get_render_context(event)
            
            # Render each variable template
            env = Environment(loader=BaseLoader())
            rendered_vars = {}
            
            for var_name, var_template in vars_block.items():
                try:
                    if isinstance(var_template, str):
                        template = env.from_string(var_template)
                        rendered_value = template.render(eval_ctx)
                        
                        # Try to parse as JSON if it looks like JSON
                        if rendered_value.strip().startswith(("{", "[")):
                            try:
                                import json
                                rendered_value = json.loads(rendered_value)
                            except:
                                pass  # Keep as string
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
    
    async def handle_event(self, event: Event) -> list[Command]:
        """
        Handle an event and return commands to enqueue.
        
        This is the core engine method called by the API.
        """
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
        
        step_def = state.get_step(event.step)
        if not step_def:
            logger.error(f"Step not found: {event.step}")
            return commands
        
        # Update current step
        state.set_current_step(event.step)
        
        # Store step result if this is a step.exit event
        if event.name == "step.exit" and "result" in event.payload:
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
            command = self._create_command_for_step(state, step_def, {})
            if command:
                commands.append(command)
                logger.debug(f"Created command for next loop iteration")
            else:
                # Loop completed, would emit loop.done below
                logger.debug(f"Loop iteration complete, will check for loop.done")
        
        # Check if step has completed loop - emit loop.done event
        # Check on step.exit regardless of whether case generated commands
        # (case may have matched call.done and generated sink/next commands)
        if step_def.loop and event.name == "step.exit":
            if not state.is_loop_done(event.step):
                # More items to process - create next iteration command if not already created
                # (case rules may have already created next iteration)
                if not any(cmd.step == event.step for cmd in commands):
                    logger.debug(f"Loop has more items, creating next command")
                    command = self._create_command_for_step(state, step_def, {})
                    if command:
                        commands.append(command)
            else:
                # Loop done - recursively process loop.done event through case matching
                logger.info(f"Loop completed for step {event.step}, processing loop.done event")
                loop_done_event = Event(
                    execution_id=event.execution_id,
                    step=event.step,
                    name="loop.done",
                    payload={"status": "completed", "iterations": state.loop_state[event.step]["index"]}
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
                        command = self._create_command_for_step(state, next_step_def, {})
                        if command:
                            commands.append(command)
                            logger.info(f"[STRUCTURAL-NEXT] Created command for step {target_step}")

        
        # Check for completion (only emit once) - prepare completion events but persist after current event
        # Completion triggers when step.exit occurs with no commands generated AND step has no routing
        # This handles explicit terminal steps (no next/case blocks) only
        # OR when a step fails with no error handler (no commands generated despite having routing)
        completion_events = []
        logger.info(f"=== COMPLETION CHECK === event={event.name}, step={event.step}, commands={len(commands)}, completed={state.completed}, has_next={bool(step_def.next if step_def else False)}, has_case={bool(step_def.case if step_def else False)}, has_error={bool(event.payload.get('error'))}")
        
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
        if not completion_events:
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
                meta = {
                    "execution_id": str(event.execution_id),
                    "catalog_id": catalog_id,
                    "root_event_id": state.root_event_id,
                    "event_chain": [
                        state.root_event_id,
                        parent_event_id,
                        event_id
                    ] if state.root_event_id else [event_id]
                }
                
                # Add parent execution link if present
                if state.parent_execution_id:
                    meta["parent_execution_id"] = state.parent_execution_id
                
                # Add step-specific metadata
                if event.step:
                    meta["step"] = event.step
                    if event.step in state.step_event_ids:
                        meta["previous_step_event_id"] = state.step_event_ids[event.step]
                
                # Merge with existing context metadata
                context_data = event.payload.get("context", {})
                if isinstance(context_data, dict):
                    # Ensure execution_id and catalog_id are in context for easy access
                    context_data["execution_id"] = str(event.execution_id)
                    context_data["catalog_id"] = catalog_id
                    context_data["root_event_id"] = state.root_event_id
                
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
        
        # Load playbook
        playbook = await self.playbook_repo.load_playbook(playbook_path)
        if not playbook:
            raise ValueError(f"Playbook not found: {playbook_path}")
        
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
                logger.info(f"ENGINE: Keychain processing complete, created {len(keychain_data)} entries")
            except Exception as e:
                logger.error(f"ENGINE: Failed to process keychain section: {e}")
                # Don't fail execution, keychain errors will surface when workers try to resolve
        
        # Find start step
        start_step = state.get_step("start")
        if not start_step:
            raise ValueError("Playbook must have a 'start' step")
        
        # Emit playbook.initialized event (playbook loaded and validated)
        from noetl.core.dsl.v2.models import LifecycleEventPayload
        playbook_init_event = Event(
            execution_id=execution_id,
            step=playbook_path,
            name="playbook.initialized",
            payload=LifecycleEventPayload(
                status="initialized",
                final_step=None,
                result={"workload": state.variables, "playbook_path": playbook_path}
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
                result={"first_step": "start", "playbook_path": playbook_path}
            ).model_dump(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await self._persist_event(workflow_init_event, state)
        
        # Create initial command for start step
        start_command = self._create_command_for_step(state, start_step, payload)
        
        commands = [start_command] if start_command else []
        
        return execution_id, commands
