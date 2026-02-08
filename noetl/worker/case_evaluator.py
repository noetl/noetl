"""
Case Evaluator for DSL v2 with exclusive/inclusive mode support.

This module implements the case evaluation logic as described in the DSL specification:

- case_mode: exclusive (default) - XOR-split, first matching condition wins
- case_mode: inclusive - OR-split, all matching conditions fire their then blocks

The evaluator processes then: blocks as sequential task lists:
- Named tasks (with tool:) execute tools
- sink: executes immediately
- next: controls transitions (acts as break in exclusive mode)
- set: updates variables
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Literal
from jinja2 import Environment, Template
import logging

logger = logging.getLogger(__name__)


@dataclass
class CaseMatch:
    """Represents a matched case condition."""
    case_index: int
    when_condition: str
    then_block: list[dict[str, Any]]
    triggered_by: str  # 'call.done' or 'call.error'


@dataclass
class CaseAction:
    """Action extracted from a case match."""
    type: Literal["sink", "next", "retry", "set", "tool"]
    config: dict[str, Any]
    case_index: int
    triggered_by: str


@dataclass
class CaseEvaluationResult:
    """Result of case evaluation."""
    matches: list[CaseMatch] = field(default_factory=list)
    actions: list[CaseAction] = field(default_factory=list)
    routing_action: Optional[CaseAction] = None  # next or retry
    else_matched: bool = False


class TemplateCache:
    """LRU cache for compiled Jinja2 templates."""

    def __init__(self, max_size: int = 500):
        self._cache: dict[str, Template] = {}
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._jinja_env = Environment()

    def get_or_compile(self, template_str: str) -> Template:
        """Get template from cache or compile it."""
        if template_str in self._cache:
            self._hits += 1
            return self._cache[template_str]

        self._misses += 1

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._evictions += 1

        template = self._jinja_env.from_string(template_str)
        self._cache[template_str] = template
        return template

    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "size": len(self._cache)
        }


# Module-level template cache
_template_cache = TemplateCache()


class CaseEvaluator:
    """
    Evaluates case blocks with exclusive/inclusive mode support.

    Exclusive mode (default):
        - Evaluates conditions in order
        - First matching condition wins
        - next: acts as break (ends evaluation immediately)
        - else: fires only if no conditions matched

    Inclusive mode:
        - Evaluates ALL conditions
        - All matching then: blocks execute their immediate actions (sink, tool)
        - next: acts as break for inclusive mode too (first next: wins)
        - else: fires only if zero conditions matched
    """

    def __init__(self, case_mode: str = "exclusive", eval_mode: str = "on_entry"):
        self.case_mode = case_mode
        self.eval_mode = eval_mode

    def evaluate(
        self,
        case_blocks: list[dict[str, Any]],
        eval_context: dict[str, Any],
        event_name: str = "call.done"
    ) -> CaseEvaluationResult:
        """
        Evaluate case blocks against the given context.

        Args:
            case_blocks: List of case condition dicts with 'when' and 'then'
            eval_context: Context for Jinja2 template rendering
            event_name: Event triggering evaluation ('call.done' or 'call.error')

        Returns:
            CaseEvaluationResult with all matches and extracted actions
        """
        result = CaseEvaluationResult()

        if not case_blocks or not isinstance(case_blocks, list):
            return result

        logger.info(
            f"[CASE-EVAL] Evaluating {len(case_blocks)} case blocks | "
            f"mode={self.case_mode} | event={event_name}"
        )

        # Track whether any when condition matched
        any_when_matched = False

        for idx, case in enumerate(case_blocks):
            if not isinstance(case, dict):
                continue

            # Handle else block
            if 'else' in case:
                # else only fires if no when conditions matched
                if not any_when_matched:
                    logger.info(f"[CASE-EVAL] Case {idx}: else block fires (no prior matches)")
                    result.else_matched = True
                    else_actions = case.get('else', [])
                    if isinstance(else_actions, dict):
                        else_actions = [else_actions]

                    match = CaseMatch(
                        case_index=idx,
                        when_condition="else",
                        then_block=else_actions,
                        triggered_by=event_name
                    )
                    result.matches.append(match)

                    # Extract actions from else block
                    self._extract_actions(else_actions, idx, event_name, result)
                continue

            when_condition = case.get('when')
            then_block = case.get('then')

            if not when_condition:
                continue

            # Evaluate condition
            matches = self._evaluate_condition(when_condition, eval_context, idx)

            if matches:
                any_when_matched = True
                logger.info(f"[CASE-EVAL] Case {idx} MATCHED (mode={self.case_mode})")

                # Normalize then_block to list
                if then_block is None:
                    then_block = []
                elif isinstance(then_block, dict):
                    then_block = [then_block]

                match = CaseMatch(
                    case_index=idx,
                    when_condition=when_condition,
                    then_block=then_block,
                    triggered_by=event_name
                )
                result.matches.append(match)

                # Extract actions from then block
                has_routing = self._extract_actions(then_block, idx, event_name, result)

                # In exclusive mode, stop on first match
                if self.case_mode == "exclusive":
                    logger.info(f"[CASE-EVAL] Exclusive mode: stopping after first match (case {idx})")
                    break

                # In inclusive mode, stop if we found a routing action (next or retry)
                if has_routing and result.routing_action:
                    logger.info(f"[CASE-EVAL] Inclusive mode: found routing action, stopping")
                    break
            else:
                logger.debug(f"[CASE-EVAL] Case {idx} did not match")

        logger.info(
            f"[CASE-EVAL] Evaluation complete: {len(result.matches)} matches, "
            f"{len(result.actions)} actions, routing={result.routing_action is not None}"
        )

        return result

    def _evaluate_condition(
        self,
        condition: str,
        context: dict[str, Any],
        case_index: int
    ) -> bool:
        """Evaluate a Jinja2 condition template."""
        try:
            template = _template_cache.get_or_compile(condition)
            rendered = template.render(context)

            # Parse boolean result
            # Jinja2's `and` operator returns the actual value, not "True/False"
            result_stripped = rendered.strip()
            result_lower = result_stripped.lower()

            matches = bool(result_stripped) and result_lower not in ['false', '0', 'no', 'none', '']

            logger.debug(
                f"[CASE-EVAL] Case {case_index}: {condition[:80]}... = {rendered!r} -> {matches}"
            )

            return matches

        except Exception as e:
            logger.error(f"[CASE-EVAL] Error evaluating case {case_index}: {e}")
            return False

    def _extract_actions(
        self,
        then_block: list[dict[str, Any]],
        case_index: int,
        event_name: str,
        result: CaseEvaluationResult
    ) -> bool:
        """
        Extract actions from a then block.

        Returns True if a routing action (next/retry) was found.
        """
        has_routing = False

        for action_item in then_block:
            if not isinstance(action_item, dict):
                continue

            # Check for sink action
            if 'sink' in action_item:
                action = CaseAction(
                    type="sink",
                    config=action_item['sink'],
                    case_index=case_index,
                    triggered_by=event_name
                )
                result.actions.append(action)
                logger.debug(f"[CASE-EVAL] Extracted sink action from case {case_index}")

            # Check for retry action
            if 'retry' in action_item:
                action = CaseAction(
                    type="retry",
                    config=action_item['retry'],
                    case_index=case_index,
                    triggered_by=event_name
                )
                result.actions.append(action)
                if result.routing_action is None:
                    result.routing_action = action
                    has_routing = True
                logger.debug(f"[CASE-EVAL] Extracted retry action from case {case_index}")

            # Check for next action
            if 'next' in action_item:
                next_config = action_item['next']
                action = CaseAction(
                    type="next",
                    config={"steps": next_config},
                    case_index=case_index,
                    triggered_by=event_name
                )
                result.actions.append(action)
                if result.routing_action is None:
                    result.routing_action = action
                    has_routing = True
                logger.debug(f"[CASE-EVAL] Extracted next action from case {case_index}")

            # Check for set action
            if 'set' in action_item:
                action = CaseAction(
                    type="set",
                    config=action_item['set'],
                    case_index=case_index,
                    triggered_by=event_name
                )
                result.actions.append(action)
                logger.debug(f"[CASE-EVAL] Extracted set action from case {case_index}")

            # Check for named task with tool (future DSL pattern)
            for key, value in action_item.items():
                if key in ('sink', 'retry', 'next', 'set'):
                    continue
                if isinstance(value, dict) and 'tool' in value:
                    action = CaseAction(
                        type="tool",
                        config={"task_name": key, "tool": value['tool']},
                        case_index=case_index,
                        triggered_by=event_name
                    )
                    result.actions.append(action)
                    logger.debug(f"[CASE-EVAL] Extracted tool task '{key}' from case {case_index}")

        return has_routing


def build_eval_context(
    render_context: dict[str, Any],
    response: dict[str, Any],
    step: str,
    event_name: str = "call.done",
    error: Optional[str] = None
) -> dict[str, Any]:
    """
    Build the evaluation context for case condition rendering.

    This context includes:
    - All render_context variables (workload, step results, etc.)
    - response/result/this: tool response data
    - event: event context (name, type, step)
    - error: error message if call.error
    - status_code: HTTP status code if available
    """
    eval_context = {
        **render_context,
        'response': response,
        'result': response,
        'this': response,
        'event': {
            'name': event_name,
            'type': 'tool.completed' if event_name == 'call.done' else 'tool.error',
            'step': step
        },
        'error': error
    }

    # Add HTTP-specific context if available
    if isinstance(response, dict):
        if 'status_code' in response:
            eval_context['status_code'] = response['status_code']
        if isinstance(response.get('data'), dict) and 'status_code' in response['data']:
            eval_context['status_code'] = response['data']['status_code']

    return eval_context
