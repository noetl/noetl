"""
Task sequence executor for NoETL worker - Canonical v10 Format (Strict).

Executes labeled tasks in tool pipelines with task.spec.policy for flow control.

Features:
- Sequential task execution within a single worker
- Data threading via _prev (like Clojure's ->)
- Per-task flow control via task.spec.policy.rules (canonical v10 ONLY)
- Control actions: continue, retry, break, jump, fail
- Tracks _task, _prev, _attempt, outcome for template access
- Uses `when` as the ONLY conditional keyword (rejects `expr`)
- Outcome status uses "ok" | "error" (rejects "success")
- Variable mutations via set_ctx/set_iter (rejects set_vars)

NO BACKWARD COMPATIBILITY - v10 patterns only.

Canonical v10 usage in playbooks:
    - step: fetch_and_transform
      tool:
        - fetch:
            kind: http
            url: "..."
            spec:
              policy:
                rules:
                  - when: "{{ outcome.status == 'error' and outcome.error.retryable }}"
                    then: { do: retry, attempts: 5, backoff: exponential, delay: 1.0 }
                  - when: "{{ outcome.status == 'error' }}"
                    then: { do: fail }
                  - else:
                      then: { do: continue }
        - transform:
            kind: python
            args: { data: "{{ _prev }}" }
            code: "..."
      next:
        arcs:
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
    Runtime context for task sequence execution (canonical v10 - strict).

    Variable scoping:
    - _prev: pipeline-local, only valid during tool pipeline execution
    - _task: current task name (pipeline-local)
    - _attempt: retry attempt for current task (pipeline-local)
    - outcome: current task execution result (pipeline-local)
    - results: all task results by name (pipeline-local)
    - ctx: execution-scoped mutable state (canonical v10)
    - iter: iteration-scoped vars (canonical v10, isolated per parallel loop iteration)
    """
    _task: str = ""
    _prev: Any = None
    _attempt: int = 1
    outcome: Optional[dict[str, Any]] = None
    results: dict[str, Any] = field(default_factory=dict)
    ctx: dict[str, Any] = field(default_factory=dict)
    iter: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for template rendering."""
        return {
            "_task": self._task,
            "_prev": self._prev,
            "_attempt": self._attempt,
            "outcome": self.outcome,
            "results": self.results,
            "ctx": self.ctx,
            "iter": self.iter,
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

    def set_ctx_vars(self, vars_dict: dict[str, Any]):
        """Update execution-scoped context (canonical v10: set_ctx)."""
        self.ctx.update(vars_dict)

    def set_iter_vars(self, vars_dict: dict[str, Any]):
        """Update iteration-scoped variables (canonical v10: set_iter)."""
        self.iter.update(vars_dict)


@dataclass
class ControlAction:
    """Result of policy rule evaluation (canonical v10)."""
    action: str  # continue, retry, break, jump, fail
    to: Optional[str] = None  # For jump: target task label
    attempts: int = 3  # Max retry attempts
    backoff: str = "none"  # none, linear, exponential
    delay: float = 1.0  # Initial delay seconds
    set_ctx: Optional[dict[str, Any]] = None  # Execution-scoped vars
    set_iter: Optional[dict[str, Any]] = None  # Iteration-scoped vars


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
    Build a structured outcome object for policy rule expressions.

    Args:
        status: "ok" or "error" (canonical v10 - "success" is REJECTED)
        result: Tool output (if ok)
        error: Structured error dict (if error)
        meta: Additional metadata
        tool_kind: Tool type for tool-specific helpers
        duration_ms: Execution duration
        attempt: Current attempt number

    Returns:
        Outcome dict with status, result/error, meta, and tool-specific helpers

    Raises:
        ValueError: If status is "success" (must use "ok" in v10)
    """
    # STRICT v10: Reject "success" - must use "ok"
    if status == "success":
        raise ValueError("Canonical v10 requires status='ok', not 'success'")

    if status not in ("ok", "error"):
        raise ValueError(f"Invalid outcome status: {status}. Must be 'ok' or 'error'")

    outcome = {
        "status": status,
        "meta": {
            "attempt": attempt,
            "duration_ms": duration_ms,
            **(meta or {}),
        },
    }

    if status == "ok":
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
    Executes a task sequence within a single worker (canonical v10 - strict).

    Tasks are labeled items in a tool pipeline, with task.spec.policy.rules
    for flow control. The sequence is treated as an atomic unit.

    NO BACKWARD COMPATIBILITY - rejects eval, expr, set_vars.
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
        Execute a task sequence (canonical v10 - strict).

        Args:
            tasks: List of labeled task definitions (canonical v10 format ONLY):
                [
                    {"fetch": {"kind": "http", "url": "...", "spec": {"policy": {"rules": [...]}}}},
                    {"transform": {"kind": "python", ...}},
                    ...
                ]
            base_context: Base render context (workload, ctx, iter, step results)

        Returns:
            Sequence result:
                {
                    "status": "ok" | "failed" | "break",
                    "_prev": final _prev value,
                    "results": {task_name: result, ...},
                    "error": {...} if failed,
                    "remaining_actions": [...] if break
                }
        """
        if not tasks:
            logger.warning("[TASK_SEQ] Empty task sequence - no tasks to execute")
            return {"status": "ok", "_prev": None, "results": {}}

        # Parse task list (strict v10)
        parsed_tasks = self._parse_tasks(tasks)
        task_names = [t["name"] for t in parsed_tasks]
        logger.info(f"[TASK_SEQ] Executing {len(parsed_tasks)} tasks: {task_names}")

        # Initialize context
        ctx = TaskSequenceContext()
        retry_counts: dict[str, int] = {}

        # Initialize iter namespace with values from base_context (loop iterator, etc.)
        # This preserves {{ iter.item }} access within the task sequence
        if isinstance(base_context.get("iter"), dict):
            ctx.iter.update(base_context["iter"])
            logger.debug(f"[TASK_SEQ] Initialized iter from base_context: {list(ctx.iter.keys())}")

        # Execute tasks
        current_idx = 0
        while current_idx < len(parsed_tasks):
            task = parsed_tasks[current_idx]
            task_name = task["name"]
            tool_config = task["config"]
            policy_rules = task.get("policy_rules", [])

            ctx._task = task_name
            ctx._attempt = retry_counts.get(task_name, 0) + 1

            # Build context for template rendering
            # Spread task results at top level so {{ task_name }} works (not just {{ results.task_name }})
            # IMPORTANT: Merge ctx dicts properly instead of overriding
            # base_context["ctx"] contains execution variables (current_endpoint, etc.)
            # ctx.ctx contains task sequence mutations (from set_ctx in policy rules)
            # We need both available for template rendering
            task_seq_dict = ctx.to_dict()
            merged_ctx = {**base_context.get("ctx", {}), **task_seq_dict.get("ctx", {})}
            merged_iter = {**base_context.get("iter", {}), **task_seq_dict.get("iter", {})}

            render_ctx = {
                **base_context,
                **ctx.results,  # Task results at root level: {{ amadeus_search }}
                **task_seq_dict,  # Pipeline-local vars: _prev, _task, _attempt, outcome, results
                "ctx": merged_ctx,  # Merged execution ctx + task sequence ctx
                "iter": merged_iter,  # Merged iteration vars
            }

            # Debug: Log context keys for troubleshooting
            logger.info(f"[TASK_SEQ] Task '{task_name}': base_context ctx keys={list(base_context.get('ctx', {}).keys())}, task_seq ctx keys={list(task_seq_dict.get('ctx', {}).keys())}, merged_ctx keys={list(merged_ctx.keys())}")
            logger.info(f"[TASK_SEQ] Task '{task_name}': base_context iter keys={list(base_context.get('iter', {}).keys())}, task_seq iter keys={list(task_seq_dict.get('iter', {}).keys())}, merged_iter keys={list(merged_iter.keys())}")

            # Execute tool and build outcome
            start_time = time.monotonic()
            try:
                tool_kind = tool_config.get("kind")
                config_to_render = {k: v for k, v in tool_config.items() if k not in ("kind", "spec", "output")}
                rendered_config = self.render_dict(config_to_render, render_ctx)

                # Debug: Log rendered command for postgres tasks
                if tool_kind == "postgres" and "command" in rendered_config:
                    logger.info(f"[TASK_SEQ] Task '{task_name}' rendered command: {rendered_config.get('command', '')[:200]}")
                logger.info(f"[TASK_SEQ] Executing task '{task_name}' (kind={tool_kind}, attempt={ctx._attempt})")

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
                    outcome = build_outcome(
                        status="ok",
                        result=result,
                        tool_kind=tool_kind,
                        duration_ms=duration_ms,
                        attempt=ctx._attempt,
                    )
                    ctx.update_success(task_name, result, outcome)
                    logger.info(f"[TASK_SEQ] Task '{task_name}' completed successfully")

            except Exception as e:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                error_info = self._classify_task_error(e, task_name, tool_config.get("kind", "unknown"))
                outcome = build_outcome(
                    status="error",
                    error=error_info.to_dict(),
                    tool_kind=tool_config.get("kind", "unknown"),
                    duration_ms=duration_ms,
                    attempt=ctx._attempt,
                )
                ctx.update_error(task_name, outcome)
                logger.warning(f"[TASK_SEQ] Task '{task_name}' failed: {error_info.message}")

            # Evaluate policy rules (strict v10)
            # Update render_ctx with latest task sequence state (outcome, _prev, etc.)
            # but preserve the merged ctx/iter from render_ctx
            latest_task_dict = ctx.to_dict()
            eval_ctx = {
                **render_ctx,
                "_task": latest_task_dict["_task"],
                "_prev": latest_task_dict["_prev"],
                "_attempt": latest_task_dict["_attempt"],
                "outcome": latest_task_dict["outcome"],
                "results": latest_task_dict["results"],
                # Keep merged ctx and iter from render_ctx (don't override with empty task seq ctx)
            }
            action = self._evaluate_policy_rules(policy_rules, eval_ctx, ctx.outcome)

            # Apply set_ctx
            if action.set_ctx:
                rendered_ctx = {}
                for key, value in action.set_ctx.items():
                    if isinstance(value, str) and "{{" in value:
                        try:
                            rendered_ctx[key] = self.render_template(value, eval_ctx)
                        except Exception as e:
                            logger.warning(f"[TASK_SEQ] Error rendering set_ctx.{key}: {e}")
                            rendered_ctx[key] = value
                    else:
                        rendered_ctx[key] = value
                ctx.set_ctx_vars(rendered_ctx)
                logger.debug(f"[TASK_SEQ] Set ctx vars: {list(rendered_ctx.keys())}")

            # Apply set_iter
            if action.set_iter:
                rendered_iter = {}
                for key, value in action.set_iter.items():
                    if isinstance(value, str) and "{{" in value:
                        try:
                            rendered_iter[key] = self.render_template(value, eval_ctx)
                            logger.info(f"[TASK_SEQ] Rendered set_iter.{key}: {type(rendered_iter[key]).__name__}")
                        except Exception as e:
                            logger.warning(f"[TASK_SEQ] Error rendering set_iter.{key}: {e}")
                            rendered_iter[key] = value
                    else:
                        rendered_iter[key] = value
                ctx.set_iter_vars(rendered_iter)
                logger.info(f"[TASK_SEQ] Applied set_iter: {list(rendered_iter.keys())}, ctx.iter now has: {list(ctx.iter.keys())}")

            # Apply control action
            if action.action == "continue":
                current_idx += 1

            elif action.action == "retry":
                retry_counts[task_name] = retry_counts.get(task_name, 0) + 1

                if retry_counts[task_name] >= action.attempts:
                    logger.error(f"[TASK_SEQ] Task '{task_name}' exceeded max attempts ({action.attempts})")
                    return {
                        "status": "failed",
                        "_prev": ctx._prev,
                        "results": ctx.results,
                        "ctx": ctx.ctx,
                        "error": ctx.outcome.get("error") if ctx.outcome else None,
                        "failed_task": task_name,
                    }

                delay = self._calculate_delay(action, retry_counts[task_name])
                if delay > 0:
                    logger.info(f"[TASK_SEQ] Waiting {delay:.2f}s before retry (backoff={action.backoff})")
                    await asyncio.sleep(delay)

                logger.info(f"[TASK_SEQ] Retrying task '{task_name}' (attempt {retry_counts[task_name] + 1}/{action.attempts})")

            elif action.action == "jump":
                target = action.to
                if not target:
                    logger.error("[TASK_SEQ] Jump action missing 'to' target")
                    return {
                        "status": "failed",
                        "_prev": ctx._prev,
                        "results": ctx.results,
                        "ctx": ctx.ctx,
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
                        "ctx": ctx.ctx,
                        "error": {"kind": "config", "message": f"Jump target '{target}' not found"},
                        "failed_task": task_name,
                    }

                logger.info(f"[TASK_SEQ] Jumping to task '{target}'")
                current_idx = target_idx

            elif action.action == "break":
                remaining = tasks[current_idx + 1:] if current_idx + 1 < len(tasks) else []
                logger.info(f"[TASK_SEQ] Breaking from task sequence at '{task_name}'")
                return {
                    "status": "break",
                    "_prev": ctx._prev,
                    "results": ctx.results,
                    "ctx": ctx.ctx,
                    "remaining_actions": remaining,
                }

            else:  # fail
                logger.error(f"[TASK_SEQ] Task sequence failed at task '{task_name}'")
                return {
                    "status": "failed",
                    "_prev": ctx._prev,
                    "results": ctx.results,
                    "ctx": ctx.ctx,
                    "error": ctx.outcome.get("error") if ctx.outcome else None,
                    "failed_task": task_name,
                }

        logger.info(f"[TASK_SEQ] Task sequence completed successfully, {len(ctx.results)} tasks executed")
        return {
            "status": "ok",
            "_prev": ctx._prev,
            "results": ctx.results,
            "ctx": ctx.ctx,
        }

    def _parse_tasks(self, tasks: list[dict]) -> list[dict]:
        """
        Parse task list into task definitions (strict v10 - no legacy support).

        REJECTS: eval (must use spec.policy.rules)
        """
        parsed = []
        for task_def in tasks:
            if not isinstance(task_def, dict):
                continue

            for name, config in task_def.items():
                if name in ("next", "vars", "collect", "emit", "set"):
                    continue

                if isinstance(config, dict) and "kind" in config:
                    # STRICT v10: Reject eval
                    if "eval" in config:
                        raise ValueError(
                            f"Task '{name}': 'eval' is not allowed in v10. "
                            "Use 'spec.policy.rules' for outcome handling."
                        )

                    # Get policy rules from spec.policy.rules
                    policy_rules = []
                    if "spec" in config and isinstance(config["spec"], dict):
                        spec = config["spec"]
                        if "policy" in spec and isinstance(spec["policy"], dict):
                            policy = spec["policy"]
                            policy_rules = policy.get("rules", [])

                    parsed.append({
                        "name": name,
                        "config": config,
                        "policy_rules": policy_rules,
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

        if isinstance(error, TaskSequenceError):
            if error.context:
                context["status_code"] = error.context.get("status_code")
                context["headers"] = error.context.get("headers")
            return classify_error(error, source=error.source, context=context)

        return classify_error(error, source=tool_kind, context=context)

    def _evaluate_policy_rules(
        self,
        policy_rules: list[dict],
        render_ctx: dict,
        outcome: dict[str, Any],
    ) -> ControlAction:
        """
        Evaluate task.spec.policy.rules (strict v10 - no legacy support).

        REJECTS: expr (must use when)
        REJECTS: set_vars (must use set_ctx)

        Default behavior (if no rules):
        - ok → continue
        - error → fail
        """
        if not policy_rules:
            if outcome and outcome.get("status") == "error":
                return ControlAction(action="fail")
            return ControlAction(action="continue")

        for rule in policy_rules:
            if not isinstance(rule, dict):
                continue

            # Check for else clause
            if "else" in rule:
                else_data = rule["else"]
                if isinstance(else_data, dict) and "then" in else_data:
                    return self._parse_then(else_data["then"])
                continue

            # STRICT v10: Reject expr
            if "expr" in rule:
                raise ValueError(
                    "Policy rule uses 'expr' which is not allowed in v10. "
                    "Use 'when' as the ONLY conditional keyword."
                )

            # Get when condition (required for non-else rules)
            condition = rule.get("when")
            if condition is None:
                if "then" in rule:
                    return self._parse_then(rule["then"])
                continue

            try:
                # Handle boolean conditions directly (YAML parses `true` as bool)
                if isinstance(condition, bool):
                    matches = condition
                else:
                    rendered = self.render_template(condition, render_ctx)
                    # Handle boolean results from template rendering
                    if isinstance(rendered, bool):
                        matches = rendered
                    else:
                        matches = str(rendered).lower() in ("true", "1", "yes")

                if matches:
                    if "then" not in rule:
                        raise ValueError(
                            f"Policy rule with 'when' must have 'then' block in v10. "
                            f"Rule: {rule}"
                        )
                    return self._parse_then(rule["then"])
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f"[TASK_SEQ] Error evaluating policy rule condition: {e}")
                continue

        # No rule matched
        if outcome and outcome.get("status") == "error":
            logger.debug("[TASK_SEQ] No policy rule matched for error, defaulting to fail")
            return ControlAction(action="fail")

        logger.debug("[TASK_SEQ] No policy rule matched for ok, defaulting to continue")
        return ControlAction(action="continue")

    def _parse_then(self, then_data: dict) -> ControlAction:
        """Parse canonical v10 `then` block (strict - no legacy support)."""
        if not isinstance(then_data, dict):
            raise ValueError("Policy rule 'then' must be an object in v10")

        # STRICT v10: Reject set_vars
        if "set_vars" in then_data:
            raise ValueError(
                "Policy rule uses 'set_vars' which is not allowed in v10. "
                "Use 'set_ctx' for execution-scoped variables."
            )

        # STRICT v10: Require 'do' field
        if "do" not in then_data:
            raise ValueError(
                "Policy rule 'then' must have 'do' field in v10. "
                f"Got: {then_data}"
            )

        delay = then_data.get("delay", 1.0)
        if isinstance(delay, str):
            try:
                delay = float(delay)
            except ValueError:
                delay = 1.0

        return ControlAction(
            action=then_data["do"],
            to=then_data.get("to"),
            attempts=then_data.get("attempts", 3),
            backoff=then_data.get("backoff", "none"),
            delay=delay,
            set_ctx=then_data.get("set_ctx"),
            set_iter=then_data.get("set_iter"),
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


def is_task_sequence(tool_list: Any) -> bool:
    """
    Check if a tool list contains labeled tool tasks (task sequence).

    A task sequence is detected when the list contains items
    that are labeled tasks with kind configs (not reserved actions).
    """
    if not isinstance(tool_list, list):
        return False

    reserved_actions = {"next", "vars", "collect", "emit", "set", "pipe"}

    for item in tool_list:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if key not in reserved_actions and isinstance(value, dict):
                if "kind" in value:
                    return True

    return False


def extract_task_sequence(tool_list: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Extract task sequence and remaining actions from a tool list.

    Returns:
        (task_list, remaining_actions)
    """
    tasks = []
    remaining = []
    reserved_actions = {"next", "vars", "collect", "emit", "set"}

    for item in tool_list:
        if not isinstance(item, dict):
            continue

        is_task = False
        for key, value in item.items():
            if key not in reserved_actions and isinstance(value, dict):
                if "kind" in value:
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
