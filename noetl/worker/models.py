from __future__ import annotations

import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActionConfig(BaseModel):
    """Validated representation of a task configuration."""

    tool: str
    name: Optional[str] = None
    args: Dict[str, Any] = Field(default_factory=dict)
    sink: Optional[Dict[str, Any]] = None
    retry: Optional[Any] = None

    model_config = ConfigDict(extra="allow", validate_assignment=True)

    @field_validator("tool")
    @classmethod
    def _validate_tool(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("Task configuration must include a non-empty 'tool' field")
        return normalized

    @field_validator("args", mode="before")
    @classmethod
    def _ensure_args_dict(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise TypeError("'args' must be a dictionary of task arguments")
    
    @model_validator(mode="before")
    @classmethod
    def _extract_data_to_args(cls, values: Any) -> Any:
        """Extract 'data' field from task config and merge into 'args' for Python plugin compatibility."""
        if not isinstance(values, dict):
            return values
        
        # If there's a 'data' field, merge it into 'args'
        data = values.get("data")
        if data and isinstance(data, dict):
            args = values.get("args", {})
            if not isinstance(args, dict):
                args = {}
            # Merge data into args (data takes precedence)
            merged_args = {**args, **data}
            values["args"] = merged_args
            
            # Log for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.critical(f"ActionConfig: Merged data into args. args_before={args}, data={list(data.keys())}, args_after={list(merged_args.keys())}")
        
        return values


class QueueJob(BaseModel):
    """Queue job payload fetched from the server."""

    queue_id: int
    id: Optional[int] = None
    catalog_id: str
    execution_id: str
    node_id: Optional[str] = None
    action: ActionConfig
    context: Dict[str, Any]
    meta: Optional[Dict[str, Any]] = None
    attempts: int = 0
    max_attempts: int = 1
    run_mode: Optional[str] = None

    model_config = ConfigDict(extra="allow", validate_assignment=True)

    @field_validator("catalog_id", "execution_id", mode="before")
    @classmethod
    def _ensure_string_ids(cls, value: Any) -> str:
        if value is None:
            raise ValueError("catalog_id and execution_id must be provided")
        return str(value)

    @field_validator("context")
    @classmethod
    def _ensure_context_dict(cls, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        raise TypeError("Job context must be a dictionary")

    @field_validator("meta", mode="before")
    @classmethod
    def _parse_meta(cls, value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        raise TypeError("Job metadata must be a dictionary or JSON string")

    @property
    def effective_node_id(self) -> str:
        return self.node_id or f"job_{self.queue_id}"

    @property
    def step_name(self) -> Optional[str]:
        step_name = self.context.get("step_name")
        return step_name if isinstance(step_name, str) else None

    @property
    def use_process(self) -> bool:
        return (self.run_mode or "").lower() == "process"

    def loop_metadata(self) -> Dict[str, Any]:
        loop = self.context.get("_loop")
        if not isinstance(loop, dict):
            return {}
        return {
            "loop_id": loop.get("loop_id"),
            "loop_name": loop.get("loop_name"),
            "iterator": loop.get("iterator"),
            "current_index": loop.get("current_index"),
            "current_item": loop.get("current_item"),
            "items_count": loop.get("items_count"),
        }
    @field_validator("action", mode="before")
    @classmethod
    def _parse_action(cls, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        raise TypeError("Job action must be a dictionary or JSON string")
