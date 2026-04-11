from __future__ import annotations

from .common import *
from .validation import ParserValidationMixin


class DSLParser(ParserValidationMixin):
    """
    YAML parser for NoETL DSL v2 playbooks (canonical v10 format).

    Validates:
    - tool.kind pattern (rejects old 'type' field)
    - tool as single object or pipeline list
    - task.spec.policy.rules for output handling (rejects eval)
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

        self._validate_canonical_v10(data)
        playbook = Playbook(**data)

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
