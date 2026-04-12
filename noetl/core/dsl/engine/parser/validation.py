from __future__ import annotations

from .common import *


class ParserValidationMixin:
    # =========================================================================
    # Canonical v10 Validation
    # =========================================================================

    def _validate_canonical_v10(self, data: dict[str, Any]):
        """
        Validate that data uses canonical v10 structure.
        Reject all deprecated patterns.
        """
        api_version = data.get("apiVersion", "")
        valid_versions = ("noetl.io/v2", "noetl.io/v10")
        if api_version not in valid_versions:
            raise ValueError(
                f"Invalid apiVersion: {api_version}. "
                f"Playbooks must use one of: {valid_versions}"
            )

        if data.get("kind") != "Playbook":
            raise ValueError("kind must be 'Playbook'")

        if "vars" in data:
            raise ValueError(
                "Root 'vars' is not allowed in canonical v10. "
                "Use 'ctx' (execution-scoped) and 'iter' (iteration-scoped) via policy mutations."
            )

        if "executor" in data:
            self._validate_executor(data["executor"], data.get("workflow", []))

        workflow = data.get("workflow", [])
        if not workflow:
            raise ValueError("Workflow cannot be empty")

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
                    if "name" in task_def and "kind" in task_def:
                        labels.add(task_def["name"])
                    elif "kind" in task_def and "name" not in task_def:
                        labels.add(f"task_{i}")
        return labels

    def _validate_step_v10(self, step_data: dict[str, Any], all_task_labels: set[str]):
        """
        Validate step uses canonical v10 structure.
        Reject deprecated patterns.
        """
        step_name = step_data.get("step", "<unknown>")

        if "when" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'when' field is not allowed on step in v10. "
                "Use 'step.spec.policy.admit.rules' for admission control."
            )

        if "case" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'case' blocks are not allowed in v10. "
                "Use 'step.spec.policy.admit.rules' for admission, "
                "'task.spec.policy.rules' for output handling, "
                "and 'next.arcs[].when' for routing."
            )

        if "type" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'type' field is not allowed. "
                "Use 'tool.kind' instead."
            )

        if "tool" not in step_data:
            raise ValueError(
                f"Step '{step_name}': Missing 'tool' field. "
                "Every step must have a tool (use 'kind: noop' for pure routing)."
            )

        tool_data = step_data["tool"]
        self._validate_tool_v10(tool_data, step_name, all_task_labels)

        if "spec" in step_data:
            self._validate_step_spec_v10(step_data["spec"], step_name)

        if "next" in step_data:
            self._validate_next_router_v10(step_data["next"], step_name)

        if "loop" in step_data:
            self._validate_loop_v10(step_data["loop"], step_name)

    def _validate_tool_v10(self, tool_data: Any, step_name: str, all_task_labels: set[str]):
        """
        Validate tool field in canonical v10 format.

        REJECTS: eval (use task.spec.policy.rules instead)
        """
        if isinstance(tool_data, dict):
            if "kind" not in tool_data:
                raise ValueError(
                    f"Step '{step_name}': tool must have 'kind' field "
                    "(e.g., http, postgres, python, noop)"
                )
            if "eval" in tool_data:
                raise ValueError(
                    f"Step '{step_name}': 'eval' is not allowed in v10. "
                    "Use 'task.spec.policy.rules' for output handling instead."
                )
            if "spec" in tool_data:
                self._validate_task_spec_v10(tool_data["spec"], step_name, "tool", all_task_labels)

        elif isinstance(tool_data, list):
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

            if "name" in task_def and "kind" in task_def:
                label = task_def["name"]
                task_config = {k: v for k, v in task_def.items() if k != "name"}
            elif "kind" in task_def and "name" not in task_def:
                label = f"task_{i}"
                task_config = task_def
            else:
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

            if "eval" in task_config:
                raise ValueError(
                    f"Step '{step_name}': tool[{i}].{label}: 'eval' is not allowed in v10. "
                    "Use 'spec.policy.rules' for output handling instead."
                )

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

            if "else" in rule:
                else_data = rule["else"]
                if isinstance(else_data, dict) and "then" in else_data:
                    self._validate_then_v10(
                        else_data["then"], step_name, f"{location}.rules[{i}].else",
                        valid_actions, all_task_labels
                    )
                continue

            if "expr" in rule:
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}]: 'expr' is not allowed in v10. "
                    "Use 'when' as the ONLY conditional keyword."
                )

            if "when" not in rule:
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}] must have 'when' or be an 'else' clause"
                )

            if not isinstance(rule["when"], str):
                raise ValueError(
                    f"Step '{step_name}': {location}.rules[{i}].when must be a Jinja2 expression string"
                )

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

        if "allow" in then_data and "do" not in then_data:
            return

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

        if "next_mode" in spec_data:
            raise ValueError(
                f"Step '{step_name}': 'spec.next_mode' is not allowed in v10. "
                "Use 'next.spec.mode' for routing mode."
            )

        if "policy" in spec_data:
            policy = spec_data["policy"]
            if not isinstance(policy, dict):
                raise ValueError(
                    f"Step '{step_name}': spec.policy must be an object"
                )

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

                if "expr" in rule:
                    raise ValueError(
                        f"Step '{step_name}': spec.policy.admit.rules[{i}]: "
                        "'expr' is not allowed in v10. Use 'when'."
                    )

                if "when" not in rule:
                    raise ValueError(
                        f"Step '{step_name}': spec.policy.admit.rules[{i}] "
                        "must have 'when' or be an 'else' clause"
                    )

                if "then" not in rule:
                    raise ValueError(
                        f"Step '{step_name}': spec.policy.admit.rules[{i}] "
                        "must have 'then' field"
                    )

    def _validate_next_router_v10(self, next_data: Any, step_name: str):
        """
        Validate next router in v10 format.

        Canonical format: {spec: {...}, arcs: [...]}
        """
        if isinstance(next_data, str) or isinstance(next_data, list):
            raise ValueError(
                f"Step '{step_name}': next must use canonical router format "
                "{spec: {...}, arcs: [...]}."
            )

        if isinstance(next_data, dict):
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
                    if "expr" in arc:
                        raise ValueError(
                            f"Step '{step_name}': next.arcs[{i}]: 'expr' is not allowed. "
                            "Use 'when' for arc guards."
                        )
                    if "when" in arc and not isinstance(arc["when"], str):
                        raise ValueError(
                            f"Step '{step_name}': next.arcs[{i}].when must be a string"
                        )

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

            if "step" in next_data:
                raise ValueError(
                    f"Step '{step_name}': next must use canonical router format "
                    "{spec: {...}, arcs: [...]}."
                )

            raise ValueError(f"Step '{step_name}': next must define 'arcs'")

        raise ValueError(
            f"Step '{step_name}': 'next' must be a router object"
        )

    def _validate_loop_v10(self, loop_data: dict, step_name: str):
        """
        Validate loop in v10 format.
        """
        if not isinstance(loop_data, dict):
            raise ValueError(
                f"Step '{step_name}': 'loop' must be an object"
            )

        if "in" not in loop_data:
            raise ValueError(
                f"Step '{step_name}': loop must have 'in' field"
            )

        if "iterator" not in loop_data:
            raise ValueError(
                f"Step '{step_name}': loop must have 'iterator' field"
            )

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

        if "profile" in executor_data:
            valid_profiles = ("local", "distributed", "auto")
            if executor_data["profile"] not in valid_profiles:
                raise ValueError(
                    f"executor.profile must be one of: {valid_profiles}"
                )

        if "requires" in executor_data:
            requires = executor_data["requires"]
            if not isinstance(requires, dict):
                raise ValueError("executor.requires must be an object")

            if "tools" in requires and not isinstance(requires["tools"], list):
                raise ValueError("executor.requires.tools must be a list")

            if "features" in requires and not isinstance(requires["features"], list):
                raise ValueError("executor.requires.features must be a list")

        if "spec" in executor_data:
            spec = executor_data["spec"]
            if not isinstance(spec, dict):
                raise ValueError("executor.spec must be an object")

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

            if "no_next_is_error" in spec and not isinstance(spec["no_next_is_error"], bool):
                raise ValueError("executor.spec.no_next_is_error must be a boolean")
