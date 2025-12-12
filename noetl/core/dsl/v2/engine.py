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
    
    def __init__(self, execution_id: str, playbook: Playbook, payload: dict[str, Any], catalog_id: Optional[int] = None):
        self.execution_id = execution_id
        self.playbook = playbook
        self.payload = payload
        self.catalog_id = catalog_id  # Store catalog_id for event persistence
        self.current_step: Optional[str] = None
        self.variables: dict[str, Any] = {}
        self.step_results: dict[str, Any] = {}
        self.completed_steps: set[str] = set()
        self.failed = False
        self.completed = False
        
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
        """Mark step as completed and store result."""
        self.completed_steps.add(step_name)
        if result is not None:
            self.step_results[step_name] = result
            self.variables[step_name] = result
    
    def is_step_completed(self, step_name: str) -> bool:
        """Check if step is completed."""
        return step_name in self.completed_steps
    
    def get_render_context(self, event: Event) -> dict[str, Any]:
        """Get context for Jinja2 rendering."""
        context = {
            "event": {
                "name": event.name,
                "payload": event.payload,
                "step": event.step,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            },
            "execution_id": self.execution_id,
            "workload": self.variables,
            "vars": self.variables,
            **self.variables,  # Make variables accessible at top level
            **self.step_results,  # Make step results accessible (e.g., {{ process }})
        }
        
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


class StateStore:
    """Stores and retrieves execution state."""
    
    def __init__(self):
        self._memory_cache: dict[str, ExecutionState] = {}
    
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
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO noetl.workload (execution_id, data, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (execution_id) 
                    DO UPDATE SET data = %s
                """, (
                    int(state.execution_id), 
                    Json(state_data),
                    datetime.now(timezone.utc),
                    Json(state_data)
                ))
            await conn.commit()
    
    async def load_state(self, execution_id: str) -> Optional[ExecutionState]:
        """Load execution state."""
        # Check memory first
        if execution_id in self._memory_cache:
            return self._memory_cache[execution_id]
        
        # TODO: Load from database if needed
        return None
    
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
    
    def _render_template(self, template_str: str, context: dict[str, Any]) -> Any:
        """Render Jinja2 template."""
        try:
            # Check if this is a simple variable reference like {{ varname }}
            # If so, return the actual object instead of string representation
            import re
            simple_var_match = re.match(r'^\{\{\s*(\w+)\s*\}\}$', template_str.strip())
            if simple_var_match:
                var_name = simple_var_match.group(1)
                if var_name in context:
                    return context[var_name]
            
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
        
        return commands
    
    def _create_command_for_step(
        self,
        state: ExecutionState,
        step: Step,
        args: dict[str, Any]
    ) -> Optional[Command]:
        """Create a command to execute a step."""
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
        
        # Render Jinja2 templates in tool config
        rendered_tool_config = {}
        for key, value in tool_config.items():
            if isinstance(value, str) and "{{" in value:
                try:
                    rendered_tool_config[key] = self._render_template(value, context)
                except Exception as e:
                    logger.warning(f"Failed to render tool config {key}: {e}")
                    rendered_tool_config[key] = value
            else:
                rendered_tool_config[key] = value
        
        # Render Jinja2 templates in args
        rendered_args = {}
        for key, value in step_args.items():
            if isinstance(value, str) and "{{" in value:
                try:
                    rendered_args[key] = self._render_template(value, context)
                except Exception as e:
                    logger.warning(f"Failed to render arg {key}: {e}")
                    rendered_args[key] = value
            else:
                rendered_args[key] = value
        
        command = Command(
            execution_id=state.execution_id,
            step=step.step,
            tool=ToolCall(
                kind=step.tool.kind,
                config=rendered_tool_config  # Tool-specific config (code, url, query, etc.)
            ),
            args=rendered_args,  # Rendered step input arguments
            attempt=1,
            priority=0
        )
        
        return command
    
    async def handle_event(self, event: Event) -> list[Command]:
        """
        Handle an event and return commands to enqueue.
        
        This is the core engine method called by the API.
        """
        commands: list[Command] = []
        
        # Load execution state
        state = self.state_store.get_state(event.execution_id)
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
            logger.debug(f"Stored result for step {event.step}")
        
        # Get render context
        context = state.get_render_context(event)
        
        # Process case rules
        if step_def.case:
            for case_entry in step_def.case:
                # Evaluate condition
                if self._evaluate_condition(case_entry.when, context):
                    logger.info(f"Case matched: {case_entry.when}")
                    
                    # Process then actions
                    new_commands = await self._process_then_actions(
                        case_entry.then,
                        state,
                        event
                    )
                    commands.extend(new_commands)
                    
                    # First match wins
                    break
        
        # If step.exit event and no case matched, use structural next
        if event.name == "step.exit" and step_def.next and not commands:
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
                
                step_def = state.get_step(target_step)
                if step_def:
                    command = self._create_command_for_step(state, step_def, {})
                    if command:
                        commands.append(command)
        
        # Save state
        await self.state_store.save_state(state)
        
        # Persist event to database
        await self._persist_event(event, state)
        
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
        
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                # Generate event_id
                event_id = await get_snowflake_id()
                
                await cur.execute("""
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, event_type,
                        node_id, node_name, status, context, result, 
                        error, stack_trace, worker_id, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    int(event.execution_id),
                    catalog_id,
                    event_id,
                    event.name,
                    event.step,
                    event.step,
                    "COMPLETED" if event.name == "step.exit" else "RUNNING",
                    Json(event.payload.get("context")) if event.payload.get("context") else None,
                    Json(event.payload.get("result")) if event.payload.get("result") else None,
                    Json(event.payload.get("error")) if event.payload.get("error") else None,
                    event.payload.get("stack_trace"),
                    event.worker_id,
                    event.timestamp or datetime.now(timezone.utc)
                ))
            await conn.commit()
    
    async def start_execution(
        self,
        playbook_path: str,
        payload: dict[str, Any],
        catalog_id: Optional[int] = None
    ) -> tuple[str, list[Command]]:
        """
        Start a new playbook execution.
        
        Returns (execution_id, initial_commands).
        """
        # Generate execution ID
        execution_id = str(await get_snowflake_id())
        
        # Load playbook
        playbook = await self.playbook_repo.load_playbook(playbook_path)
        if not playbook:
            raise ValueError(f"Playbook not found: {playbook_path}")
        
        # Create execution state with catalog_id
        state = ExecutionState(execution_id, playbook, payload, catalog_id)
        await self.state_store.save_state(state)
        
        # Find start step
        start_step = state.get_step("start")
        if not start_step:
            raise ValueError("Playbook must have a 'start' step")
        
        # Emit workflow_initialized event
        init_event = Event(
            execution_id=execution_id,
            step="start",
            name="workflow_initialized",
            payload={"workload": state.variables},
            timestamp=datetime.now(timezone.utc)
        )
        
        await self._persist_event(init_event, state)
        
        # Create initial command for start step
        start_command = self._create_command_for_step(state, start_step, payload)
        
        commands = [start_command] if start_command else []
        
        return execution_id, commands
