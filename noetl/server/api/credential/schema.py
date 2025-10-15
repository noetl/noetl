"""
NoETL Credential API Schemas - Request/Response models for credential management.

Supports:
- Credential creation and updates
- Credential listing and retrieval
- GCP token generation
"""

from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_serializer


class CredentialCreateRequest(BaseModel):
    """Request schema for creating or updating credentials."""
    
    name: str = Field(
        ...,
        description="Unique credential name",
        min_length=1
    )
    type: str = Field(
        default="generic",
        description="Credential type (e.g., httpBearerAuth, serviceAccount, postgres)",
        alias="credential_type"
    )
    data: Dict[str, Any] = Field(
        ...,
        description="Secret data to be encrypted (passwords, keys, tokens)"
    )
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata (not encrypted)"
    )
    tags: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Tags for organization (comma-separated string or list)"
    )
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description"
    )
    
    @field_validator('name', mode='before')
    @classmethod
    def strip_name(cls, v):
        """Strip whitespace from name."""
        if v:
            return str(v).strip()
        return v
    
    @field_validator('type', mode='before')
    @classmethod
    def normalize_type(cls, v):
        """Normalize credential type."""
        if v:
            return str(v).strip()
        return "generic"
    
    @field_validator('tags', mode='before')
    @classmethod
    def normalize_tags(cls, v):
        """Normalize tags to list format."""
        if v is None:
            return None
        if isinstance(v, str):
            return [t.strip() for t in v.split(',') if t and t.strip()]
        if isinstance(v, list):
            return [str(t) for t in v]
        return [str(v)]
    
    model_config = {
        "populate_by_name": True,
    }


class CredentialResponse(BaseModel):
    """Response schema for credential operations."""
    
    id: str = Field(
        ...,
        description="Credential ID"
    )
    name: str = Field(
        ...,
        description="Credential name"
    )
    type: str = Field(
        ...,
        description="Credential type",
        alias="credential_type"
    )
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadata"
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Tags"
    )
    description: Optional[str] = Field(
        default=None,
        description="Description"
    )
    created_at: str = Field(
        ...,
        description="Creation timestamp (ISO 8601)"
    )
    updated_at: str = Field(
        ...,
        description="Last update timestamp (ISO 8601)"
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Decrypted credential data (only included if requested)"
    )
    
    @field_validator('id', mode='before')
    @classmethod
    def coerce_id_to_string(cls, v):
        """Coerce ID to string."""
        if v is None:
            return v
        return str(v)
    
    @field_validator('created_at', 'updated_at', mode='before')
    @classmethod
    def coerce_datetime_to_iso(cls, v):
        """Coerce datetime to ISO 8601 string."""
        if v is None:
            return v
        if hasattr(v, 'isoformat'):
            return v.isoformat()
        return str(v)
    
    @model_serializer(mode='wrap')
    def serialize_model(self, serializer):
        """Use field names (not aliases) for output."""
        data = serializer(self)
        # Ensure 'type' is used instead of alias 'credential_type' in output
        if 'credential_type' in data:
            data['type'] = data.pop('credential_type')
        return data
    
    model_config = {
        "populate_by_name": True,
    }


class CredentialListResponse(BaseModel):
    """Response schema for listing credentials."""
    
    items: List[CredentialResponse] = Field(
        default_factory=list,
        description="List of credentials"
    )
    filter: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Applied filters"
    )


class GCPTokenRequest(BaseModel):
    """Request schema for obtaining GCP access tokens."""
    
    scopes: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="OAuth2 scopes (default: cloud-platform)"
    )
    credentials_path: Optional[str] = Field(
        default=None,
        description="Path to service account JSON file"
    )
    use_metadata: bool = Field(
        default=False,
        description="Use GCE metadata server"
    )
    service_account_secret: Optional[str] = Field(
        default=None,
        description="GCP Secret Manager path to service account JSON"
    )
    credentials_info: Optional[Union[Dict[str, Any], str]] = Field(
        default=None,
        description="Service account JSON as object or string"
    )
    credential: Optional[Union[str, int]] = Field(
        default=None,
        description="Stored credential name or ID to use",
        alias="credential_name"
    )
    credential_id: Optional[Union[str, int]] = Field(
        default=None,
        description="Stored credential ID (alternative to credential)"
    )
    store_as: Optional[str] = Field(
        default=None,
        description="Name to store issued token as credential"
    )
    store_type: Optional[str] = Field(
        default="httpBearerAuth",
        description="Credential type when storing token"
    )
    store_meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadata when storing token"
    )
    store_description: Optional[str] = Field(
        default=None,
        description="Description when storing token"
    )
    store_tags: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Tags when storing token"
    )
    
    model_config = {
        "populate_by_name": True,
    }


class GCPTokenResponse(BaseModel):
    """Response schema for GCP token generation."""
    
    access_token: str = Field(
        ...,
        description="OAuth2 access token"
    )
    token_expiry: Optional[str] = Field(
        default=None,
        description="Token expiration time (ISO 8601)"
    )
    scopes: Optional[List[str]] = Field(
        default=None,
        description="Granted scopes"
    )
