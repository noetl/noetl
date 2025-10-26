"""
Playbook validation module for execution API.

Validates playbook content structure and prepares for execution planning.
Uses core DSL modules for schema validation.
"""

from typing import Dict, Any, Optional
import yaml
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class PlaybookValidationError(Exception):
    """Raised when playbook validation fails."""
    pass


class PlaybookValidator:
    """
    Validates playbook content and structure.
    
    Responsibilities:
    - Parse YAML content
    - Validate required sections (apiVersion, kind, metadata, workflow)
    - Validate workflow has 'start' step
    - Extract metadata (path, name, version)
    """
    
    @staticmethod
    def validate_and_parse(content: str) -> Dict[str, Any]:
        """
        Validate playbook content and parse into structured data.
        
        Args:
            content: YAML playbook content string
            
        Returns:
            Parsed playbook dictionary
            
        Raises:
            PlaybookValidationError: If validation fails
        """
        try:
            playbook = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise PlaybookValidationError(f"Invalid YAML content: {e}")
        
        if not isinstance(playbook, dict):
            raise PlaybookValidationError("Playbook content must be a dictionary")
        
        # Validate required fields
        PlaybookValidator._validate_structure(playbook)
        
        # Validate workflow
        PlaybookValidator._validate_workflow(playbook)
        
        return playbook
    
    @staticmethod
    def _validate_structure(playbook: Dict[str, Any]) -> None:
        """Validate basic playbook structure."""
        required_fields = ["apiVersion", "kind", "metadata"]
        
        for field in required_fields:
            if field not in playbook:
                raise PlaybookValidationError(f"Missing required field: {field}")
        
        # Validate metadata
        metadata = playbook.get("metadata", {})
        if not isinstance(metadata, dict):
            raise PlaybookValidationError("metadata must be a dictionary")
        
        if "name" not in metadata and "path" not in metadata:
            raise PlaybookValidationError("metadata must contain 'name' or 'path'")
        
        # Validate kind
        kind = playbook.get("kind", "").lower()
        if kind not in ["playbook", "tool", "model", "workflow"]:
            logger.warning(f"Unexpected kind: {kind}, expected one of: playbook, tool, model, workflow")
    
    @staticmethod
    def _validate_workflow(playbook: Dict[str, Any]) -> None:
        """Validate workflow structure and required steps."""
        workflow = playbook.get("workflow")
        
        if not workflow:
            raise PlaybookValidationError("Missing required 'workflow' section")
        
        if not isinstance(workflow, list):
            raise PlaybookValidationError("workflow must be a list of steps")
        
        if len(workflow) == 0:
            raise PlaybookValidationError("workflow must contain at least one step")
        
        # Validate each step has required fields
        step_names = set()
        has_start = False
        
        for idx, step in enumerate(workflow):
            if not isinstance(step, dict):
                raise PlaybookValidationError(f"Step at index {idx} must be a dictionary")
            
            step_name = step.get("step")
            if not step_name:
                raise PlaybookValidationError(f"Step at index {idx} missing required 'step' field")
            
            if step_name in step_names:
                raise PlaybookValidationError(f"Duplicate step name: {step_name}")
            
            step_names.add(step_name)
            
            if step_name.lower() == "start":
                has_start = True
        
        if not has_start:
            raise PlaybookValidationError("workflow must contain a 'start' step")
    
    @staticmethod
    def extract_metadata(playbook: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from validated playbook.
        
        Returns:
            Dictionary with path, name, version, and other metadata
        """
        metadata = playbook.get("metadata", {})
        
        path = metadata.get("path") or metadata.get("name")
        name = metadata.get("name") or (path.split("/")[-1] if path else "unknown")
        
        return {
            "path": path,
            "name": name,
            "kind": playbook.get("kind", "Playbook"),
            "apiVersion": playbook.get("apiVersion", "noetl.io/v1"),
            "metadata": metadata
        }
    
    @staticmethod
    def extract_workload(playbook: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract workload section from playbook.
        
        Returns:
            Workload dictionary (empty dict if not present)
        """
        return playbook.get("workload", {})
    
    @staticmethod
    def extract_workbook(playbook: Dict[str, Any]) -> list[Dict[str, Any]]:
        """
        Extract workbook section from playbook.
        
        Returns:
            List of workbook tasks (empty list if not present)
        """
        workbook = playbook.get("workbook")
        if not workbook:
            return []
        
        if not isinstance(workbook, list):
            logger.warning("workbook should be a list, converting to list")
            return [workbook]
        
        return workbook
    
    @staticmethod
    def extract_workflow(playbook: Dict[str, Any]) -> list[Dict[str, Any]]:
        """
        Extract workflow section from playbook.
        
        Returns:
            List of workflow steps
        """
        return playbook.get("workflow", [])
