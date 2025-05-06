from typing import Optional, List, Dict
from datetime import datetime, timezone
from pydantic import BaseModel

class RegistryRequest(BaseModel):
    event_id: Optional[str] = None
    resource_path: str
    resource_version: str
    namespace: Optional[dict] = {}
    status: str = "PENDING"
    payload: dict
    meta: Optional[dict] = None
    labels: Optional[List[str]] = []
    tags: Optional[Dict[str, str]] = {}


class RegistryResponse(BaseModel):
    registry_id: str
    event_id: Optional[str] = None
    namespace: Optional[dict] = None
    status: str
    payload: dict
    meta: Optional[dict] = None
    labels: Optional[List[str]] = None
    tags: Optional[Dict[str, str]] = None
    timestamp: datetime