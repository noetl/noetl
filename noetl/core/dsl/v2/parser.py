"""
NoETL DSL v2 Parser - Canonical Format

Class-based YAML parser for v2 playbooks with canonical format:
- tool as pipeline (list of labeled tasks) or single tool shorthand
- step.when for transition enable guard
- next[].when for conditional routing
- loop.spec.mode for iteration mode
- tool.eval for per-task flow control
- Rejects case blocks (deprecated)
"""

import yaml
from typing import Any, Optional
from pathlib import Path
from .models import Playbook, Step, ToolSpec, Loop, WorkbookTask


class DSLParser:
    """
    YAML parser for NoETL DSL v2 playbooks (canonical format).

    Validates:
    - tool.kind pattern (rejects old 'type' field)
    - tool as single object or pipeline list
    - step.when for enable guards
    - next[].when for conditional routing
    - loop.spec.mode for iteration
    - Rejects case blocks (use step.when + next[].when instead)
    - Ensures 'start' step exists
    """

    def __init__(self):
        self._cache: dict[str, Playbook] = {}

    def parse(self, yaml_content: str, cache_key: Optional[str] = None) -> Playbook:
        """
        Parse YAML string to Playbook model.

        Args:
            yaml_content: YAML string
            cache_key: Optional key for caching

        Returns:
            Validated Playbook object

        Raises:
            ValueError: If YAML is invalid or uses deprecated patterns
        """
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]

        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

        # Validate canonical structure
        self._validate_canonical_structure(data)

        # Parse to model
        playbook = Playbook(**data)

        # Cache if requested
        if cache_key:
            self._cache[cache_key] = playbook

        return playbook

    def parse_file(self, file_path: str | Path, use_cache: bool = True) -> Playbook:
        """
        Parse YAML file to Playbook model.

        Args:
            file_path: Path to YAML file
            use_cache: Whether to use cache

        Returns:
            Validated Playbook object
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Playbook file not found: {file_path}")

        cache_key = str(file_path.absolute()) if use_cache else None
        yaml_content = file_path.read_text()

        return self.parse(yaml_content, cache_key=cache_key)

    def validate(self, yaml_content: str) -> tuple[bool, Optional[str]]:
        """
        Validate YAML without full parsing.

        Args:
            yaml_content: YAML string

        Returns:
            (is_valid, error_message)
        """
        try:
            self.parse(yaml_content)
            return True, None
        except Exception as e:
            return False, str(e)

    def validate_file(self, file_path: str | Path) -> tuple[bool, Optional[str]]:
        """
        Validate YAML file without full parsing.

        Args:
            file_path: Path to YAML file

        Returns:
            (is_valid, error_message)
        """
        try:
            self.parse_file(file_path, use_cache=False)
            return True, None
        except Exception as e:
            return False, str(e)

    def to_dict(self, playbook: Playbook) -> dict[str, Any]:
        """Convert Playbook model to dict."""
        return playbook.model_dump(by_alias=True, exclude_none=True)

    def to_yaml(self, playbook: Playbook) -> str:
        """Convert Playbook model to YAML string."""
        data = self.to_dict(playbook)
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def clear_cache(self, cache_key: Optional[str] = None):
        """
        Clear parser cache.

        Args:
            cache_key: Specific key to clear, or None to clear all
        """
        if cache_key:
            self._cache.pop(cache_key, None)
        else:
            self._cache.clear()

    def get_step(self, playbook: Playbook, step_name: str) -> Optional[Step]:
        """Get step by name from playbook."""
        for step in playbook.workflow:
            if step.step == step_name:
                return step
        return None

    def list_steps(self, playbook: Playbook) -> list[str]:
        """List all step names in playbook."""
        return [step.step for step in playbook.workflow]

    def _validate_canonical_structure(self, data: dict[str, Any]):
        """
        Validate that data uses canonical v2 structure.
        Reject deprecated patterns.
        """
        # Check apiVersion
        api_version = data.get("apiVersion", "")
        if api_version != "noetl.io/v2":
            raise ValueError(
                f"Invalid apiVersion: {api_version}. "
                "v2 playbooks must use 'apiVersion: noetl.io/v2'"
            )

        # Check kind
        if data.get("kind") != "Playbook":
            raise ValueError("kind must be 'Playbook'")

        # Validate executor if present
        if "executor" in data:
            self._validate_executor(data["executor"], data.get("workflow", []))

        # Validate workflow steps
        workflow = data.get("workflow", [])
        if not workflow:
            raise ValueError("Workflow cannot be empty")

        for step_data in workflow:
            self._validate_step_canonical(step_data)

    def _validate_step_canonical(self, step_data: dict[str, Any]):
        """
        Validate step uses canonical structure.
        Reject deprecated patterns (case blocks).
        """
        step_name = step_data.get("step", "<unknown>")

        # Check for old 'type' field
        if "type" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'type' field is not allowed. "
                "Use 'tool.kind' instead."
            )

        # REJECT case blocks - use step.when + next[].when instead
        if "case" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'case' blocks are not allowed in canonical format. "
                "Use 'step.when' for enable guards and 'next[].when' for conditional routing. "
                "For pipelines, use 'tool: [- label: {{kind: ...}}]' directly on the step."
            )

        # Validate tool field
        has_tool = "tool" in step_data
        if not has_tool:
            raise ValueError(
                f"Step '{step_name}': Missing 'tool' field. "
                "Every step must have a tool (use 'kind: noop' for pure routing steps)."
            )

        tool_data = step_data["tool"]
        self._validate_tool_canonical(tool_data, step_name)

        # Validate step.when if present
        if "when" in step_data:
            when_expr = step_data["when"]
            if not isinstance(when_expr, str):
                raise ValueError(
                    f"Step '{step_name}': 'when' must be a Jinja2 expression string"
                )

        # Validate next with conditional routing
        if "next" in step_data:
            self._validate_next_canonical(step_data["next"], step_name)

        # Validate loop.spec.mode
        if "loop" in step_data:
            self._validate_loop_canonical(step_data["loop"], step_name)

        # Validate step.spec if present
        if "spec" in step_data:
            self._validate_step_spec(step_data["spec"], step_name)

    def _validate_tool_canonical(self, tool_data: Any, step_name: str):
        """
        Validate tool field in canonical format.

        Supports two forms:
        - Single tool object: {kind: http, url: "..."}
        - Pipeline list: [- label: {kind: http, ...}]
        """
        if isinstance(tool_data, dict):
            # Single tool shorthand
            if "kind" not in tool_data:
                raise ValueError(
                    f"Step '{step_name}': tool must have 'kind' field "
                    "(e.g., http, postgres, python, noop)"
                )
            # Validate tool.eval if present
            if "eval" in tool_data:
                self._validate_tool_eval(tool_data["eval"], step_name, "tool")

        elif isinstance(tool_data, list):
            # Pipeline format
            self._validate_tool_pipeline(tool_data, step_name)

        else:
            raise ValueError(
                f"Step '{step_name}': 'tool' must be an object or list of labeled tasks"
            )

    def _validate_tool_pipeline(self, pipeline: list, step_name: str):
        """
        Validate tool pipeline (list of labeled tasks).

        Each task must be: {label: {kind: ..., eval: [...], ...}}
        """
        if not pipeline:
            raise ValueError(
                f"Step '{step_name}': tool pipeline cannot be empty"
            )

        seen_labels = set()

        for i, task_def in enumerate(pipeline):
            if not isinstance(task_def, dict):
                raise ValueError(
                    f"Step '{step_name}': tool[{i}] must be an object"
                )

            if len(task_def) != 1:
                raise ValueError(
                    f"Step '{step_name}': tool[{i}] must have exactly one key (the task label). "
                    f"Got: {list(task_def.keys())}"
                )

            label, task_config = next(iter(task_def.items()))

            if label in seen_labels:
                raise ValueError(
                    f"Step '{step_name}': Duplicate task label '{label}'"
                )
            seen_labels.add(label)

            if not isinstance(task_config, dict):
                raise ValueError(
                    f"Step '{step_name}': tool[{i}].{label} must be an object"
                )

            if "kind" not in task_config:
                raise ValueError(
                    f"Step '{step_name}': tool[{i}].{label} must have 'kind' field"
                )

            # Validate tool.eval if present
            if "eval" in task_config:
                self._validate_tool_eval(
                    task_config["eval"], step_name, f"tool[{i}].{label}"
                )

    def _validate_next_canonical(self, next_data: Any, step_name: str):
        """
        Validate canonical next format with conditional routing.

        Supports:
        - String shorthand: next: "step_name"
        - List of strings: next: ["step1", "step2"]
        - List of objects with optional when: next: [{step: x, when: "..."}]
        """
        if isinstance(next_data, str):
            return  # Simple step name - valid

        if isinstance(next_data, list):
            for i, item in enumerate(next_data):
                if isinstance(item, str):
                    continue  # Simple step name

                if isinstance(item, dict):
                    # Must have 'step' key
                    if "step" not in item:
                        raise ValueError(
                            f"Step '{step_name}': next[{i}] must have 'step' field"
                        )

                    # Validate 'when' if present
                    if "when" in item and not isinstance(item["when"], str):
                        raise ValueError(
                            f"Step '{step_name}': next[{i}].when must be a Jinja2 expression string"
                        )

                    # Reject old then/else patterns
                    if "then" in item or "else" in item:
                        raise ValueError(
                            f"Step '{step_name}': next[{i}] cannot have 'then' or 'else'. "
                            "Use next[].when for conditional routing."
                        )
                else:
                    raise ValueError(
                        f"Step '{step_name}': next[{i}] must be a string or object"
                    )
        else:
            raise ValueError(
                f"Step '{step_name}': 'next' must be a string or list"
            )

    def _validate_loop_canonical(self, loop_data: dict, step_name: str):
        """
        Validate canonical loop format with spec.

        Canonical format:
            loop:
              spec:
                mode: parallel
                max_in_flight: 5
              in: "{{ workload.items }}"
              iterator: item
        """
        if not isinstance(loop_data, dict):
            raise ValueError(
                f"Step '{step_name}': 'loop' must be an object"
            )

        # Required fields
        if "in" not in loop_data:
            raise ValueError(
                f"Step '{step_name}': loop must have 'in' field"
            )

        if "iterator" not in loop_data:
            raise ValueError(
                f"Step '{step_name}': loop must have 'iterator' field"
            )

        # Validate loop.spec if present
        if "spec" in loop_data:
            spec = loop_data["spec"]
            if not isinstance(spec, dict):
                raise ValueError(
                    f"Step '{step_name}': loop.spec must be an object"
                )

            if "mode" in spec and spec["mode"] not in ("sequential", "parallel"):
                raise ValueError(
                    f"Step '{step_name}': loop.spec.mode must be 'sequential' or 'parallel'"
                )

            if "max_in_flight" in spec:
                max_flight = spec["max_in_flight"]
                if not isinstance(max_flight, int) or max_flight < 1:
                    raise ValueError(
                        f"Step '{step_name}': loop.spec.max_in_flight must be a positive integer"
                    )

    def _validate_step_spec(self, spec_data: dict, step_name: str):
        """Validate step.spec configuration."""
        if not isinstance(spec_data, dict):
            raise ValueError(
                f"Step '{step_name}': 'spec' must be an object"
            )

        # Validate next_mode
        if "next_mode" in spec_data:
            if spec_data["next_mode"] not in ("exclusive", "inclusive"):
                raise ValueError(
                    f"Step '{step_name}': spec.next_mode must be 'exclusive' or 'inclusive'"
                )

        # Validate on_error
        if "on_error" in spec_data:
            if spec_data["on_error"] not in ("fail", "continue", "retry"):
                raise ValueError(
                    f"Step '{step_name}': spec.on_error must be 'fail', 'continue', or 'retry'"
                )

    def _validate_executor(self, executor_data: Any, workflow: list):
        """
        Validate executor configuration (canonical v2).

        Validates:
        - profile: local, distributed, auto
        - version: semantic version string
        - requires: tools and features lists
        - spec: entry_step, final_step, no_next_is_error
        """
        if not isinstance(executor_data, dict):
            raise ValueError("executor must be an object")

        # Validate profile
        if "profile" in executor_data:
            valid_profiles = ("local", "distributed", "auto")
            if executor_data["profile"] not in valid_profiles:
                raise ValueError(
                    f"executor.profile must be one of: {valid_profiles}"
                )

        # Validate requires
        if "requires" in executor_data:
            requires = executor_data["requires"]
            if not isinstance(requires, dict):
                raise ValueError("executor.requires must be an object")

            if "tools" in requires and not isinstance(requires["tools"], list):
                raise ValueError("executor.requires.tools must be a list")

            if "features" in requires and not isinstance(requires["features"], list):
                raise ValueError("executor.requires.features must be a list")

        # Validate spec
        if "spec" in executor_data:
            spec = executor_data["spec"]
            if not isinstance(spec, dict):
                raise ValueError("executor.spec must be an object")

            # Validate entry_step exists in workflow
            if "entry_step" in spec:
                entry_step = spec["entry_step"]
                if not isinstance(entry_step, str):
                    raise ValueError("executor.spec.entry_step must be a string")

                step_names = [s.get("step") for s in workflow if isinstance(s, dict)]
                if entry_step not in step_names:
                    raise ValueError(
                        f"executor.spec.entry_step '{entry_step}' not found in workflow. "
                        f"Available steps: {step_names}"
                    )

            # Validate final_step exists in workflow
            if "final_step" in spec:
                final_step = spec["final_step"]
                if not isinstance(final_step, str):
                    raise ValueError("executor.spec.final_step must be a string")

                step_names = [s.get("step") for s in workflow if isinstance(s, dict)]
                if final_step not in step_names:
                    raise ValueError(
                        f"executor.spec.final_step '{final_step}' not found in workflow. "
                        f"Available steps: {step_names}"
                    )

            # Validate no_next_is_error
            if "no_next_is_error" in spec:
                if not isinstance(spec["no_next_is_error"], bool):
                    raise ValueError("executor.spec.no_next_is_error must be a boolean")

    def _validate_tool_eval(self, eval_data: Any, step_name: str, location: str):
        """
        Validate tool.eval structure.

        Each entry must be either:
        - {expr: "...", do: "action", ...} - Conditional action
        - {else: {do: "action"}} - Default action
        """
        if not isinstance(eval_data, list):
            raise ValueError(
                f"Step '{step_name}': {location}.eval must be a list of conditions"
            )

        valid_actions = {"continue", "retry", "break", "jump", "fail"}

        for i, entry in enumerate(eval_data):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Step '{step_name}': {location}.eval[{i}] must be an object"
                )

            # Check for else clause
            if "else" in entry:
                else_data = entry["else"]
                if isinstance(else_data, dict):
                    action = else_data.get("do", "continue")
                    if action not in valid_actions:
                        raise ValueError(
                            f"Step '{step_name}': {location}.eval[{i}].else.do must be one of: {valid_actions}"
                        )
                continue

            # Validate expr condition
            if "expr" not in entry and "do" not in entry:
                raise ValueError(
                    f"Step '{step_name}': {location}.eval[{i}] must have 'expr' or be an 'else' clause"
                )

            action = entry.get("do", "continue")
            if action not in valid_actions:
                raise ValueError(
                    f"Step '{step_name}': {location}.eval[{i}].do must be one of: {valid_actions}"
                )

            # Validate jump requires 'to' target
            if action == "jump" and "to" not in entry:
                raise ValueError(
                    f"Step '{step_name}': {location}.eval[{i}] jump action requires 'to' target"
                )

            # Validate retry options
            if action == "retry":
                if "attempts" in entry and not isinstance(entry["attempts"], int):
                    raise ValueError(
                        f"Step '{step_name}': {location}.eval[{i}].attempts must be an integer"
                    )
                valid_backoff = ("none", "linear", "exponential", "fixed")
                if "backoff" in entry and entry["backoff"] not in valid_backoff:
                    raise ValueError(
                        f"Step '{step_name}': {location}.eval[{i}].backoff must be one of: {valid_backoff}"
                    )


# ============================================================================
# Global Parser Instance and Convenience Functions
# ============================================================================

_default_parser: Optional[DSLParser] = None


def get_parser() -> DSLParser:
    """Get global DSLParser instance."""
    global _default_parser
    if _default_parser is None:
        _default_parser = DSLParser()
    return _default_parser


def parse_playbook(yaml_content: str, cache_key: Optional[str] = None) -> Playbook:
    """Parse YAML content to Playbook (convenience function)."""
    return get_parser().parse(yaml_content, cache_key=cache_key)


def parse_playbook_file(file_path: str | Path, use_cache: bool = True) -> Playbook:
    """Parse YAML file to Playbook (convenience function)."""
    return get_parser().parse_file(file_path, use_cache=use_cache)


def validate_playbook(yaml_content: str) -> tuple[bool, Optional[str]]:
    """Validate YAML content (convenience function)."""
    return get_parser().validate(yaml_content)


def validate_playbook_file(file_path: str | Path) -> tuple[bool, Optional[str]]:
    """Validate YAML file (convenience function)."""
    return get_parser().validate_file(file_path)
