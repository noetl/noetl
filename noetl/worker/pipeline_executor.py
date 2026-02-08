"""
Pipeline executor for NoETL worker.

Executes pipe: blocks as atomic units with Clojure-style threading and error handling.

Features:
- Sequential task execution within a single worker
- Data threading via _prev (like Clojure's ->)
- Centralized error handling via catch.cond
- Control flow: retry, skip, jump, fail
- Tracks _task, _prev, _err, _attempt for template access

Usage in playbooks:
    case:
      - when: "{{ event.name == 'call.done' }}"
        then:
          pipe:
            - fetch: {tool: {kind: http, url: "..."}}
            - transform: {tool: {kind: python, args: {data: "{{ _prev }}"}}}
            - store: {tool: {kind: postgres, data: "{{ _prev }}"}}

          catch:
            cond:
              - when: "{{ _task == 'fetch' and _err.retryable }}"
                do: retry
                attempts: 5
              - else:
                  do: fail

          finally:
            - next: [{step: continue}]
"""

import asyncio
from typing import Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from noetl.core.errors import ErrorInfo, classify_error
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


@dataclass
class PipelineContext:
    """
    Runtime context for pipeline execution.

    Available as template variables:
    - _task: name of current/failed task
    - _prev: result of last successful task (threading)
    - _err: structured error payload
    - _attempt: retry attempt count for current task
    - results: dict of all task results by name
    """
    _task: str = ""
    _prev: Any = None
    _err: Optional[dict[str, Any]] = None
    _attempt: int = 1
    results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for template rendering."""
        return {
            "_task": self._task,
            "_prev": self._prev,
            "_err": self._err,
            "_attempt": self._attempt,
            "results": self.results,
        }

    def update_prev(self, task_name: str, result: Any):
        """Update _prev and results after successful task."""
        self._prev = result
        self._task = task_name
        self.results[task_name] = result
        self._err = None  # Clear error on success

    def update_error(self, task_name: str, error: ErrorInfo):
        """Update _err after failed task."""
        self._task = task_name
        self._err = error.to_dict()


@dataclass
class ControlAction:
    """Result of catch.cond evaluation."""
    action: str  # retry, skip, jump, fail, continue
    task: Optional[str] = None  # For retry: target task
    from_task: Optional[str] = None  # For retry: restart from
    to: Optional[str] = None  # For jump: target task
    attempts: int = 3  # Max retry attempts
    backoff: str = "none"  # none, linear, exponential
    delay: float = 1.0  # Initial delay seconds
    set_prev: Any = None  # For skip: value to set as _prev


class PipelineExecutor:
    """
    Executes a pipeline block within a single worker.

    The pipeline is treated as an atomic unit - all tasks run sequentially
    on the same worker with local control flow for error handling.
    """

    def __init__(
        self,
        tool_executor: Callable[[str, dict, dict], Awaitable[Any]],
        render_template: Callable[[str, dict], str],
        render_dict: Callable[[dict, dict], dict],
    ):
        """
        Initialize pipeline executor.

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
        pipeline: dict[str, Any],
        base_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute a pipeline block.

        Args:
            pipeline: The pipeline definition:
                {
                    "pipe": [...tasks...],
                    "catch": {"cond": [...]},
                    "finally": [...]
                }
            base_context: Base render context (workload, vars, step results)

        Returns:
            Pipeline result:
                {
                    "status": "success" | "failed" | "skipped",
                    "_prev": final _prev value,
                    "results": {task_name: result, ...},
                    "error": {...} if failed
                }
        """
        pipe_tasks = pipeline.get("pipe", [])
        catch_block = pipeline.get("catch", {})
        finally_block = pipeline.get("finally", [])

        if not pipe_tasks:
            logger.warning("[PIPELINE] Empty pipeline - no tasks to execute")
            return {"status": "success", "_prev": None, "results": {}}

        # Parse task list
        tasks = self._parse_tasks(pipe_tasks)
        task_names = [t["name"] for t in tasks]
        logger.info(f"[PIPELINE] Executing {len(tasks)} tasks: {task_names}")

        # Initialize context
        ctx = PipelineContext()
        retry_counts: dict[str, int] = {}  # task_name -> attempt count

        # Execute tasks
        current_idx = 0
        while current_idx < len(tasks):
            task = tasks[current_idx]
            task_name = task["name"]
            tool_spec = task["tool"]

            ctx._task = task_name
            ctx._attempt = retry_counts.get(task_name, 0) + 1

            # Build context for template rendering
            render_ctx = {
                **base_context,
                **ctx.to_dict(),
            }

            try:
                # Render tool config with current context
                tool_kind = tool_spec.get("kind")
                tool_config = {k: v for k, v in tool_spec.items() if k != "kind"}
                rendered_config = self.render_dict(tool_config, render_ctx)

                logger.info(f"[PIPELINE] Executing task '{task_name}' (kind={tool_kind}, attempt={ctx._attempt})")

                # Execute tool
                result = await self.tool_executor(tool_kind, rendered_config, render_ctx)

                # Check for error in result
                if isinstance(result, dict) and result.get("status") == "error":
                    raise PipelineTaskError(
                        task_name=task_name,
                        error=result.get("error", "Tool returned error status"),
                        source=tool_kind,
                        context=result,
                    )

                # Success - update context and move to next task
                ctx.update_prev(task_name, result)
                logger.info(f"[PIPELINE] Task '{task_name}' completed successfully")
                current_idx += 1

            except Exception as e:
                # Task failed - classify error
                error_info = self._classify_task_error(e, task_name, tool_spec.get("kind", "unknown"))
                ctx.update_error(task_name, error_info)

                logger.warning(f"[PIPELINE] Task '{task_name}' failed: {error_info.message}")

                # Evaluate catch.cond
                action = self._evaluate_catch(
                    catch_block,
                    ctx,
                    {**base_context, **ctx.to_dict()},
                )

                # Execute control action
                if action.action == "retry":
                    # Retry this task or from a specific task
                    target = action.from_task or action.task or task_name
                    retry_counts[target] = retry_counts.get(target, 0) + 1

                    if retry_counts[target] > action.attempts:
                        logger.error(f"[PIPELINE] Task '{target}' exceeded max attempts ({action.attempts})")
                        return {
                            "status": "failed",
                            "_prev": ctx._prev,
                            "results": ctx.results,
                            "error": ctx._err,
                            "failed_task": task_name,
                        }

                    # Find index of target task
                    target_idx = next((i for i, t in enumerate(tasks) if t["name"] == target), None)
                    if target_idx is None:
                        logger.error(f"[PIPELINE] Retry target '{target}' not found in pipeline")
                        return {
                            "status": "failed",
                            "_prev": ctx._prev,
                            "results": ctx.results,
                            "error": ctx._err,
                            "failed_task": task_name,
                        }

                    # Apply backoff delay
                    delay = self._calculate_delay(action, retry_counts[target])
                    if delay > 0:
                        logger.info(f"[PIPELINE] Waiting {delay:.2f}s before retry (backoff={action.backoff})")
                        await asyncio.sleep(delay)

                    logger.info(f"[PIPELINE] Retrying from task '{target}' (attempt {retry_counts[target] + 1})")
                    current_idx = target_idx

                elif action.action == "skip":
                    # Skip to next task
                    if action.set_prev is not None:
                        ctx._prev = action.set_prev
                    logger.info(f"[PIPELINE] Skipping failed task '{task_name}', continuing to next")
                    current_idx += 1

                elif action.action == "jump":
                    # Jump to specific task
                    target = action.to
                    if not target:
                        logger.error("[PIPELINE] Jump action missing 'to' target")
                        return {
                            "status": "failed",
                            "_prev": ctx._prev,
                            "results": ctx.results,
                            "error": ctx._err,
                            "failed_task": task_name,
                        }

                    target_idx = next((i for i, t in enumerate(tasks) if t["name"] == target), None)
                    if target_idx is None:
                        logger.error(f"[PIPELINE] Jump target '{target}' not found in pipeline")
                        return {
                            "status": "failed",
                            "_prev": ctx._prev,
                            "results": ctx.results,
                            "error": ctx._err,
                            "failed_task": task_name,
                        }

                    logger.info(f"[PIPELINE] Jumping to task '{target}'")
                    current_idx = target_idx

                elif action.action == "continue":
                    # Continue to next (unusual for error, but allowed)
                    logger.info(f"[PIPELINE] Continuing after failed task '{task_name}'")
                    current_idx += 1

                else:  # fail
                    logger.error(f"[PIPELINE] Pipeline failed at task '{task_name}'")
                    return {
                        "status": "failed",
                        "_prev": ctx._prev,
                        "results": ctx.results,
                        "error": ctx._err,
                        "failed_task": task_name,
                    }

        # All tasks completed successfully
        logger.info(f"[PIPELINE] Pipeline completed successfully, {len(ctx.results)} tasks executed")
        return {
            "status": "success",
            "_prev": ctx._prev,
            "results": ctx.results,
            "finally": finally_block,  # Return finally block for caller to process
        }

    def _parse_tasks(self, pipe_tasks: list[dict]) -> list[dict]:
        """Parse pipe list into task definitions."""
        tasks = []
        for task_def in pipe_tasks:
            if not isinstance(task_def, dict):
                continue
            # Format: {task_name: {tool: {...}}}
            for name, config in task_def.items():
                if isinstance(config, dict) and "tool" in config:
                    tasks.append({
                        "name": name,
                        "tool": config["tool"],
                        "catch": config.get("catch"),  # Optional per-task catch
                    })
        return tasks

    def _classify_task_error(
        self,
        error: Exception,
        task_name: str,
        tool_kind: str,
    ) -> ErrorInfo:
        """Classify a task execution error."""
        context = {}

        # Extract HTTP-specific info
        if isinstance(error, PipelineTaskError):
            if error.context:
                context["status_code"] = error.context.get("status_code")
                context["headers"] = error.context.get("headers")
            return classify_error(error, source=error.source, context=context)

        # Generic classification
        return classify_error(error, source=tool_kind, context=context)

    def _evaluate_catch(
        self,
        catch_block: dict,
        ctx: PipelineContext,
        render_ctx: dict,
    ) -> ControlAction:
        """
        Evaluate catch.cond to determine control action.

        Returns first matching condition's action, or fail if none match.
        """
        cond_list = catch_block.get("cond", [])

        for cond in cond_list:
            if not isinstance(cond, dict):
                continue

            # Check for else clause
            if "else" in cond:
                action_spec = cond["else"]
                return self._parse_action(action_spec)

            # Check when condition
            when_expr = cond.get("when")
            if when_expr is None:
                continue

            try:
                # Render condition with pipeline context
                rendered = self.render_template(when_expr, render_ctx)
                # Evaluate as boolean
                if rendered.lower() in ("true", "1", "yes"):
                    return self._parse_action(cond)
            except Exception as e:
                logger.warning(f"[PIPELINE] Error evaluating catch condition: {e}")
                continue

        # No match - default to fail
        logger.debug("[PIPELINE] No catch condition matched, defaulting to fail")
        return ControlAction(action="fail")

    def _parse_action(self, action_spec: dict) -> ControlAction:
        """Parse catch condition into ControlAction."""
        return ControlAction(
            action=action_spec.get("do", "fail"),
            task=action_spec.get("task"),
            from_task=action_spec.get("from"),
            to=action_spec.get("to"),
            attempts=action_spec.get("attempts", 3),
            backoff=action_spec.get("backoff", "none"),
            delay=action_spec.get("delay", 1.0),
            set_prev=action_spec.get("set_prev"),
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


class PipelineTaskError(Exception):
    """Error during pipeline task execution."""

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


def is_pipeline_block(then_block: Any) -> bool:
    """Check if a then: block contains a pipe: (pipeline) structure."""
    if isinstance(then_block, dict) and "pipe" in then_block:
        return True
    if isinstance(then_block, list):
        for item in then_block:
            if isinstance(item, dict) and "pipe" in item:
                return True
    return False


def extract_pipeline_block(then_block: Any) -> Optional[dict]:
    """Extract pipeline definition from then: block."""
    if isinstance(then_block, dict) and "pipe" in then_block:
        return then_block
    if isinstance(then_block, list):
        for item in then_block:
            if isinstance(item, dict) and "pipe" in item:
                return item
    return None


__all__ = [
    "PipelineExecutor",
    "PipelineContext",
    "PipelineTaskError",
    "ControlAction",
    "is_pipeline_block",
    "extract_pipeline_block",
]
