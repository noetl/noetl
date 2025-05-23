from pydantic import BaseModel, Field
from typing import Optional, Dict


class RegisterRequest(BaseModel):
    content_base64: str

class CatalogEntryRequest(BaseModel):
    path: str
    version: str
    resource_type: str
    source: str = "inline"
    location: Optional[str]
    content: Optional[str]
    template: Optional[str]
    payload: Dict = Field(..., description="JSON payload required")
    meta: Optional[Dict]


class CatalogEntryResponse(BaseModel):
    message: str

