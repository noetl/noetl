"""
Task sequence executor for NoETL worker.

Executes labeled tasks in then: blocks with tool-level eval: flow control.

Features:
- Sequential task execution within a single worker
- Data threading via _prev (like Clojure's ->)
- Per-task flow control via tool.eval:
- Control actions: continue, retry, break, jump, fail
- Tracks _task, _prev, _attempt, outcome for template access

Usage in playbooks:
    case:
      - when: "{{ event.name == 'call.done' }}"
        then:
          - fetch:
              tool:
                kind: http
                url: "..."
                eval:
                  - expr: "{{ outcome.error.retryable }}"
                    do: retry
                    attempts: 5
                    backoff: exponential
                    delay: 1.0
                  - expr: "{{ outcome.status == 'error' }}"
                    do: fail
                  - else:
                      do: continue
          - transform:
              tool:
                kind: python
                args: {data: "{{ _prev }}"}
                code: "..."
          - next:
              - step: continue
"""

import asyncio
import time
from typing import Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from noetl.core.errors import ErrorInfo, classify_error
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


@dataclass
class TaskSequenceContext:
    """
    Runtime context for task sequence execution.

    Variable scoping:
    - _prev: pipeline-local, only valid during then: list execution
    - _task: current task name (pipeline-local)
    - _attempt: retry attempt for current task (pipeline-local)
    - outcome: current task execution result (pipeline-local)
    - results: all task results by name (pipeline-local)
    - step_vars: step-scoped mutable state (visible to subsequent tools and case evaluation)
    - iter_vars: iteration-scoped vars (isolated per parallel loop iteration)
    """
    _task: str = ""
    _prev: Any = None
    _attempt: int = 1
    outcome: Optional[dict[str, Any]] = None
    results: dict[str, Any] = field(default_factory=dict)
    step_vars: dict[str, Any] = field(default_factory=dict)
    iter_vars: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for template rendering."""
        return {
            "_task": self._task,
            "_prev": self._prev,
            "_attempt": self._attempt,
            "outcome": self.outcome,
            "results": self.results,
            "vars": self.step_vars,  # Expose step vars as 'vars' for templates
            "iter": self.iter_vars,  # Expose iteration vars as 'iter' for templates
        }

    def update_success(self, task_name: str, result: Any, outcome: dict[str, Any]):
        """Update context after successful task."""
        self._prev = result
        self._task = task_name
        self.outcome = outcome
        self.results[task_name] = result

    def update_error(self, task_name: str, outcome: dict[str, Any]):
        """Update context after failed task."""
        self._task = task_name
        self.outcome = outcome

    def set_step_vars(self, vars_dict: dict[str, Any]):
        """Update step-scoped variables."""
        self.step_vars.update(vars_dict)

    def set_iter_vars(self, vars_dict: dict[str, Any]):
        """Update iteration-scoped variables (for parallel loops)."""
        self.iter_vars.update(vars_dict)


@dataclass
class ControlAction:
    """Result of eval condition evaluation."""
    action: str  # continue, retry, break, jump, fail
    to: Optional[str] = None  # For jump: target task label
    attempts: int = 3  # Max retry attempts
    backoff: str = "none"  # none, linear, exponential
    delay: float = 1.0  # Initial delay seconds
    set_vars: Optional[dict[str, Any]] = None  # Step-scoped vars to set
    set_iter: Optional[dict[str, Any]] = None  # Iteration-scoped vars to set


def build_outcome(
    status: str,
    result: Any = None,
    error: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, Any]] = None,
    tool_kind: str = "unknown",
    duration_ms: int = 0,
    attempt: int = 1,
) -> dict[str, Any]:
    """
    Build a structured outcome object for eval expressions.

    Args:
        status: "success" or "error"
        result: Tool output (if success)
        error: Structured error dict (if error)
        meta: Additional metadata
        tool_kind: Tool type for tool-specific helpers
        duration_ms: Execution duration
        attempt: Current attempt number

    Returns:
        Outcome dict with status, result/error, meta, and tool-specific helpers
    """
    outcome = {
        "status": status,
        "meta": {
            "attempt": attempt,
            "duration_ms": duration_ms,
            **(meta or {}),
        },
    }

    if status == "success":
        outcome["result"] = result
    else:
        outcome["error"] = error or {"kind": "unknown", "retryable": False, "message": "Unknown error"}

    # Add tool-specific helpers
    if tool_kind == "http" and isinstance(result, dict):
        outcome["http"] = {
            "status": result.get("status_code") or result.get("status"),
            "headers": result.get("headers", {}),
        }
        if error:
            outcome["http"]["status"] = error.get("status_code") or error.get("code")
    elif tool_kind == "postgres":
        outcome["pg"] = {}
        if error:
            outcome["pg"]["code"] = error.get("code")
            outcome["pg"]["sqlstate"] = error.get("sqlstate")
    elif tool_kind == "python":
        outcome["py"] = {}
        if error:
            outcome["py"]["exception"] = error.get("exception")
            outcome["py"]["traceback"] = error.get("traceback")

    return outcome


class TaskSequenceExecutor:
    """
    Executes a task sequence within a single worker.

    Tasks are labeled items in a then: block, with tool-level eval:
    for flow control. The sequence is treated as an atomic unit.
    """

    def __init__(
        self,
        tool_executor: Callable[[str, dict, dict], Awaitable[Any]],
        render_template: Callable[[str, dict], str],
        render_dict: Callable[[dict, dict], dict],
    ):
        """
        Initialize task sequence executor.

        Args:
            tool_executor: Async function to execute a tool: (kind, config, context) -> result
            render_template: Function to render Jinja2 templates
            render_dict: Function to render all templates in a dict
        """
        self.tool_executor = tool_executor
        self.render_template = render_template
        self.render_dict = render_dict

    async def execute(
        self,
        tasks: list[dict[str, Any]],
        base_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute a task sequence.

        Args:
            tasks: List of labeled task definitions:
                [
                    {"fetch": {"tool": {"kind": "http", "url": "...", "eval": [...]}}},
                    {"transform": {"tool": {"kind": "python", ...}}},
                    ...
                ]
            base_context: Base render context (workload, vars, step results)

        Returns:
            Sequence result:
                {
                    "status": "success" | "failed" | "break",
                    "_prev": final _prev value,
                    "results": {task_name: result, ...},
                    "error": {...} if failed,
                    "remaining_actions": [...] if break
                }
        """
        if not tasks:
            logger.warning("[TASK_SEQ] Empty task sequence - no tasks to execute")
            return {"status": "success", "_prev": None, "results": {}}

        # Parse task list
        parsed_tasks = self._parse_tasks(tasks)
        task_names = [t["name"] for t in parsed_tasks]
        logger.info(f"[TASK_SEQ] Executing {len(parsed_tasks)} tasks: {task_names}")

        # Initialize context
        ctx = TaskSequenceContext()
        retry_counts: dict[str, int] = {}  # task_name -> attempt count

        # Execute tasks
        current_idx = 0
        while current_idx < len(parsed_tasks):
            task = parsed_tasks[current_idx]
            task_name = task["name"]
            tool_spec = task["tool"]
            eval_conditions = task.get("eval", [])

            ctx._task = task_name
            ctx._attempt = retry_counts.get(task_name, 0) + 1

            # Build context for template rendering
            render_ctx = {
                **base_context,
                **ctx.to_dict(),
            }

            # Execute tool and build outcome
            start_time = time.monotonic()
            try:
                # Render tool config with current context
                tool_kind = tool_spec.get("kind")
                tool_config = {k: v for k, v in tool_spec.items() if k not in ("kind", "eval", "output")}
                rendered_config = self.render_dict(tool_config, render_ctx)

                logger.info(f"[TASK_SEQ] Executing task '{task_name}' (kind={tool_kind}, attempt={ctx._attempt})")

                # Execute tool
                result = await self.tool_executor(tool_kind, rendered_config, render_ctx)
                duration_ms = int((time.monotonic() - start_time) * 1000)

                # Check for error in result
                if isinstance(result, dict) and result.get("status") == "error":
                    error_info = {
                        "kind": result.get("error_kind", "tool_error"),
                        "retryable": result.get("retryable", False),
                        "code": result.get("code"),
                        "message": result.get("error") or result.get("message", "Tool returned error status"),
                    }
                    outcome = build_outcome(
                        status="error",
                        error=error_info,
                        tool_kind=tool_kind,
                        duration_ms=duration_ms,
                        attempt=ctx._attempt,
                    )
                    ctx.update_error(task_name, outcome)
                else:
                    # Success
                    outcome = build_outcome(
                        status="success",
                        result=result,
                        tool_kind=tool_kind,
                        duration_ms=duration_ms,
                        attempt=ctx._attempt,
                    )
                    ctx.update_success(task_name, result, outcome)
                    logger.info(f"[TASK_SEQ] Task '{task_name}' completed successfully")

            except Exception as e:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                # Task failed - classify error
                error_info = self._classify_task_error(e, task_name, tool_spec.get("kind", "unknown"))
                outcome = build_outcome(
                    status="error",
                    error=error_info.to_dict(),
                    tool_kind=tool_spec.get("kind", "unknown"),
                    duration_ms=duration_ms,
                    attempt=ctx._attempt,
                )
                ctx.update_error(task_name, outcome)
                logger.warning(f"[TASK_SEQ] Task '{task_name}' failed: {error_info.message}")

            # Evaluate tool.eval conditions
            eval_ctx = {**render_ctx, **ctx.to_dict()}
            action = self._evaluate_eval(eval_conditions, eval_ctx, ctx.outcome)

            # Apply set_vars and set_iter from the matched eval condition
            if action.set_vars:
                # Render the vars values with current context
                rendered_vars = {}
                for key, value in action.set_vars.items():
                    if isinstance(value, str) and "{{" in value:
                        try:
                            rendered_vars[key] = self.render_template(value, eval_ctx)
                        except Exception as e:
                            logger.warning(f"[TASK_SEQ] Error rendering set_vars.{key}: {e}")
                            rendered_vars[key] = value
                    else:
                        rendered_vars[key] = value
                ctx.set_step_vars(rendered_vars)
                logger.debug(f"[TASK_SEQ] Set step vars: {list(rendered_vars.keys())}")

            if action.set_iter:
                # Render the iter vars values with current context
                rendered_iter = {}
                for key, value in action.set_iter.items():
                    if isinstance(value, str) and "{{" in value:
                        try:
                            rendered_iter[key] = self.render_template(value, eval_ctx)
                        except Exception as e:
                            logger.warning(f"[TASK_SEQ] Error rendering set_iter.{key}: {e}")
                            rendered_iter[key] = value
                    else:
                        rendered_iter[key] = value
                ctx.set_iter_vars(rendered_iter)
                logger.debug(f"[TASK_SEQ] Set iter vars: {list(rendered_iter.keys())}")

            # Apply control action
            if action.action == "continue":
                if ctx.outcome["status"] == "success":
                    current_idx += 1
                else:
                    # Error but continue anyway
                    logger.info(f"[TASK_SEQ] Continuing after error in task '{task_name}'")
                    current_idx += 1

            elif action.action == "retry":
                retry_counts[task_name] = retry_counts.get(task_name, 0) + 1

                if retry_counts[task_name] >= action.attempts:
                    logger.error(f"[TASK_SEQ] Task '{task_name}' exceeded max attempts ({action.attempts})")
                    return {
                        "status": "failed",
                        "_prev": ctx._prev,
                        "results": ctx.results,
                        "step_vars": ctx.step_vars,
                        "error": ctx.outcome.get("error") if ctx.outcome else None,
                        "failed_task": task_name,
                    }

                # Apply backoff delay
                delay = self._calculate_delay(action, retry_counts[task_name])
                if delay > 0:
                    logger.info(f"[TASK_SEQ] Waiting {delay:.2f}s before retry (backoff={action.backoff})")
                    await asyncio.sleep(delay)

                logger.info(f"[TASK_SEQ] Retrying task '{task_name}' (attempt {retry_counts[task_name] + 1}/{action.attempts})")
                # Stay at current_idx to retry

            elif action.action == "jump":
                target = action.to
                if not target:
                    logger.error("[TASK_SEQ] Jump action missing 'to' target")
                    return {
                        "status": "failed",
                        "_prev": ctx._prev,
                        "results": ctx.results,
                        "step_vars": ctx.step_vars,
                        "error": {"kind": "config", "message": "Jump action missing 'to' target"},
                        "failed_task": task_name,
                    }

                target_idx = next((i for i, t in enumerate(parsed_tasks) if t["name"] == target), None)
                if target_idx is None:
                    logger.error(f"[TASK_SEQ] Jump target '{target}' not found in task sequence")
                    return {
                        "status": "failed",
                        "_prev": ctx._prev,
                        "results": ctx.results,
                        "step_vars": ctx.step_vars,
                        "error": {"kind": "config", "message": f"Jump target '{target}' not found"},
                        "failed_task": task_name,
                    }

                logger.info(f"[TASK_SEQ] Jumping to task '{target}'")
                current_idx = target_idx

            elif action.action == "break":
                # Stop task sequence, return remaining actions for step-level processing
                remaining = tasks[current_idx + 1:] if current_idx + 1 < len(tasks) else []
                logger.info(f"[TASK_SEQ] Breaking from task sequence at '{task_name}'")
                return {
                    "status": "break",
                    "_prev": ctx._prev,
                    "results": ctx.results,
                    "step_vars": ctx.step_vars,
                    "remaining_actions": remaining,
                }

            else:  # fail
                logger.error(f"[TASK_SEQ] Task sequence failed at task '{task_name}'")
                return {
                    "status": "failed",
                    "_prev": ctx._prev,
                    "results": ctx.results,
                    "step_vars": ctx.step_vars,
                    "error": ctx.outcome.get("error") if ctx.outcome else None,
                    "failed_task": task_name,
                }

        # All tasks completed successfully
        logger.info(f"[TASK_SEQ] Task sequence completed successfully, {len(ctx.results)} tasks executed")
        return {
            "status": "success",
            "_prev": ctx._prev,
            "results": ctx.results,
            "step_vars": ctx.step_vars,
        }

    def _parse_tasks(self, tasks: list[dict]) -> list[dict]:
        """Parse task list into task definitions."""
        parsed = []
        for task_def in tasks:
            if not isinstance(task_def, dict):
                continue

            # Skip non-tool actions (next, vars, etc.)
            # Only process labeled tool tasks
            for name, config in task_def.items():
                # Skip reserved action names
                if name in ("next", "vars", "collect", "emit", "set"):
                    continue

                if isinstance(config, dict) and "tool" in config:
                    tool = config["tool"]
                    parsed.append({
                        "name": name,
                        "tool": tool,
                        "eval": tool.get("eval", []) if isinstance(tool, dict) else [],
                    })
        return parsed

    def _classify_task_error(
        self,
        error: Exception,
        task_name: str,
        tool_kind: str,
    ) -> ErrorInfo:
        """Classify a task execution error."""
        context = {}

        # Extract HTTP-specific info
        if isinstance(error, TaskSequenceError):
            if error.context:
                context["status_code"] = error.context.get("status_code")
                context["headers"] = error.context.get("headers")
            return classify_error(error, source=error.source, context=context)

        # Generic classification
        return classify_error(error, source=tool_kind, context=context)

    def _evaluate_eval(
        self,
        eval_conditions: list[dict],
        render_ctx: dict,
        outcome: dict[str, Any],
    ) -> ControlAction:
        """
        Evaluate tool.eval conditions to determine control action.

        Default behavior (if tool.eval is omitted):
        - success → continue
        - error → fail

        If tool.eval is present and no clause matches, same default applies
        unless an else clause is provided.

        Returns first matching condition's action with any set_vars/set_iter.
        """
        # Default behavior when no eval: block is specified
        if not eval_conditions:
            if outcome and outcome.get("status") == "error":
                return ControlAction(action="fail")
            return ControlAction(action="continue")

        for cond in eval_conditions:
            if not isinstance(cond, dict):
                continue

            # Check for else clause: - else: {do: continue, set_vars: {...}}
            if "else" in cond:
                action_spec = cond["else"]
                if isinstance(action_spec, dict):
                    return self._parse_action(action_spec)
                continue

            # Check expr condition
            expr = cond.get("expr")
            if expr is None:
                # No expr means this is a default/else clause with inline action
                return self._parse_action(cond)

            try:
                # Render condition with context including outcome
                rendered = self.render_template(expr, render_ctx)
                # Evaluate as boolean
                if rendered.lower() in ("true", "1", "yes"):
                    return self._parse_action(cond)
            except Exception as e:
                logger.warning(f"[TASK_SEQ] Error evaluating eval condition: {e}")
                continue

        # No clause matched - apply default behavior based on outcome status
        # This is the same as if no eval: block was specified
        if outcome and outcome.get("status") == "error":
            logger.debug("[TASK_SEQ] No eval condition matched for error, defaulting to fail")
            return ControlAction(action="fail")

        logger.debug("[TASK_SEQ] No eval condition matched for success, defaulting to continue")
        return ControlAction(action="continue")

    def _parse_action(self, action_spec: dict) -> ControlAction:
        """Parse eval condition into ControlAction."""
        # Handle delay that might be a template expression (rendered as string)
        delay = action_spec.get("delay", 1.0)
        if isinstance(delay, str):
            try:
                delay = float(delay)
            except ValueError:
                delay = 1.0

        return ControlAction(
            action=action_spec.get("do", "continue"),
            to=action_spec.get("to"),
            attempts=action_spec.get("attempts", 3),
            backoff=action_spec.get("backoff", "none"),
            delay=delay,
            set_vars=action_spec.get("set_vars"),
            set_iter=action_spec.get("set_iter"),
        )

    def _calculate_delay(self, action: ControlAction, attempt: int) -> float:
        """Calculate retry delay based on backoff strategy."""
        if action.backoff == "none":
            return 0
        elif action.backoff == "linear":
            return action.delay * attempt
        elif action.backoff == "exponential":
            return action.delay * (2 ** (attempt - 1))
        return action.delay


class TaskSequenceError(Exception):
    """Error during task sequence execution."""

    def __init__(
        self,
        task_name: str,
        error: str,
        source: str = "unknown",
        context: Optional[dict] = None,
    ):
        self.task_name = task_name
        self.source = source
        self.context = context or {}
        super().__init__(error)


def is_task_sequence(then_block: Any) -> bool:
    """
    Check if a then: block contains labeled tool tasks (task sequence).

    A task sequence is detected when the then: block contains items
    that are labeled tasks with tool: configs (not reserved actions).
    """
    if not isinstance(then_block, list):
        return False

    reserved_actions = {"next", "vars", "collect", "emit", "set", "pipe"}

    for item in then_block:
        if not isinstance(item, dict):
            continue
        # Check if this is a labeled task (not a reserved action)
        for key, value in item.items():
            if key not in reserved_actions and isinstance(value, dict) and "tool" in value:
                return True

    return False


def extract_task_sequence(then_block: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Extract task sequence and remaining actions from then: block.

    Returns:
        (task_list, remaining_actions)
        - task_list: labeled tool tasks to execute
        - remaining_actions: non-task actions (next, vars, etc.) to process after
    """
    tasks = []
    remaining = []
    reserved_actions = {"next", "vars", "collect", "emit", "set"}

    for item in then_block:
        if not isinstance(item, dict):
            continue

        # Check if this is a labeled task or a reserved action
        is_task = False
        for key, value in item.items():
            if key not in reserved_actions and isinstance(value, dict) and "tool" in value:
                tasks.append(item)
                is_task = True
                break

        if not is_task:
            remaining.append(item)

    return tasks, remaining


__all__ = [
    "TaskSequenceExecutor",
    "TaskSequenceContext",
    "TaskSequenceError",
    "ControlAction",
    "build_outcome",
    "is_task_sequence",
    "extract_task_sequence",
]
