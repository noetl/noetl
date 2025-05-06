from typing import Optional, List, Dict
from pydantic import BaseModel, root_validator
from datetime import datetime



class EmitEventRequest(BaseModel):
    event_id: Optional[str] = None
    parent_id: Optional[str] = None
    registry_id: Optional[str] = None
    execution_id: Optional[str] = None
    context_id: Optional[str] = None
    resource_path: Optional[str] = None
    resource_version: Optional[str] = None
    event_type: str
    status: Optional[str] = "READY"
    state: Optional[str] = None
    event_message: Optional[str] = None
    content: Optional[str] = None
    payload: Optional[dict] = None
    meta: Optional[dict] = None
    labels: Optional[List[str]] = None
    tags: Optional[Dict[str, str]] = None
    timestamp: Optional[datetime] = None


    # @root_validator
    # def validate_identifiers(cls, values):
    #     identifiers = [values.get("event_id"), values.get("parent_id"), values.get("registry_id"),
    #                    values.get("execution_id"), values.get("context_id")]
    #     if not any(identifiers):
    #         raise ValueError("At least one identifier (event_id, parent_id, registry_id, execution_id, or context_id) must be provided.")
    #     return values