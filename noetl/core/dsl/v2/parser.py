"""
NoETL DSL v2 Parser - Canonical v10 Format

Class-based YAML parser for v2 playbooks with canonical v10 format:
- `when` is the ONLY conditional keyword (reject `expr`)
- All knobs live under `spec` at any level
- Policies under `spec.policy` typed by scope
- Task outcome via `task.spec.policy.rules` (reject `eval`)
- Routing via `next.spec` + `next.arcs[]` (Petri-net arcs)
- NO `step.when` field (use `step.spec.policy.admit.rules`)
- NO root `vars` (use ctx/iter via policy)
"""

import yaml
from typing import Any, Optional
from pathlib import Path
from .models import Playbook, Step, ToolSpec, Loop, WorkbookTask


class DSLParser:
    """
    YAML parser for NoETL DSL v2 playbooks (canonical v10 format).

    Validates:
    - tool.kind pattern (rejects old 'type' field)
    - tool as single object or pipeline list
    - task.spec.policy.rules for outcome handling (rejects eval)
    - next.spec + next.arcs[] for routing (rejects simple next[] list)
    - step.spec.policy.admit.rules for admission (rejects step.when)
    - loop.spec.mode for iteration
    - Rejects case blocks, expr, eval, step.when, root vars
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

        # Validate canonical v10 structure
        self._validate_canonical_v10(data)

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

    # =========================================================================
    # Canonical v10 Validation
    # =========================================================================

    def _validate_canonical_v10(self, data: dict[str, Any]):
        """
        Validate that data uses canonical v10 structure.
        Reject all deprecated patterns.
        """
        # Check apiVersion - accept both v2 and v10 (canonical naming convention)
        api_version = data.get("apiVersion", "")
        valid_versions = ("noetl.io/v2", "noetl.io/v10")
        if api_version not in valid_versions:
            raise ValueError(
                f"Invalid apiVersion: {api_version}. "
                f"Playbooks must use one of: {valid_versions}"
            )

        # Check kind
        if data.get("kind") != "Playbook":
            raise ValueError("kind must be 'Playbook'")

        # REJECT root vars (v10: use ctx/iter via policy)
        if "vars" in data:
            raise ValueError(
                "Root 'vars' is not allowed in canonical v10. "
                "Use 'ctx' (execution-scoped) and 'iter' (iteration-scoped) via policy mutations."
            )

        # Validate executor if present
        if "executor" in data:
            self._validate_executor(data["executor"], data.get("workflow", []))

        # Validate workflow steps
        workflow = data.get("workflow", [])
        if not workflow:
            raise ValueError("Workflow cannot be empty")

        # Collect all task labels for jump validation
        all_task_labels = set()
        for step_data in workflow:
            labels = self._collect_task_labels(step_data)
            all_task_labels.update(labels)

        for step_data in workflow:
            self._validate_step_v10(step_data, all_task_labels)

    def _collect_task_labels(self, step_data: dict[str, Any]) -> set[str]:
        """
        Collect all task labels in a step for jump validation.

        Supported formats:
        1. Canonical (named): { name: "task_name", kind: "http", ... }
        2. Unnamed: { kind: "http", ... } - synthetic name task_N
        """
        labels = set()
        tool_data = step_data.get("tool")
        if isinstance(tool_data, list):
            for i, task_def in enumerate(tool_data):
                if isinstance(task_def, dict):
                    # Canonical format: { name: "task_name", kind: ... }
                    if "name" in task_def and "kind" in task_def:
                        labels.add(task_def["name"])
                    # Unnamed format: { kind: ... }
                    elif "kind" in task_def and "name" not in task_def:
                        labels.add(f"task_{i}")
        return labels

    def _validate_step_v10(self, step_data: dict[str, Any], all_task_labels: set[str]):
        """
        Validate step uses canonical v10 structure.
        Reject deprecated patterns.
        """
        step_name = step_data.get("step", "<unknown>")

        # REJECT step.when (v10: use step.spec.policy.admit.rules)
        if "when" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'when' field is not allowed on step in v10. "
                "Use 'step.spec.policy.admit.rules' for admission control."
            )

        # REJECT case blocks
        if "case" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'case' blocks are not allowed in v10. "
                "Use 'step.spec.policy.admit.rules' for admission, "
                "'task.spec.policy.rules' for outcome handling, "
                "and 'next.arcs[].when' for routing."
            )

        # Check for old 'type' field
        if "type" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'type' field is not allowed. "
                "Use 'tool.kind' instead."
            )

        # Validate tool field is required
        if "tool" not in step_data:
            raise ValueError(
                f"Step '{step_name}': Missing 'tool' field. "
                "Every step must have a tool (use 'kind: noop' for pure routing)."
            )

        tool_data = step_data["tool"]
        self._validate_tool_v10(tool_data, step_name, all_task_labels)

        # Validate step.spec if present
        if "spec" in step_data:
            self._validate_step_spec_v10(step_data["spec"], step_name)

        # Validate next router
        if "next" in step_data:
            self._validate_next_router_v10(step_data["next"], step_name)

        # Validate loop.spec
        if "loop" in step_data:
            self._validate_loop_v10(step_data["loop"], step_name)

    def _validate_tool_v10(self, tool_data: Any, step_name: str, all_task_labels: set[str]):
        """
        Validate tool field in canonical v10 format.

        REJECTS: eval (use task.spec.policy.rules instead)
        """
        if isinstance(tool_data, dict):
            # Single tool shorthand
            if "kind" not in tool_data:
                raise ValueError(
                    f"Step '{step_name}': tool must have 'kind' field "
                    "(e.g., http, postgres, python, noop)"
                )
            # REJECT eval (v10: use task.spec.policy.rules)
            if "eval" in tool_data:
                raise ValueError(
                    f"Step '{step_name}': 'eval' is not allowed in v10. "
                    "Use 'task.spec.policy.rules' for outcome handling instead."
                )
            # Validate task.spec.policy if present
            if "spec" in tool_data:
                self._validate_task_spec_v10(tool_data["spec"], step_name, "tool", all_task_labels)

        elif isinstance(tool_data, list):
            # Pipeline format
            self._validate_tool_pipeline_v10(tool_data, step_name, all_task_labels)

        else:
            raise ValueError(
                f"Step '{step_name}': 'tool' must be an object or list of labeled tasks"
            )

    def _validate_tool_pipeline_v10(self, pipeline: list, step_name: str, all_task_labels: set[str]):
        """
        Validate tool pipeline (list of labeled tasks) in v10 format.

        Supported formats:
        1. Canonical (named): { name: "task_name", kind: "http", ... }
        2. Unnamed: { kind: "http", ... } - synthetic name task_N

        NOT supported (removed):
        - Syntactic sugar: { task_label: { kind: ... } }
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

            # Determine format and extract label + config
            # Canonical format: { name: "task_name", kind: "http", ... }
            # Unnamed format: { kind: "http", ... }
            if "name" in task_def and "kind" in task_def:
                # Canonical format
                label = task_def["name"]
                task_config = {k: v for k, v in task_def.items() if k != "name"}
            elif "kind" in task_def and "name" not in task_def:
                # Unnamed format - assign synthetic label
                label = f"task_{i}"
                task_config = task_def
            else:
                # Invalid format - syntactic sugar is no longer supported
                raise ValueError(
                    f"Step '{step_name}': tool[{i}] must be either:\n"
                    f"  1. Canonical: {{ name: 'task_name', kind: 'http', ... }}\n"
                    f"  2. Unnamed: {{ kind: 'http', ... }}\n"
                    f"Got: {list(task_def.keys())}"
                )

            if label in seen_labels:
                raise ValueError(
                    f"Step '{step_name}': Duplicate task label '{label}'"
                )
            seen_labels.add(label)

            if "kind" not in task_config:
                raise ValueError(
                    f"Step '{step_name}': tool[{i}].{label} must have 'kind' field"
                )

            # REJECT eval (v10: use task.spec.policy.rules)
            if "eval" in task_config:
                raise ValueError(
                    f"Step '{step_name}': tool[{i}].{label}: 'eval' is not allowed in v10. "
                    "Use 'spec.policy.rules' for outcome handling instead."
                )

            # Validate task.spec.policy if present
            if "spec" in task_config:
                self._validate_task_spec_v10(
                    task_config["spec"], step_name, f"tool[{i}].{label}", all_task_labels
                )

    def _validate_task_spec_v10(self, spec_data: Any, step_name: str, location: str, all_task_labels: set[str]):
        """
        Validate task.spec in v10 format.

        task.spec.policy MUST be an object with required `rules:` list.
        """
        if not isinstance(spec_data, dict):
            raise ValueError(
                f"Step '{step_name}': {location}.spec must be an object"
            )

        if "policy" in spec_data:
            policy = spec_data["policy"]
            if not isinstance(policy, dict):
                raise ValueError(
                    f"Step '{step_name}': {location}.spec.policy must be an object"
                )

            # MUST have rules (v10 requirement)
            if "rules" not in policy:
                raise ValueError(
                    f"Step '{step_name}': {location}.spec.policy must have 'rules' field. "
                    "Task policy requires rules: [...] in v10."
                )

            rules = policy["rules"]
            if not isinstance(rules, list):
                raise ValueError(
                    f"Step '{step_name}': {location}.spec.policy.rules must be a list"
                )

            self._validate_policy_rules_v10(rules, step_name, f"{location}.spec.policy", all_task_labels)

    def _validate_policy_rules_v10(self, rules: list, step_name: str, location: str, all_task_labels: set[str]):
        """
        Validate policy rules in v10 format.

        Each rule must use `when` (not `expr`) and have `then.do`.
        """
        valid_actions = {"continue", "retry", "break", "jump", "fail"}

        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}] must be an object"
                )

            # Check for else clause
            if "else" in rule:
                else_data = rule["else"]
                if isinstance(else_data, dict) and "then" in else_data:
                    self._validate_then_v10(
                        else_data["then"], step_name, f"{location}.rules[{i}].else",
                        valid_actions, all_task_labels
                    )
                continue

            # REJECT expr (v10: only `when` is allowed)
            if "expr" in rule:
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}]: 'expr' is not allowed in v10. "
                    "Use 'when' as the ONLY conditional keyword."
                )

            # Must have `when` condition (or be else clause)
            if "when" not in rule:
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}] must have 'when' or be an 'else' clause"
                )

            if not isinstance(rule["when"], str):
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}].when must be a Jinja2 expression string"
                )

            # Must have `then` with action
            if "then" not in rule:
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}] must have 'then' field"
                )

            self._validate_then_v10(
                rule["then"], step_name, f"{location}.rules[{i}]",
                valid_actions, all_task_labels
            )

    def _validate_then_v10(self, then_data: Any, step_name: str, location: str,
                          valid_actions: set[str], all_task_labels: set[str]):
        """
        Validate `then` block in v10 format.

        MUST have `do` field with valid action.
        """
        if not isinstance(then_data, dict):
            raise ValueError(
                f"Step '{step_name}': {location}.then must be an object"
            )

        # For admit policies, allow: is valid
        if "allow" in then_data and "do" not in then_data:
            return  # Valid admit rule

        # MUST have `do` field (v10 requirement)
        if "do" not in then_data:
            raise ValueError(
                f"Step '{step_name}': {location}.then must have 'do' field. "
                "Task policy rules require 'then.do' in v10."
            )

        action = then_data["do"]
        if action not in valid_actions:
            raise ValueError(
                f"Step '{step_name}': {location}.then.do must be one of: {valid_actions}. "
                f"Got: '{action}'"
            )

        # Validate jump requires 'to' target
        if action == "jump":
            if "to" not in then_data:
                raise ValueError(
                    f"Step '{step_name}': {location}.then: jump action requires 'to' target"
                )
            jump_target = then_data["to"]
            if jump_target not in all_task_labels:
                raise ValueError(
                    f"Step '{step_name}': {location}.then.to: unknown task label '{jump_target}'. "
                    f"Available labels: {sorted(all_task_labels)}"
                )

        # Validate retry options
        if action == "retry":
            if "attempts" in then_data and not isinstance(then_data["attempts"], int):
                raise ValueError(
                    f"Step '{step_name}': {location}.then.attempts must be an integer"
                )
            valid_backoff = ("none", "linear", "exponential")
            if "backoff" in then_data and then_data["backoff"] not in valid_backoff:
                raise ValueError(
                    f"Step '{step_name}': {location}.then.backoff must be one of: {valid_backoff}"
                )

    def _validate_step_spec_v10(self, spec_data: Any, step_name: str):
        """
        Validate step.spec in v10 format.

        NOTE: next_mode is REMOVED from step.spec in v10.
        Use next.spec.mode instead.
        """
        if not isinstance(spec_data, dict):
            raise ValueError(
                f"Step '{step_name}': 'spec' must be an object"
            )

        # REJECT next_mode at step level (v10: use next.spec.mode)
        if "next_mode" in spec_data:
            raise ValueError(
                f"Step '{step_name}': 'spec.next_mode' is not allowed in v10. "
                "Use 'next.spec.mode' for routing mode."
            )

        # Validate policy if present
        if "policy" in spec_data:
            policy = spec_data["policy"]
            if not isinstance(policy, dict):
                raise ValueError(
                    f"Step '{step_name}': spec.policy must be an object"
                )

            # Validate admit policy
            if "admit" in policy:
                self._validate_admit_policy_v10(policy["admit"], step_name)

    def _validate_admit_policy_v10(self, admit_data: Any, step_name: str):
        """
        Validate step.spec.policy.admit in v10 format.
        """
        if not isinstance(admit_data, dict):
            raise ValueError(
                f"Step '{step_name}': spec.policy.admit must be an object"
            )

        if "rules" in admit_data:
            rules = admit_data["rules"]
            if not isinstance(rules, list):
                raise ValueError(
                    f"Step '{step_name}': spec.policy.admit.rules must be a list"
                )

            for i, rule in enumerate(rules):
                if not isinstance(rule, dict):
                    raise ValueError(
                        f"Step '{step_name}': spec.policy.admit.rules[{i}] must be an object"
                    )

                # Check for else clause
                if "else" in rule:
                    else_data = rule["else"]
                    if isinstance(else_data, dict) and "then" in else_data:
                        then = else_data["then"]
                        if isinstance(then, dict) and "allow" not in then:
                            raise ValueError(
                                f"Step '{step_name}': spec.policy.admit.rules[{i}].else.then "
                                "must have 'allow' field for admission"
                            )
                    continue

                # REJECT expr
                if "expr" in rule:
                    raise ValueError(
                        f"Step '{step_name}': spec.policy.admit.rules[{i}]: "
                        "'expr' is not allowed in v10. Use 'when'."
                    )

                # Must have when or be else
                if "when" not in rule:
                    raise ValueError(
                        f"Step '{step_name}': spec.policy.admit.rules[{i}] "
                        "must have 'when' or be an 'else' clause"
                    )

                # Must have then with allow
                if "then" not in rule:
                    raise ValueError(
                        f"Step '{step_name}': spec.policy.admit.rules[{i}] "
                        "must have 'then' field"
                    )

    def _validate_next_router_v10(self, next_data: Any, step_name: str):
        """
        Validate next router in v10 format.

        Canonical format: {spec: {...}, arcs: [...]}
        Also accepts legacy formats for backward compatibility during migration.
        """
        # String shorthand: next: "step_name" - allowed, normalized by model
        if isinstance(next_data, str):
            return

        # List format: next: ["step1", "step2"] or [{step: x, when: "..."}] - allowed
        if isinstance(next_data, list):
            for i, item in enumerate(next_data):
                if isinstance(item, str):
                    continue
                if isinstance(item, dict):
                    if "step" not in item:
                        raise ValueError(
                            f"Step '{step_name}': next[{i}] must have 'step' field"
                        )
                    # REJECT expr in next (v10: only when)
                    if "expr" in item:
                        raise ValueError(
                            f"Step '{step_name}': next[{i}]: 'expr' is not allowed. "
                            "Use 'when' for arc guards."
                        )
                    # Validate when if present
                    if "when" in item and not isinstance(item["when"], str):
                        raise ValueError(
                            f"Step '{step_name}': next[{i}].when must be a string"
                        )
            return

        # Canonical router format: {spec: {...}, arcs: [...]}
        if isinstance(next_data, dict):
            # Check for canonical format
            if "arcs" in next_data:
                arcs = next_data["arcs"]
                if not isinstance(arcs, list):
                    raise ValueError(
                        f"Step '{step_name}': next.arcs must be a list"
                    )
                for i, arc in enumerate(arcs):
                    if not isinstance(arc, dict):
                        raise ValueError(
                            f"Step '{step_name}': next.arcs[{i}] must be an object"
                        )
                    if "step" not in arc:
                        raise ValueError(
                            f"Step '{step_name}': next.arcs[{i}] must have 'step' field"
                        )
                    # REJECT expr in arcs
                    if "expr" in arc:
                        raise ValueError(
                            f"Step '{step_name}': next.arcs[{i}]: 'expr' is not allowed. "
                            "Use 'when' for arc guards."
                        )
                    if "when" in arc and not isinstance(arc["when"], str):
                        raise ValueError(
                            f"Step '{step_name}': next.arcs[{i}].when must be a string"
                        )

                # Validate spec if present
                if "spec" in next_data:
                    spec = next_data["spec"]
                    if not isinstance(spec, dict):
                        raise ValueError(
                            f"Step '{step_name}': next.spec must be an object"
                        )
                    if "mode" in spec and spec["mode"] not in ("exclusive", "inclusive"):
                        raise ValueError(
                            f"Step '{step_name}': next.spec.mode must be 'exclusive' or 'inclusive'"
                        )
                return

            # Legacy single target: {step: name, when: "..."}
            if "step" in next_data:
                if "expr" in next_data:
                    raise ValueError(
                        f"Step '{step_name}': next: 'expr' is not allowed. Use 'when'."
                    )
                return

            raise ValueError(
                f"Step '{step_name}': next must have 'arcs' (router) or 'step' (single target)"
            )

        raise ValueError(
            f"Step '{step_name}': 'next' must be a string, list, or router object"
        )

    def _validate_loop_v10(self, loop_data: dict, step_name: str):
        """
        Validate loop in v10 format.
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

            # Validate loop.spec.policy if present
            if "policy" in spec:
                policy = spec["policy"]
                if not isinstance(policy, dict):
                    raise ValueError(
                        f"Step '{step_name}': loop.spec.policy must be an object"
                    )
                if "exec" in policy and policy["exec"] not in ("distributed", "local"):
                    raise ValueError(
                        f"Step '{step_name}': loop.spec.policy.exec must be 'distributed' or 'local'"
                    )

    def _validate_executor(self, executor_data: Any, workflow: list):
        """
        Validate executor configuration in v10 format.
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
