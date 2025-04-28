from pydantic import BaseModel, Field
from typing import Optional, Dict


class RegisterRequest(BaseModel):
    content_base64: str

class CatalogEntryRequest(BaseModel):
    resource_path: str
    resource_version: str
    resource_type: str
    source: str = "inline"
    resource_location: Optional[str]
    payload: Dict = Field(..., description="JSON payload required")
    meta: Optional[Dict]


class CatalogEntryResponse(BaseModel):
    message: str

