"""
Execution planning module for playbook executions.

Builds execution plan from validated playbook content including:
- Workflow steps and structure
- Step transitions and conditions
- Workbook task references
- Initial actionable steps
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class ExecutionPlan:
    """
    Represents an execution plan for a playbook.

    Contains:
    - workflow_steps: List of workflow step definitions
    - workbook_tasks: List of reusable workbook tasks
    - transitions: Step transition mapping
    - initial_steps: Steps ready for immediate execution (typically ['start'])
    """

    def __init__(
        self,
        workflow_steps: List[Dict[str, Any]],
        workbook_tasks: List[Dict[str, Any]],
        transitions: List[Dict[str, Any]],
        initial_steps: List[str],
    ):
        self.workflow_steps = workflow_steps
        self.workbook_tasks = workbook_tasks
        self.transitions = transitions
        self.initial_steps = initial_steps

    def to_dict(self) -> Dict[str, Any]:
        """Convert execution plan to dictionary."""
        return {
            "workflow_steps": self.workflow_steps,
            "workbook_tasks": self.workbook_tasks,
            "transitions": self.transitions,
            "initial_steps": self.initial_steps,
        }


class ExecutionPlanner:
    """
    Builds execution plan from validated playbook.

    Responsibilities:
    - Extract workflow steps
    - Build step transition graph
    - Identify initial actionable steps
    - Prepare workflow/workbook/transition data for database persistence
    """

    @staticmethod
    def build_plan(playbook: Dict[str, Any], execution_id: str) -> ExecutionPlan:
        """
        Build complete execution plan from playbook.

        Args:
            playbook: Validated playbook dictionary
            execution_id: Execution identifier

        Returns:
            ExecutionPlan with all workflow metadata
        """
        workflow = playbook.get("workflow", [])
        workbook = playbook.get("workbook", [])

        # Build transitions from workflow steps
        transitions = ExecutionPlanner._extract_transitions(workflow)

        # Prepare workflow steps for persistence
        workflow_steps = ExecutionPlanner._prepare_workflow_steps(
            workflow, execution_id
        )

        # Prepare workbook tasks for persistence
        workbook_tasks = ExecutionPlanner._prepare_workbook_tasks(
            workbook, execution_id
        )

        # Identify initial steps (should be 'start')
        initial_steps = ExecutionPlanner._identify_initial_steps(workflow)

        plan = ExecutionPlan(
            workflow_steps=workflow_steps,
            workbook_tasks=workbook_tasks,
            transitions=transitions,
            initial_steps=initial_steps,
        )

        logger.debug(
            f"Built execution plan for {execution_id}: "
            f"{len(workflow_steps)} steps, {len(transitions)} transitions, "
            f"initial steps: {initial_steps}"
        )

        return plan

    @staticmethod
    def _extract_transitions(workflow: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract step transitions from workflow.

        Returns list of transitions in format:
        {
            "from_step": "step_name",
            "to_step": "next_step_name",
            "condition": "{{ optional_condition }}",
            "with_params": {...}
        }
        """
        transitions = []

        for step in workflow:
            from_step = step.get("step")
            if not from_step:
                continue

            next_items = step.get("next", [])
            if not next_items:
                continue

            # Handle both list and single next item
            if not isinstance(next_items, list):
                next_items = [next_items]

            for next_item in next_items:
                if isinstance(next_item, dict):
                    # Structured next with condition and parameters
                    to_step = next_item.get("step")
                    condition = next_item.get("when", "")
                    with_params = next_item.get("data") or next_item.get("with") or {}

                    # Handle 'then' array for conditional transitions
                    then_items = next_item.get("then", [])
                    if then_items:
                        for then_item in then_items:
                            if isinstance(then_item, dict):
                                then_step = then_item.get("step")
                                if then_step:
                                    transitions.append(
                                        {
                                            "from_step": from_step,
                                            "to_step": then_step,
                                            "condition": condition,
                                            "with_params": then_item.get("data")
                                            or then_item.get("with")
                                            or {},
                                        }
                                    )
                            elif isinstance(then_item, str):
                                transitions.append(
                                    {
                                        "from_step": from_step,
                                        "to_step": then_item,
                                        "condition": condition,
                                        "with_params": {},
                                    }
                                )
                    elif to_step:
                        # Direct transition with optional condition
                        transitions.append(
                            {
                                "from_step": from_step,
                                "to_step": to_step,
                                "condition": condition,
                                "with_params": with_params,
                            }
                        )
                elif isinstance(next_item, str):
                    # Simple string transition
                    transitions.append(
                        {
                            "from_step": from_step,
                            "to_step": next_item,
                            "condition": "",
                            "with_params": {},
                        }
                    )

        return transitions

    @staticmethod
    def _prepare_workflow_steps(
        workflow: List[Dict[str, Any]], execution_id: str
    ) -> List[Dict[str, Any]]:
        """
        Prepare workflow steps for database persistence.

        Returns list in format matching noetl.workflow table:
        {
            "execution_id": execution_id,
            "step_id": "step_name",
            "step_name": "step_name",
            "step_type": "tool",
            "description": "desc",
            "raw_config": "{...}"
        }
        """
        workflow_steps = []

        for step in workflow:
            step_name = step.get("step")
            if not step_name:
                continue

            # Determine step type
            step_type = ExecutionPlanner._determine_step_type(step)

            workflow_steps.append(
                {
                    "execution_id": execution_id,
                    "step_id": step_name,
                    "step_name": step_name,
                    "step_type": step_type,
                    "description": step.get("desc") or step.get("description") or "",
                    "raw_config": json.dumps(step),
                }
            )

        return workflow_steps

    @staticmethod
    def _determine_step_type(step: Dict[str, Any]) -> str:
        """
        Determine step type from step configuration.

        Priority:
        1. Special control steps with specific handling:
           - 'start': router if no explicit tool; otherwise use explicit tool (actionable)
           - 'end': remains a terminal control step
        2. Explicit 'tool' field
        3. Default to control flow ('router') when no tool is provided
        """
        step_name = step.get("step", "").lower()

        # Special control steps handling
        # - start: router if no explicit type; otherwise use explicit type (actionable)
        # - end: remains a terminal control step
        if step_name == "start" and not step.get("tool"):
            return "router"
        if step_name == "end":
            return "end"

        tool = step.get("tool")
        if tool:
            return tool

        # Default to router for steps without an explicit tool
        return "router"

    @staticmethod
    def _prepare_workbook_tasks(
        workbook: List[Dict[str, Any]], execution_id: str
    ) -> List[Dict[str, Any]]:
        """
        Prepare workbook tasks for database persistence.

        Returns list in format matching noetl.workbook table:
        {
            "execution_id": execution_id,
            "task_id": "task_name",
            "task_name": "task_name",
            "task_type": "type",
            "raw_config": "{...}"
        }
        """
        workbook_tasks = []

        for task in workbook:
            task_name = task.get("name")
            if not task_name:
                continue

            tool_name = task.get("tool")
            if not tool_name:
                raise ValueError(
                    f"Workbook action '{task_name}' must define a 'tool' field"
                )

            workbook_tasks.append(
                {
                    "execution_id": execution_id,
                    "task_id": task_name,
                    "task_name": task_name,
                    "task_type": tool_name,
                    "raw_config": json.dumps(task),
                }
            )

        return workbook_tasks

    @staticmethod
    def _identify_initial_steps(workflow: List[Dict[str, Any]]) -> List[str]:
        """
        Identify initial steps that should execute immediately.

        Returns list of step names (typically just ['start'])
        """
        # In NoETL, workflow must have a 'start' step
        for step in workflow:
            step_name = step.get("step", "").lower()
            if step_name == "start":
                return ["start"]

        # Fallback: return first step if no 'start' found
        if workflow:
            first_step = workflow[0].get("step")
            if first_step:
                logger.warning(f"No 'start' step found, using first step: {first_step}")
                return [first_step]

        return []
