"""
NoETL DSL v2 Control Flow Engine - Event-driven orchestration.

Server-side engine that:
1. Receives events from workers
2. Evaluates case/when/then rules
3. Generates commands for queue table
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import BaseLoader, Environment, StrictUndefined

from noetl.core.logger import setup_logger

from .models import (
    ActionCall,
    ActionCollect,
    ActionNext,
    CaseEntry,
    Command,
    Event,
    EventName,
    Playbook,
    Step,
    ThenBlock,
    ToolCall,
)

logger = setup_logger(__name__, include_location=True)


class ExecutionState:
    """Manages state for a single execution."""
    
    def __init__(self, execution_id: str, playbook: Playbook):
        self.execution_id = execution_id
        self.playbook = playbook
        self.current_step: Optional[str] = None
        self.step_results: Dict[str, Any] = {}  # step_name -> result
        self.context: Dict[str, Any] = {}  # User-defined context (ctx, flags, etc.)
        self.loop_state: Dict[str, Any] = {}  # Loop iteration state
        self.step_attempts: Dict[str, int] = {}  # step_name -> attempt count
        self.workflow_status: str = "running"  # running, completed, failed
    
    def get_step(self, step_name: str) -> Optional[Step]:
        """Get step definition by name."""
        for step in self.playbook.workflow:
            if step.step == step_name:
                return step
        return None
    
    def get_step_result(self, step_name: str) -> Any:
        """Get result from a completed step."""
        return self.step_results.get(step_name)
    
    def set_step_result(self, step_name: str, result: Any) -> None:
        """Store result for a step."""
        self.step_results[step_name] = result
    
    def increment_attempt(self, step_name: str) -> int:
        """Increment and return attempt count for a step."""
        current = self.step_attempts.get(step_name, 0)
        new_count = current + 1
        self.step_attempts[step_name] = new_count
        return new_count


class StateStore:
    """Interface for persisting execution state."""
    
    def __init__(self):
        # In-memory store for now; can be replaced with database persistence
        self._states: Dict[str, ExecutionState] = {}
    
    def get_state(self, execution_id: str) -> Optional[ExecutionState]:
        """Retrieve execution state."""
        return self._states.get(execution_id)
    
    def save_state(self, state: ExecutionState) -> None:
        """Persist execution state."""
        self._states[state.execution_id] = state
    
    def delete_state(self, execution_id: str) -> None:
        """Remove execution state."""
        self._states.pop(execution_id, None)


class PlaybookRepo:
    """Repository for playbook lookup."""
    
    def __init__(self):
        self._playbooks: Dict[str, Playbook] = {}
    
    def register(self, playbook: Playbook) -> None:
        """Register a playbook."""
        key = f"{playbook.metadata.path}/{playbook.metadata.name}"
        self._playbooks[key] = playbook
        logger.info(f"Registered playbook: {key}")
    
    def get_by_execution(self, execution_id: str) -> Optional[Playbook]:
        """
        Get playbook for an execution.
        In real implementation, this would query the catalog/execution tables.
        """
        # Placeholder - in production, query from database
        # For now, return first registered playbook if any
        if self._playbooks:
            return next(iter(self._playbooks.values()))
        return None


class ControlFlowEngine:
    """Event-driven control flow engine for NoETL v2."""
    
    def __init__(self, playbook_repo: PlaybookRepo, state_store: StateStore):
        self.playbook_repo = playbook_repo
        self.state_store = state_store
        self._jinja = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self._jinja.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
    
    def handle_event(self, event: Event) -> List[Command]:
        """
        Process an event and generate commands.
        
        Args:
            event: Event from worker or internal system
            
        Returns:
            List of Command objects to insert into queue
        """
        logger.info(
            f"Handling event: execution={event.execution_id}, "
            f"step={event.step}, name={event.name}"
        )
        
        # Get or create execution state
        state = self.state_store.get_state(event.execution_id)
        if not state:
            # New execution - initialize
            playbook = self.playbook_repo.get_by_execution(event.execution_id)
            if not playbook:
                logger.error(f"No playbook found for execution {event.execution_id}")
                return []
            
            state = ExecutionState(event.execution_id, playbook)
            state.current_step = "start"
            self.state_store.save_state(state)
        
        # Handle workflow-level events
        if event.name == EventName.WORKFLOW_START.value:
            return self._handle_workflow_start(state)
        
        if event.name == EventName.WORKFLOW_END.value:
            state.workflow_status = "completed"
            self.state_store.save_state(state)
            return []
        
        # Handle step-level events
        if not event.step:
            logger.warning(f"Event {event.name} has no step specified")
            return []
        
        step = state.get_step(event.step)
        if not step:
            logger.error(f"Step '{event.step}' not found in playbook")
            return []
        
        # Build Jinja context for evaluation
        context = self._build_jinja_context(state, step, event)
        
        # Evaluate case rules
        commands = []
        if step.case:
            for case_entry in step.case:
                if self._evaluate_when(case_entry.when, context):
                    logger.info(
                        f"Case matched for step '{step.step}': {case_entry.when}"
                    )
                    case_commands = self._execute_then(
                        state, step, case_entry.then, context
                    )
                    commands.extend(case_commands)
                    # Stop at first match (can be made configurable)
                    break
        
        # Handle step completion with structural next
        if event.name == EventName.STEP_EXIT.value and not commands:
            # No case-based transition, use structural next
            if step.next:
                next_steps = [step.next] if isinstance(step.next, str) else step.next
                for next_step_name in next_steps:
                    if next_step_name == "end":
                        # Workflow completion
                        state.workflow_status = "completed"
                        self.state_store.save_state(state)
                        continue
                    
                    next_step = state.get_step(next_step_name)
                    if next_step:
                        cmd = self._create_command(
                            state, next_step, args=step.args
                        )
                        commands.append(cmd)
        
        self.state_store.save_state(state)
        return commands
    
    def _handle_workflow_start(self, state: ExecutionState) -> List[Command]:
        """Handle workflow start - create command for 'start' step."""
        start_step = state.get_step("start")
        if not start_step:
            logger.error(f"No 'start' step in workflow")
            return []
        
        # Initialize workload variables
        if state.playbook.workload:
            state.context.update(state.playbook.workload)
        
        cmd = self._create_command(state, start_step)
        return [cmd]
    
    def _build_jinja_context(
        self, state: ExecutionState, step: Step, event: Event
    ) -> Dict[str, Any]:
        """Build Jinja context for template evaluation."""
        context: Dict[str, Any] = {
            "event": {
                "name": event.name,
                "payload": event.payload,
            },
            "execution_id": state.execution_id,
            "workload": state.playbook.workload or {},
            "args": step.args or {},
            "ctx": state.context,
            "loop": state.loop_state,
        }
        
        # Add previous step results
        for step_name, result in state.step_results.items():
            # Normalize by extracting .data if present (server-side normalization)
            if isinstance(result, dict) and "data" in result:
                context[step_name] = result["data"]
            else:
                context[step_name] = result
        
        # Extract response/error from event payload for call.done
        if event.name == EventName.CALL_DONE.value:
            payload = event.payload
            if "response" in payload:
                context["response"] = payload["response"]
            if "error" in payload:
                context["error"] = payload["error"]
            if "result" in payload:
                context["result"] = payload["result"]
        
        return context
    
    def _evaluate_when(self, when_expr: str, context: Dict[str, Any]) -> bool:
        """Evaluate a when condition using Jinja2."""
        try:
            # Wrap in {% if %} to convert to boolean
            template_str = f"{{% if {when_expr} %}}true{{% else %}}false{{% endif %}}"
            template = self._jinja.from_string(template_str)
            result = template.render(**context).strip()
            return result == "true"
        except Exception as e:
            logger.error(f"Error evaluating condition '{when_expr}': {e}")
            return False
    
    def _execute_then(
        self,
        state: ExecutionState,
        step: Step,
        then: ThenBlock,
        context: Dict[str, Any],
    ) -> List[Command]:
        """Execute actions in a then block."""
        commands: List[Command] = []
        
        # Handle set action
        if then.set:
            if then.set.ctx:
                state.context.update(then.set.ctx)
            if then.set.flags:
                state.context.setdefault("flags", {}).update(then.set.flags)
        
        # Handle collect action
        if then.collect:
            self._handle_collect(state, then.collect, context)
        
        # Handle result action
        if then.result:
            result_value = self._render_template(then.result.from_, context)
            state.set_step_result(step.step, result_value)
        
        # Handle call action (re-invoke)
        if then.call:
            cmd = self._create_command_with_overrides(state, step, then.call, context)
            commands.append(cmd)
        
        # Handle retry action
        if then.retry:
            attempt = state.increment_attempt(step.step)
            if attempt <= then.retry.max_attempts:
                # Calculate backoff delay
                delay = then.retry.initial_delay * (then.retry.backoff_multiplier ** (attempt - 1))
                logger.info(f"Retrying step '{step.step}' (attempt {attempt}) with delay {delay}s")
                
                cmd = self._create_command(state, step, attempt=attempt)
                commands.append(cmd)
            else:
                logger.warning(f"Max retry attempts reached for step '{step.step}'")
        
        # Handle sink action
        if then.sink:
            cmd = self._create_sink_command(state, step, then.sink, context)
            if cmd:
                commands.append(cmd)
        
        # Handle next action (conditional transitions)
        if then.next:
            for action_next in then.next:
                next_step = state.get_step(action_next.step)
                if next_step:
                    # Render args
                    rendered_args = self._render_dict(action_next.args or {}, context)
                    cmd = self._create_command(state, next_step, args=rendered_args)
                    commands.append(cmd)
        
        # Handle fail action
        if then.fail:
            logger.error(f"Step '{step.step}' failed: {then.fail.message}")
            if then.fail.fail_workflow:
                state.workflow_status = "failed"
        
        # Handle skip action
        if then.skip:
            logger.info(f"Step '{step.step}' skipped: {then.skip.reason}")
        
        return commands
    
    def _handle_collect(
        self, state: ExecutionState, collect: ActionCollect, context: Dict[str, Any]
    ) -> None:
        """Handle collect action - aggregate data into context."""
        # Extract source data
        source_value = self._render_template(collect.from_, context)
        
        # Get or create target collection
        target = state.context.setdefault(collect.into, [])
        
        # Apply collection mode
        if collect.mode == "append":
            if isinstance(target, list):
                target.append(source_value)
            else:
                logger.warning(f"Cannot append to non-list target '{collect.into}'")
        elif collect.mode == "extend":
            if isinstance(target, list) and isinstance(source_value, list):
                target.extend(source_value)
            else:
                logger.warning(f"Cannot extend non-list target or source")
        elif collect.mode == "replace":
            state.context[collect.into] = source_value
        
        logger.debug(f"Collected data into '{collect.into}' (mode={collect.mode})")
    
    def _create_command(
        self,
        state: ExecutionState,
        step: Step,
        args: Optional[Dict[str, Any]] = None,
        attempt: int = 1,
    ) -> Command:
        """Create a command for a step."""
        # Build tool call from step.tool
        tool_call = ToolCall(
            kind=step.tool.kind,
            config=step.tool.model_dump(exclude={"kind"}, exclude_none=True),
        )
        
        return Command(
            execution_id=state.execution_id,
            step=step.step,
            tool=tool_call,
            args=args or step.args,
            context={"loop": state.loop_state} if state.loop_state else None,
            attempt=attempt,
        )
    
    def _create_command_with_overrides(
        self,
        state: ExecutionState,
        step: Step,
        call: ActionCall,
        context: Dict[str, Any],
    ) -> Command:
        """Create command with call overrides."""
        # Start with base tool config
        config = step.tool.model_dump(exclude={"kind"}, exclude_none=True)
        
        # Apply overrides
        overrides = call.model_dump(exclude_none=True)
        for key, value in overrides.items():
            # Render template values
            if isinstance(value, str):
                config[key] = self._render_template(value, context)
            else:
                config[key] = value
        
        tool_call = ToolCall(kind=step.tool.kind, config=config)
        
        attempt = state.step_attempts.get(step.step, 0) + 1
        state.step_attempts[step.step] = attempt
        
        return Command(
            execution_id=state.execution_id,
            step=step.step,
            tool=tool_call,
            args=step.args,
            context={"loop": state.loop_state} if state.loop_state else None,
            attempt=attempt,
        )
    
    def _create_sink_command(
        self,
        state: ExecutionState,
        step: Step,
        sink: Any,
        context: Dict[str, Any],
    ) -> Optional[Command]:
        """Create a command for sink operation."""
        # Extract tool config
        tool_config = sink.tool if hasattr(sink, "tool") else sink
        if not isinstance(tool_config, dict) or "kind" not in tool_config:
            logger.error("Invalid sink configuration")
            return None
        
        tool_call = ToolCall(
            kind=tool_config["kind"],
            config={k: v for k, v in tool_config.items() if k != "kind"},
        )
        
        return Command(
            execution_id=state.execution_id,
            step=f"{step.step}_sink",
            tool=tool_call,
            args=sink.args if hasattr(sink, "args") else None,
        )
    
    def _render_template(self, template_str: str, context: Dict[str, Any]) -> Any:
        """Render a Jinja2 template string."""
        try:
            template = self._jinja.from_string(template_str)
            result = template.render(**context)
            # Try to parse as JSON if it looks like structured data
            if result.startswith("{") or result.startswith("["):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    pass
            return result
        except Exception as e:
            logger.error(f"Error rendering template '{template_str}': {e}")
            return template_str
    
    def _render_dict(
        self, data: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Recursively render templates in a dictionary."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._render_template(value, context)
            elif isinstance(value, dict):
                result[key] = self._render_dict(value, context)
            elif isinstance(value, list):
                result[key] = [
                    self._render_template(v, context) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                result[key] = value
        return result
