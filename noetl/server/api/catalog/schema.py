"""
NoETL Catalog API Schemas - Request/Response models for catalog endpoints.

Provides unified schema design for catalog resource lookup and management.
Supports multiple lookup strategies: catalog_id, path + version.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import model_validator, Field, field_validator

from noetl.core.common import AppBaseModel, transform
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class CatalogEntriesRequest(AppBaseModel):
    """Request schema for listing catalog entries."""
    resource_type: Optional[str] = Field(
        default=None,
        description="Filter by resource kind (e.g., 'Playbook', 'Tool', 'Model')",
        example="Playbook"
    )


class CatalogEntryRequest(AppBaseModel):
    """
    Catalog resource lookup request schema.
    
    **Lookup Strategies** (priority order):
    1. `catalog_id`: Direct catalog entry lookup (highest priority)
    2. `path` + `version`: Version-controlled path-based lookup
    
    At least one identifier (catalog_id or path) must be provided.
    """
    
    catalog_id: Optional[str] = Field(
        default=None,
        description="Direct catalog entry ID",
        example="478775660589088776"
    )
    path: Optional[str] = Field(
        default=None,
        description="Catalog path for version-controlled lookup",
        example="tests/fixtures/playbooks/hello_world"
    )
    version: Optional[str | int] = Field(
        default=None,
        description="Version identifier (semantic version or 'latest'). Defaults to latest if omitted",
        example="1"
    )
    
    @field_validator('catalog_id', 'path', mode='before')
    @classmethod
    def coerce_ids_to_string(cls, v):
        """Coerce integers or other types to strings for ID fields."""
        if v is None:
            return v
        return str(v)
    
    @model_validator(mode='after')
    def validate_identifiers(self) -> "CatalogEntryRequest":
        """Validate that at least one identifier is provided."""
        if not self.catalog_id and not self.path:
            raise ValueError(
                "At least one identifier must be provided: catalog_id or path"
            )
        return self


class CatalogEntry(AppBaseModel):
    """
    Complete catalog entry data model from database.
    
    Represents the full catalog table record with all fields.
    Used internally by the service layer when fetching from database.
    """
    
    catalog_id: str
    path: str
    version: int
    kind: str
    content: Optional[str] = None
    layout: Optional[dict[str, Any]] = None
    payload: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    
    @field_validator('catalog_id', 'path', mode='before')
    @classmethod
    def coerce_ids_to_string(cls, v):
        """Coerce integers or other types to strings for ID fields."""
        if v is None:
            return v
        return str(v)
    
    @field_validator("version", mode="before")
    @classmethod
    def parse_version(cls, value: Any) -> Optional[int]:
        """Parse version to integer."""
        if value in (None, ""):
            return None
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Version must be an integer") from exc
    
    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Optional[str]) -> Optional[str]:
        """Validate and clean path."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Path cannot be empty")
        return cleaned
    
    model_config = {
        "populate_by_name": True,  # Allow both field name and alias
    }


# class CatalogEntry(AppBaseModel):
#     """Response model for a single catalog entry"""
#     catalog_id: str
#     path: str
#     kind: str
#     version: int
#     content: str | None = None
#     layout: dict[str, Any] | None = None
#     payload: dict[str, Any] | None = None
#     meta: dict[str, Any] | None = None
#     created_at: datetime


class CatalogEntries(AppBaseModel):
    """Response model for list of catalog entries endpoint"""
    entries: list[CatalogEntry]
