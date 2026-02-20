"""
NoETL Catalog API Schemas - Request/Response models for catalog endpoints.

Provides unified schema design for catalog resource lookup and management.
Supports multiple lookup strategies: catalog_id, path + version.
"""

import base64
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


class CatalogRegisterRequest(AppBaseModel):
    """Request model for registering a new catalog entry"""
    content: str = Field(
        description="YAML content of the catalog resource (accepts base64 encoded or plain text)",
        example="apiVersion: noetl.io/v1\nkind: Playbook\nmetadata:\n  name: example\n  path: tests/fixtures/playbooks/hello_world/hello_world"
    )
    resource_type: str = Field(
        default="Playbook",
        description="Type of resource to register (e.g., 'Playbook', 'Tool', 'Model')",
        example="Playbook"
    )

    @field_validator('content', mode="before")
    @classmethod
    def decode_data(cls, val):
        try:
            return base64.b64decode(val).decode("utf-8")
        except Exception:
            return val


class CatalogRegisterResponse(AppBaseModel):
    """Response model for catalog registration endpoint"""
    status: str = Field(
        description="Operation status",
        example="success"
    )
    message: str = Field(
        description="Human-readable result message",
        example="Resource 'tests/fixtures/playbooks/hello_world/hello_world' version '1' registered."
    )
    path: str = Field(
        description="Catalog path of the registered resource",
        example="tests/fixtures/playbooks/hello_world/hello_world"
    )
    version: int = Field(
        description="Version number of the registered resource",
        example=1
    )
    catalog_id: str = Field(
        description="Unique catalog entry identifier",
        example="478775660589088776"
    )
    kind: str = Field(
        description="Resource type/kind",
        example="Playbook"
    )


class ExplainPlaybookWithAIRequest(AppBaseModel):
    """Request schema for playbook explanation via AI playbook."""

    catalog_id: Optional[str] = Field(
        default=None,
        description="Catalog ID of target playbook (optional if path provided)",
    )
    path: Optional[str] = Field(
        default=None,
        description="Path of target playbook (optional if catalog_id provided)",
    )
    version: Optional[str | int] = Field(
        default="latest",
        description="Target version (default latest)",
    )
    explanation_playbook_path: str = Field(
        default="ops/playbook_ai_explain",
        description="Playbook path used to generate explanation",
    )
    gcp_auth_credential: Optional[str] = Field(
        default=None,
        description="Optional override for analyzer workload.gcp_auth",
    )
    openai_secret_path: Optional[str] = Field(
        default=None,
        description="Optional override for analyzer workload.openai_secret_path",
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model used by explain playbook",
    )
    timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=1200,
        description="Max time to wait for explain playbook completion",
    )
    poll_interval_ms: int = Field(
        default=1500,
        ge=200,
        le=10000,
        description="Polling interval while waiting for explain playbook",
    )

    @model_validator(mode="after")
    def validate_identifiers(self) -> "ExplainPlaybookWithAIRequest":
        if not self.catalog_id and not self.path:
            raise ValueError("Either catalog_id or path must be provided")
        return self


class ExplainPlaybookWithAIResponse(AppBaseModel):
    """Response schema for playbook explanation via AI playbook."""

    target_path: str = Field(..., description="Target playbook path")
    target_version: Optional[int] = Field(None, description="Target playbook version")
    generated_at: datetime = Field(..., description="UTC timestamp when explanation finished")
    ai_playbook_path: str = Field(..., description="AI explainer playbook path")
    ai_execution_id: Optional[str] = Field(None, description="Execution ID of AI explainer playbook")
    ai_execution_status: str = Field(..., description="AI explainer execution status")
    ai_report: dict[str, Any] = Field(default_factory=dict, description="Parsed AI explanation report")
    ai_raw_output: dict[str, Any] = Field(default_factory=dict, description="Raw AI output payload")


class GeneratePlaybookWithAIRequest(AppBaseModel):
    """Request schema for AI-generated playbook draft."""

    prompt: str = Field(..., description="Natural language prompt describing the playbook to generate")
    generator_playbook_path: str = Field(
        default="ops/playbook_ai_generate",
        description="Playbook path used to generate draft playbook",
    )
    gcp_auth_credential: Optional[str] = Field(
        default=None,
        description="Optional override for generator workload.gcp_auth",
    )
    openai_secret_path: Optional[str] = Field(
        default=None,
        description="Optional override for generator workload.openai_secret_path",
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model used by generator playbook",
    )
    timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=1200,
        description="Max time to wait for generator playbook completion",
    )
    poll_interval_ms: int = Field(
        default=1500,
        ge=200,
        le=10000,
        description="Polling interval while waiting for generator playbook",
    )

    @field_validator("prompt", mode="before")
    @classmethod
    def validate_prompt(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("prompt cannot be empty")
        return text


class GeneratePlaybookWithAIResponse(AppBaseModel):
    """Response schema for AI-generated playbook draft."""

    generated_at: datetime = Field(..., description="UTC timestamp when generation finished")
    ai_playbook_path: str = Field(..., description="AI generator playbook path")
    ai_execution_id: Optional[str] = Field(None, description="Execution ID of AI generator playbook")
    ai_execution_status: str = Field(..., description="AI generator execution status")
    generated_playbook: str = Field(..., description="Generated playbook YAML draft")
    ai_report: dict[str, Any] = Field(default_factory=dict, description="Parsed AI generation report")
    ai_raw_output: dict[str, Any] = Field(default_factory=dict, description="Raw AI output payload")
        
