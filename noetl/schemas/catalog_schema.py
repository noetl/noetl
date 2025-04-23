from pydantic import BaseModel
from typing import Optional


class CatalogEntryRequest(BaseModel):
    resource_path: str
    resource_version: str
    resource_type: str
    source: str = "inline"
    resource_location: Optional[str]
    meta: Optional[dict]


class CatalogEntryResponse(BaseModel):
    message: str
