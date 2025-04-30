from typing import Optional
from pydantic import BaseModel

class EmitEventRequest(BaseModel):
    event_id: str
    event_type: str
    resource_path: str
    resource_version: str
    event_message: Optional[str] = None
    content: Optional[str] = None
    payload: Optional[dict] = None
    context: Optional[dict] = None
    meta: Optional[dict] = None
