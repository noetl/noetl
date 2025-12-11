"""
NoETL DSL v2 Control Flow Engine

Server-side event-driven orchestration that:
- Receives events from workers
- Evaluates case/when/then rules with Jinja2
- Executes actions (call, retry, collect, sink, set, result, next, fail, skip)
- Generates Command objects for queue table
"""

import logging
from typing import Any, Optional
from jinja2 import Environment, Template, TemplateSyntaxError, UndefinedError
from .models import (
    Event, Command, Playbook, Step, ToolCall, CaseEntry,
    ToolSpec
)
from .parser import DSLParser

logger = logging.getLogger(__name__)


# ============================================================================
# State Management
# ============================================================================

class ExecutionState:
    """
    Manages state for a single execution.
    
    Tracks:
    - Current step
    - Context variables (set via 'set' action)
    - Step results
    - Loop state (iterator values, indices)
    - Workflow status
    """
    
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.current_step: Optional[str] = None
        self.context: dict[str, Any] = {}
        self.step_results: dict[str, Any] = {}
        self.loop_state: dict[str, Any] = {}
        self.workflow_status: str = "running"
        self.last_response: Optional[dict[str, Any]] = None
        self.last_error: Optional[dict[str, Any]] = None
    
    def update_from_event(self, event: Event):
        """Update state based on event."""
        if event.step:
            self.current_step = event.step
        
        # Extract response/error from payload
        if "response" in event.payload:
            self.last_response = event.payload["response"]
        
        if "error" in event.payload:
            self.last_error = event.payload["error"]
    
    def set_context(self, key: str, value: Any):
        """Set context variable."""
        self.context[key] = value
    
    def set_step_result(self, step: str, result: Any):
        """Set step result."""
        self.step_results[step] = result
    
    def get_jinja_context(self, workload: dict[str, Any], args: Optional[dict[str, Any]], event: Event) -> dict[str, Any]:
        """
        Build Jinja2 context for template evaluation.
        
        Includes:
        - workload: global variables
        - args: step input arguments
        - ctx: context variables
        - event: current event with event.name
        - response: last response (for call.done)
        - error: last error (for call.done)
        - step_results: all step results
        - loop: loop state
        """
        context = {
            "workload": workload,
            "args": args or {},
            "ctx": self.context,
            "event": {
                "name": event.name,
                "step": event.step,
                "payload": event.payload,
            },
            "execution_id": self.execution_id,
        }
        
        # Add response/error for call.done events
        if self.last_response:
            context["response"] = self.last_response
        
        if self.last_error:
            context["error"] = self.last_error
        
        # Add step results
        context.update(self.step_results)
        
        # Add loop state
        if self.loop_state:
            context["loop"] = self.loop_state
        
        return context


class StateStore:
    """
    State storage interface.
    In-memory for now, can be Redis/DB for production.
    """
    
    def __init__(self):
        self._states: dict[str, ExecutionState] = {}
    
    def get(self, execution_id: str) -> ExecutionState:
        """Get or create execution state."""
        if execution_id not in self._states:
            self._states[execution_id] = ExecutionState(execution_id)
        return self._states[execution_id]
    
    def set(self, execution_id: str, state: ExecutionState):
        """Store execution state."""
        self._states[execution_id] = state
    
    def delete(self, execution_id: str):
        """Delete execution state."""
        self._states.pop(execution_id, None)


# ============================================================================
# Playbook Repository
# ============================================================================

class PlaybookRepo:
    """
    Playbook storage and retrieval.
    Handles playbook registration and lookup by execution_id.
    """
    
    def __init__(self):
        self._playbooks: dict[str, Playbook] = {}
        self._execution_to_playbook: dict[str, str] = {}
        self.parser = DSLParser()
    
    def register(self, playbook: Playbook, execution_id: str):
        """Register playbook for an execution."""
        playbook_key = playbook.metadata["name"]
        self._playbooks[playbook_key] = playbook
        self._execution_to_playbook[execution_id] = playbook_key
    
    def get_by_execution(self, execution_id: str) -> Optional[Playbook]:
        """Get playbook by execution_id."""
        playbook_key = self._execution_to_playbook.get(execution_id)
        if playbook_key:
            return self._playbooks.get(playbook_key)
        return None
    
    def get_by_key(self, playbook_key: str) -> Optional[Playbook]:
        """Get playbook by key."""
        return self._playbooks.get(playbook_key)
    
    def list_playbooks(self) -> list[str]:
        """List all registered playbook keys."""
        return list(self._playbooks.keys())


# ============================================================================
# Control Flow Engine
# ============================================================================

class ControlFlowEngine:
    """
    Event-driven control flow orchestration.
    
    Responsibilities:
    1. Load playbook & execution state
    2. Build Jinja2 context from event
    3. Evaluate case/when/then rules
    4. Execute actions (call, retry, collect, sink, set, result, next, fail, skip)
    5. Generate Command objects for queue table
    """
    
    def __init__(self, playbook_repo: PlaybookRepo, state_store: StateStore):
        self.playbook_repo = playbook_repo
        self.state_store = state_store
        self.jinja_env = Environment()
    
    def handle_event(self, event: Event) -> list[Command]:
        """
        Handle event and generate commands.
        
        Args:
            event: Event from worker or internal
            
        Returns:
            List of commands to insert into queue table
        """
        logger.info(f"Handling event: {event.execution_id} / {event.name} / {event.step}")
        
        # Load playbook
        playbook = self.playbook_repo.get_by_execution(event.execution_id)
        if not playbook:
            logger.error(f"Playbook not found for execution {event.execution_id}")
            return []
        
        # Load/update state
        state = self.state_store.get(event.execution_id)
        state.update_from_event(event)
        
        # Handle workflow.start - initialize with start step
        if event.name == "workflow.start":
            return self._handle_workflow_start(event, playbook, state)
        
        # Get current step
        if not event.step:
            logger.warning(f"Event {event.name} has no step")
            return []
        
        step = self._get_step(playbook, event.step)
        if not step:
            logger.error(f"Step {event.step} not found in playbook")
            return []
        
        # Build Jinja context
        workload = playbook.workload or {}
        args = step.args or {}
        jinja_context = state.get_jinja_context(workload, args, event)
        
        # Evaluate case rules
        commands = []
        if step.case:
            commands = self._evaluate_case_rules(step, jinja_context, state, event)
        
        # If no case rules fired and step is complete (step.exit), use structural next
        if not commands and event.name == "step.exit" and step.next:
            commands = self._handle_structural_next(step, state, jinja_context)
        
        return commands
    
    def _handle_workflow_start(self, event: Event, playbook: Playbook, state: ExecutionState) -> list[Command]:
        """Handle workflow.start event - generate command for 'start' step."""
        start_step = self._get_step(playbook, "start")
        if not start_step:
            logger.error("No 'start' step found in playbook")
            return []
        
        # Generate command for start step
        return [self._create_command(
            execution_id=event.execution_id,
            step=start_step.step,
            tool=start_step.tool,
            args=start_step.args
        )]
    
    def _evaluate_case_rules(
        self, 
        step: Step, 
        jinja_context: dict[str, Any], 
        state: ExecutionState,
        event: Event
    ) -> list[Command]:
        """
        Evaluate case entries and execute matched then actions.
        
        Returns commands generated from actions.
        """
        commands = []
        
        for i, case_entry in enumerate(step.case):
            # Evaluate when condition
            try:
                condition_result = self._evaluate_jinja(case_entry.when, jinja_context)
            except Exception as e:
                logger.error(f"Error evaluating case[{i}].when: {e}")
                continue
            
            if not condition_result:
                continue
            
            logger.info(f"Case rule {i} matched for step {step.step}")
            
            # Execute then actions
            then_commands = self._execute_actions(
                case_entry.then,
                step,
                state,
                jinja_context,
                event
            )
            commands.extend(then_commands)
            
            # Stop after first match (can be made configurable)
            break
        
        return commands
    
    def _execute_actions(
        self,
        then_block: dict | list,
        step: Step,
        state: ExecutionState,
        jinja_context: dict[str, Any],
        event: Event
    ) -> list[Command]:
        """
        Execute actions from then block.
        
        Supported actions:
        - call: Re-invoke tool with overrides
        - retry: Retry last call with backoff
        - collect: Aggregate data
        - sink: Write to external storage
        - set: Update context
        - result: Set step result
        - next: Transition to other steps
        - fail: Mark as failed
        - skip: Mark as skipped
        """
        commands = []
        
        # Normalize to list
        actions = then_block if isinstance(then_block, list) else [then_block]
        
        for action in actions:
            if not isinstance(action, dict):
                continue
            
            # Call action
            if "call" in action:
                cmd = self._action_call(action["call"], step, state, jinja_context, event)
                if cmd:
                    commands.append(cmd)
            
            # Retry action
            elif "retry" in action:
                cmd = self._action_retry(action["retry"], step, state, event)
                if cmd:
                    commands.append(cmd)
            
            # Collect action
            elif "collect" in action:
                self._action_collect(action["collect"], state, jinja_context)
            
            # Sink action
            elif "sink" in action:
                cmd = self._action_sink(action["sink"], state, jinja_context, event)
                if cmd:
                    commands.append(cmd)
            
            # Set action
            elif "set" in action:
                self._action_set(action["set"], state, jinja_context)
            
            # Result action
            elif "result" in action:
                self._action_result(action["result"], step, state, jinja_context)
            
            # Next action
            elif "next" in action:
                next_commands = self._action_next(action["next"], state, jinja_context, event)
                commands.extend(next_commands)
            
            # Fail action
            elif "fail" in action:
                self._action_fail(action["fail"], state)
            
            # Skip action
            elif "skip" in action:
                self._action_skip(action["skip"], state)
        
        return commands
    
    def _action_call(
        self, 
        call_config: dict, 
        step: Step, 
        state: ExecutionState, 
        jinja_context: dict[str, Any],
        event: Event
    ) -> Optional[Command]:
        """Re-invoke tool with parameter overrides."""
        # Render overrides
        rendered_overrides = self._render_dict(call_config, jinja_context)
        
        # Merge with original tool config
        tool_config = step.tool.model_dump(exclude={"kind"}, by_alias=True)
        tool_config.update(rendered_overrides)
        
        return self._create_command(
            execution_id=event.execution_id,
            step=step.step,
            tool=step.tool,
            args=step.args,
            metadata={"action": "call", "overrides": rendered_overrides}
        )
    
    def _action_retry(
        self, 
        retry_config: dict, 
        step: Step, 
        state: ExecutionState,
        event: Event
    ) -> Optional[Command]:
        """Retry last call with backoff."""
        max_attempts = retry_config.get("max_attempts", 3)
        backoff_multiplier = retry_config.get("backoff_multiplier", 2.0)
        initial_delay = retry_config.get("initial_delay", 0.5)
        
        current_attempt = event.attempt
        if current_attempt >= max_attempts:
            logger.warning(f"Max retry attempts ({max_attempts}) reached for {step.step}")
            return None
        
        backoff_delay = initial_delay * (backoff_multiplier ** (current_attempt - 1))
        
        return self._create_command(
            execution_id=event.execution_id,
            step=step.step,
            tool=step.tool,
            args=step.args,
            attempt=current_attempt + 1,
            backoff=backoff_delay,
            max_attempts=max_attempts,
            metadata={"action": "retry"}
        )
    
    def _action_collect(self, collect_config: dict, state: ExecutionState, jinja_context: dict[str, Any]):
        """Collect data into context."""
        from_path = collect_config.get("from", "")
        into_var = collect_config.get("into", "")
        mode = collect_config.get("mode", "append")
        
        # Evaluate from path
        try:
            value = self._evaluate_jinja(from_path, jinja_context)
        except Exception as e:
            logger.error(f"Error evaluating collect.from: {e}")
            return
        
        # Get current value
        current = state.context.get(into_var)
        
        # Apply mode
        if mode == "append":
            if current is None:
                current = []
            if isinstance(current, list):
                current.append(value)
        elif mode == "extend":
            if current is None:
                current = []
            if isinstance(current, list) and isinstance(value, list):
                current.extend(value)
        elif mode == "merge":
            if current is None:
                current = {}
            if isinstance(current, dict) and isinstance(value, dict):
                current.update(value)
        else:
            current = value
        
        state.set_context(into_var, current)
    
    def _action_sink(
        self, 
        sink_config: dict, 
        state: ExecutionState, 
        jinja_context: dict[str, Any],
        event: Event
    ) -> Optional[Command]:
        """Write data to external sink."""
        # Render sink config
        rendered_config = self._render_dict(sink_config, jinja_context)
        
        # Extract tool config
        tool_data = rendered_config.get("tool", {})
        if not tool_data or "kind" not in tool_data:
            logger.error("Sink action missing tool.kind")
            return None
        
        tool_spec = ToolSpec(**tool_data)
        
        return self._create_command(
            execution_id=event.execution_id,
            step=f"_sink_{event.step}",
            tool=tool_spec,
            args=rendered_config.get("args"),
            metadata={"action": "sink", "source_step": event.step}
        )
    
    def _action_set(self, set_config: dict, state: ExecutionState, jinja_context: dict[str, Any]):
        """Set context variables."""
        rendered = self._render_dict(set_config, jinja_context)
        
        # Handle nested ctx
        if "ctx" in rendered:
            for key, value in rendered["ctx"].items():
                state.set_context(key, value)
        else:
            for key, value in rendered.items():
                state.set_context(key, value)
    
    def _action_result(self, result_config: dict, step: Step, state: ExecutionState, jinja_context: dict[str, Any]):
        """Set step result."""
        from_path = result_config.get("from", "")
        
        if from_path:
            try:
                result_value = self._evaluate_jinja(from_path, jinja_context)
            except Exception as e:
                logger.error(f"Error evaluating result.from: {e}")
                return
        else:
            result_value = self._render_dict(result_config, jinja_context)
        
        state.set_step_result(step.step, result_value)
    
    def _action_next(
        self, 
        next_config: list, 
        state: ExecutionState, 
        jinja_context: dict[str, Any],
        event: Event
    ) -> list[Command]:
        """Generate commands for next step transitions."""
        commands = []
        
        for target in next_config:
            if isinstance(target, str):
                target_step = target
                target_args = None
            elif isinstance(target, dict):
                target_step = target.get("step")
                target_args = target.get("args")
            else:
                continue
            
            if not target_step:
                continue
            
            # Render args
            rendered_args = None
            if target_args:
                rendered_args = self._render_dict(target_args, jinja_context)
            
            # Get target step from playbook
            playbook = self.playbook_repo.get_by_execution(event.execution_id)
            if not playbook:
                continue
            
            next_step = self._get_step(playbook, target_step)
            if not next_step:
                logger.warning(f"Target step {target_step} not found")
                continue
            
            commands.append(self._create_command(
                execution_id=event.execution_id,
                step=next_step.step,
                tool=next_step.tool,
                args=rendered_args or next_step.args
            ))
        
        return commands
    
    def _action_fail(self, fail_config: dict, state: ExecutionState):
        """Mark step/workflow as failed."""
        state.workflow_status = "failed"
        logger.info(f"Workflow {state.execution_id} marked as failed")
    
    def _action_skip(self, skip_config: dict, state: ExecutionState):
        """Mark step as skipped."""
        logger.info(f"Step {state.current_step} marked as skipped")
    
    def _handle_structural_next(self, step: Step, state: ExecutionState, jinja_context: dict[str, Any]) -> list[Command]:
        """Handle structural next transitions."""
        if not step.next:
            return []
        
        commands = []
        next_steps = []
        
        if isinstance(step.next, str):
            next_steps = [step.next]
        elif isinstance(step.next, list):
            next_steps = step.next
        
        for next_item in next_steps:
            if isinstance(next_item, str):
                target_step = next_item
            elif isinstance(next_item, dict):
                target_step = next_item.get("step")
            else:
                continue
            
            if not target_step:
                continue
            
            # Get target step from playbook
            playbook = self.playbook_repo.get_by_execution(state.execution_id)
            if not playbook:
                continue
            
            next_step_obj = self._get_step(playbook, target_step)
            if not next_step_obj:
                continue
            
            commands.append(self._create_command(
                execution_id=state.execution_id,
                step=next_step_obj.step,
                tool=next_step_obj.tool,
                args=next_step_obj.args
            ))
        
        return commands
    
    def _create_command(
        self,
        execution_id: str,
        step: str,
        tool: ToolSpec,
        args: Optional[dict[str, Any]] = None,
        attempt: int = 1,
        priority: int = 0,
        backoff: Optional[float] = None,
        max_attempts: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None
    ) -> Command:
        """Create Command object."""
        tool_call = ToolCall(
            kind=tool.kind,
            config=tool.model_dump(exclude={"kind"}, by_alias=True)
        )
        
        return Command(
            execution_id=execution_id,
            step=step,
            tool=tool_call,
            args=args,
            attempt=attempt,
            priority=priority,
            backoff=backoff,
            max_attempts=max_attempts,
            metadata=metadata or {}
        )
    
    def _get_step(self, playbook: Playbook, step_name: str) -> Optional[Step]:
        """Get step by name from playbook."""
        for step in playbook.workflow:
            if step.step == step_name:
                return step
        return None
    
    def _evaluate_jinja(self, template_str: str, context: dict[str, Any]) -> Any:
        """Evaluate Jinja2 template expression."""
        try:
            template = self.jinja_env.from_string("{{ " + template_str + " }}")
            result = template.render(context)
            
            # Try to evaluate as Python literal
            import ast
            try:
                return ast.literal_eval(result)
            except (ValueError, SyntaxError):
                return result
        except (TemplateSyntaxError, UndefinedError) as e:
            logger.error(f"Jinja evaluation error: {e}")
            raise
    
    def _render_dict(self, data: dict, context: dict[str, Any]) -> dict[str, Any]:
        """Recursively render all string values in dict with Jinja2."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                try:
                    template = self.jinja_env.from_string(value)
                    result[key] = template.render(context)
                except (TemplateSyntaxError, UndefinedError):
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._render_dict(value, context)
            elif isinstance(value, list):
                result[key] = [
                    self._render_dict(item, context) if isinstance(item, dict)
                    else template.render(context) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
