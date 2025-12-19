"""
Keychain API Pydantic schemas.

Request/response models for keychain management endpoints.
"""

from typing import Any, Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class KeychainSetRequest(BaseModel):
    """Request body for POST /api/keychain/{catalog_id}/{keychain_name}."""
    token_data: Dict[str, Any] = Field(..., description="Token/credential data to cache (e.g., access_token, username, password)")
    credential_type: str = Field(..., description="Credential type (e.g., 'oauth2_client_credentials', 'bearer', 'postgres', 'snowflake')")
    cache_type: str = Field(default="token", description="Cache type: 'token' or 'secret'")
    scope_type: str = Field(default="global", description="Scope type: 'local', 'global', or 'shared'")
    execution_id: Optional[int] = Field(None, description="Execution ID for local/shared scope")
    parent_execution_id: Optional[int] = Field(None, description="Parent execution ID for cleanup tracking")
    ttl_seconds: Optional[int] = Field(None, description="TTL in seconds (overrides expires_at)")
    expires_at: Optional[datetime] = Field(None, description="Explicit expiration timestamp")
    auto_renew: bool = Field(default=False, description="Enable automatic token renewal on expiration")
    renew_config: Optional[Dict[str, Any]] = Field(None, description="Configuration for automatic renewal (endpoint, method, auth, etc.)")


class KeychainSetResponse(BaseModel):
    """Response for POST /api/keychain/{catalog_id}/{keychain_name}."""
    status: str = Field(..., description="Operation status: 'success' or 'error'")
    message: str = Field(..., description="Result message")
    keychain_name: str = Field(..., description="Keychain entry name")
    catalog_id: int = Field(..., description="Catalog ID")
    cache_key: str = Field(..., description="Generated cache key")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")
    ttl_seconds: Optional[int] = Field(None, description="TTL in seconds")
    auto_renew: bool = Field(..., description="Auto-renewal enabled")


class KeychainGetResponse(BaseModel):
    """Response for GET /api/keychain/{catalog_id}/{keychain_name}."""
    status: str = Field(..., description="Operation status: 'success', 'not_found', or 'expired'")
    keychain_name: str = Field(..., description="Keychain entry name")
    catalog_id: int = Field(..., description="Catalog ID")
    cache_key: str = Field(..., description="Cache key")
    token_data: Optional[Dict[str, Any]] = Field(None, description="Decrypted token/credential data")
    credential_type: Optional[str] = Field(None, description="Credential type")
    cache_type: Optional[str] = Field(None, description="Cache type")
    scope_type: Optional[str] = Field(None, description="Scope type")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")
    ttl_seconds: Optional[float] = Field(None, description="Remaining TTL in seconds")
    accessed_at: Optional[datetime] = Field(None, description="Last access timestamp")
    access_count: Optional[int] = Field(None, description="Number of times accessed")
    auto_renew: bool = Field(default=False, description="Auto-renewal enabled")
    renew_config: Optional[Dict[str, Any]] = Field(None, description="Renewal configuration")
    expired: bool = Field(default=False, description="Token is expired (may trigger auto-renewal)")


class KeychainDeleteResponse(BaseModel):
    """Response for DELETE /api/keychain/{catalog_id}/{keychain_name}."""
    status: str = Field(..., description="Operation status: 'success' or 'error'")
    message: str = Field(..., description="Result message")
    keychain_name: str = Field(..., description="Keychain entry name")
    catalog_id: int = Field(..., description="Catalog ID")


class KeychainListResponse(BaseModel):
    """Response for GET /api/keychain/catalog/{catalog_id}."""
    status: str = Field(..., description="Operation status: 'success'")
    catalog_id: int = Field(..., description="Catalog ID")
    entries: list[Dict[str, Any]] = Field(..., description="List of keychain entries for this catalog")
    count: int = Field(..., description="Number of entries")
