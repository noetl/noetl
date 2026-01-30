"""
NoETL DSL v2 Parser

Class-based YAML parser for v2 playbooks with:
- tool.kind validation
- case/when/then structure
- Rejection of old v1 patterns
- Caching support
"""

import yaml
from typing import Any, Optional
from pathlib import Path
from .models import Playbook, Step, ToolSpec, Loop, CaseEntry, WorkbookTask


class DSLParser:
    """
    YAML parser for NoETL DSL v2 playbooks.
    
    Validates:
    - tool.kind pattern (rejects old 'type' field)
    - case/when/then structure
    - Rejects old next.when/then/else patterns
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
            ValueError: If YAML is invalid or uses old v1 patterns
        """
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")
        
        # Validate v2 structure
        self._validate_v2_structure(data)
        
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
    
    def _validate_v2_structure(self, data: dict[str, Any]):
        """
        Validate that data uses v2 structure.
        Reject old v1 patterns.
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
        
        # Validate workflow steps
        workflow = data.get("workflow", [])
        if not workflow:
            raise ValueError("Workflow cannot be empty")
        
        for step_data in workflow:
            self._validate_step_v2(step_data)
    
    def _validate_step_v2(self, step_data: dict[str, Any]):
        """
        Validate step uses v2 structure.
        Reject old v1 patterns.

        Note: 'tool' is optional when step has 'case' (case-driven execution).
        """
        step_name = step_data.get("step", "<unknown>")

        # Check for old 'type' field
        if "type" in step_data:
            raise ValueError(
                f"Step '{step_name}': 'type' field is not allowed in v2. "
                "Use 'tool.kind' instead."
            )

        has_case = "case" in step_data
        has_tool = "tool" in step_data

        # Tool is optional when step has case (case-driven execution)
        # But if tool is present, it must be valid
        if has_tool:
            tool_data = step_data["tool"]
            if not isinstance(tool_data, dict):
                raise ValueError(
                    f"Step '{step_name}': 'tool' must be an object with 'kind' field"
                )

            if "kind" not in tool_data:
                raise ValueError(
                    f"Step '{step_name}': 'tool' must have 'kind' field (e.g., http, postgres, python)"
                )
        elif not has_case:
            # No tool and no case - invalid step
            raise ValueError(f"Step '{step_name}': Missing 'tool' field (required unless step has 'case')")
        
        # Check for old next patterns
        next_data = step_data.get("next")
        if next_data:
            self._validate_next_v2(next_data, step_name)
        
        # Validate case structure if present
        case_data = step_data.get("case")
        if case_data:
            self._validate_case_v2(case_data, step_name)
    
    def _validate_next_v2(self, next_data: Any, step_name: str):
        """
        Validate next field - reject old when/then/else patterns.
        """
        if isinstance(next_data, list):
            for item in next_data:
                if isinstance(item, dict):
                    # Check for old conditional patterns
                    if any(key in item for key in ["when", "then", "else"]):
                        raise ValueError(
                            f"Step '{step_name}': Conditional 'next' with when/then/else is not allowed. "
                            "Use 'case/when/then' for conditional transitions."
                        )
    
    def _validate_case_v2(self, case_data: list, step_name: str):
        """
        Validate case entries have when/then structure.

        Supports two forms:
        - when: "{{ condition }}" with then: - Standard conditional
        - else: (no when) - Fallback when no conditions matched in inclusive mode
        """
        if not isinstance(case_data, list):
            raise ValueError(
                f"Step '{step_name}': 'case' must be a list of when/then entries"
            )

        for i, entry in enumerate(case_data):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Step '{step_name}': case[{i}] must be an object"
                )

            has_when = "when" in entry
            has_then = "then" in entry
            has_else = "else" in entry

            # Support else: clause (no when required)
            if has_else and not has_when:
                # else: clause - then is in 'else' key, not 'then'
                continue

            if not has_when:
                raise ValueError(
                    f"Step '{step_name}': case[{i}] missing 'when' field"
                )

            if not has_then:
                raise ValueError(
                    f"Step '{step_name}': case[{i}] missing 'then' field"
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


# Backward compatibility wrapper (if needed for migration)
class PlaybookParserV2:
    """Wrapper for backward compatibility during migration."""
    
    def __init__(self):
        self.parser = DSLParser()
    
    def parse(self, yaml_content: str) -> Playbook:
        return self.parser.parse(yaml_content)
    
    def parse_file(self, file_path: str | Path) -> Playbook:
        return self.parser.parse_file(file_path)
