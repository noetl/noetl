"""
NoETL DSL v2 Parser - Clean YAML to v2 models.

NO BACKWARD COMPATIBILITY with v1.
"""

from pathlib import Path
from typing import Any, Dict, Union

import yaml

from noetl.core.logger import setup_logger

from .models import Playbook

logger = setup_logger(__name__, include_location=True)


class PlaybookParserV2:
    """Parse YAML playbooks into v2 Pydantic models."""
    
    @staticmethod
    def parse_yaml(yaml_content: str) -> Playbook:
        """
        Parse YAML string into Playbook v2 model.
        
        Args:
            yaml_content: YAML string content
            
        Returns:
            Validated Playbook v2 instance
            
        Raises:
            ValidationError: If YAML structure doesn't match v2 schema
            yaml.YAMLError: If YAML syntax is invalid
        """
        try:
            data = yaml.safe_load(yaml_content)
            if not data:
                raise ValueError("Empty YAML content")
            
            return Playbook.model_validate(data)
            
        except yaml.YAMLError as e:
            logger.error(f"YAML syntax error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to parse playbook: {e}")
            raise
    
    @staticmethod
    def parse_file(file_path: Union[str, Path]) -> Playbook:
        """
        Parse YAML file into Playbook v2 model.
        
        Args:
            file_path: Path to YAML file
            
        Returns:
            Validated Playbook v2 instance
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Playbook file not found: {file_path}")
        
        with open(path, "r", encoding="utf-8") as f:
            yaml_content = f.read()
        
        logger.info(f"Parsing playbook from: {file_path}")
        return PlaybookParserV2.parse_yaml(yaml_content)
    
    @staticmethod
    def to_dict(playbook: Playbook) -> Dict[str, Any]:
        """
        Convert Playbook v2 model back to dictionary.
        
        Args:
            playbook: Validated Playbook v2 instance
            
        Returns:
            Dictionary representation suitable for YAML serialization
        """
        return playbook.model_dump(by_alias=True, exclude_none=True)
    
    @staticmethod
    def to_yaml(playbook: Playbook) -> str:
        """
        Convert Playbook v2 model to YAML string.
        
        Args:
            playbook: Validated Playbook v2 instance
            
        Returns:
            YAML string
        """
        data = PlaybookParserV2.to_dict(playbook)
        return yaml.dump(data, sort_keys=False, default_flow_style=False)
    
    @staticmethod
    def validate_file(file_path: Union[str, Path]) -> bool:
        """
        Validate a playbook file without fully processing it.
        
        Args:
            file_path: Path to YAML file
            
        Returns:
            True if valid, False otherwise
        """
        try:
            PlaybookParserV2.parse_file(file_path)
            logger.info(f"Playbook validation successful: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Playbook validation failed: {e}")
            return False


# Convenience functions
def parse_playbook_yaml(yaml_content: str) -> Playbook:
    """Parse YAML string to Playbook v2."""
    return PlaybookParserV2.parse_yaml(yaml_content)


def parse_playbook_file(file_path: Union[str, Path]) -> Playbook:
    """Parse YAML file to Playbook v2."""
    return PlaybookParserV2.parse_file(file_path)


def validate_playbook_file(file_path: Union[str, Path]) -> bool:
    """Validate a playbook file."""
    return PlaybookParserV2.validate_file(file_path)
