from typing import Optional, List, Dict
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class WorkloadRequest(BaseModel):
    event_id: Optional[str] = None
    resource_path: str
    resource_version: str
    namespace: Optional[dict] = Field(default_factory=dict)
    status: str = "PENDING"
    payload: dict
    meta: Optional[dict] = None
    labels: Optional[List[str]] = Field(default_factory=list)
    tags: Optional[Dict[str, str]] = Field(default_factory=dict)


class WorkloadResponse(BaseModel):
    workload_id: str
    event_id: Optional[str] = None
    namespace: Optional[dict] = None
    status: str
    payload: dict
    meta: Optional[dict] = None
    labels: Optional[List[str]] = None
    tags: Optional[Dict[str, str]] = None
    timestamp: datetime
