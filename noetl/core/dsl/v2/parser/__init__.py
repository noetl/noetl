"""
NoETL DSL v2 parser package.
"""

from pathlib import Path
from typing import Optional

from ..models import Playbook
from .core import DSLParser

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


__all__ = [
    "DSLParser",
    "get_parser",
    "parse_playbook",
    "parse_playbook_file",
    "validate_playbook",
    "validate_playbook_file",
]
