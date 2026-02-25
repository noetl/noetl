"""
NoETL Credential API Endpoints - FastAPI routes for credential management.

Provides REST endpoints for:
- Credential creation, retrieval, and listing
- GCP token generation with credential caching
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from noetl.core.logger import setup_logger
from .schema import (
    CredentialCreateRequest,
    CredentialResponse,
    CredentialListResponse,
    GCPTokenRequest,
    GCPTokenResponse
)
from .service import CredentialService

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


# ============================================================================
# Credential CRUD Endpoints
# ============================================================================

@router.post("/credentials", response_model=CredentialResponse)
async def create_or_update_credential(request: CredentialCreateRequest) -> CredentialResponse:
    """
    Create or update a credential with encryption.
    
    **Request Body**:
    ```json
    {
        "name": "my-database-creds",
        "type": "postgres",
        "data": {
            "username": "admin",
            "password": "secret123",
            "host": "db.example.com"
        },
        "meta": {"environment": "production"},
        "tags": ["database", "production"],
        "description": "Production database credentials"
    }
    ```
    
    **Response**:
    ```json
    {
        "id": "123456789",
        "name": "my-database-creds",
        "type": "postgres",
        "meta": {"environment": "production"},
        "tags": ["database", "production"],
        "description": "Production database credentials",
        "created_at": "2025-10-12T10:00:00Z",
        "updated_at": "2025-10-12T10:00:00Z"
    }
    ```
    
    **Note**: The `data` field is encrypted and not returned in responses.
    Use `GET /credentials/{identifier}?include_data=true` to retrieve decrypted data.
    """
    try:
        return await CredentialService.create_or_update_credential(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating/updating credential: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/credentials", response_model=CredentialListResponse)
async def list_credentials(
    type: Optional[str] = None,
    q: Optional[str] = None
) -> CredentialListResponse:
    """
    List credentials with optional filtering.
    
    **Query Parameters**:
    - `type`: Filter by credential type (e.g., "postgres", "httpBearerAuth")
    - `q`: Free-text search on name and description
    
    **Example**:
    ```
    GET /credentials?type=postgres&q=production
    ```
    
    **Response**:
    ```json
    {
        "items": [
            {
                "id": "123456789",
                "name": "my-database-creds",
                "type": "postgres",
                "tags": ["database", "production"],
                "created_at": "2025-10-12T10:00:00Z",
                "updated_at": "2025-10-12T10:00:00Z"
            }
        ],
        "filter": {
            "type": "postgres",
            "q": "production"
        }
    }
    ```
    """
    try:
        return await CredentialService.list_credentials(ctype=type, q=q)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error listing credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/credentials/{identifier}", response_model=CredentialResponse)
async def get_credential(
    identifier: str,
    include_data: bool = False,
    catalog_id: Optional[int] = None,
    execution_id: Optional[int] = None,
    parent_execution_id: Optional[int] = None
) -> CredentialResponse:
    """
    Get a credential by ID or name.
    
    **Path Parameters**:
    - `identifier`: Credential ID (numeric) or name (string)
    
    **Query Parameters**:
    - `include_data`: If true, includes decrypted credential data (default: false)
    
    **Examples**:
    ```
    GET /credentials/123456789
    GET /credentials/my-database-creds
    GET /credentials/my-database-creds?include_data=true
    ```
    
    **Response (without data)**:
    ```json
    {
        "id": "123456789",
        "name": "my-database-creds",
        "type": "postgres",
        "meta": {"environment": "production"},
        "tags": ["database", "production"],
        "description": "Production database credentials",
        "created_at": "2025-10-12T10:00:00Z",
        "updated_at": "2025-10-12T10:00:00Z"
    }
    ```
    
    **Response (with data)**:
    ```json
    {
        "id": "123456789",
        "name": "my-database-creds",
        "type": "postgres",
        "data": {
            "username": "admin",
            "password": "secret123",
            "host": "db.example.com"
        },
        "created_at": "2025-10-12T10:00:00Z",
        "updated_at": "2025-10-12T10:00:00Z"
    }
    ```
    
    **Security Note**: Only include data when necessary. The data field contains
    sensitive information that is normally encrypted at rest.
    """
    try:
        return await CredentialService.get_credential(
            identifier,
            include_data,
            catalog_id=catalog_id,
            execution_id=execution_id,
            parent_execution_id=parent_execution_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting credential: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/credentials/{identifier}")
async def delete_credential(identifier: str):
    """
    Delete a credential by ID or name.
    
    **Path Parameters**:
    - `identifier`: Credential ID (numeric) or name (string)
    
    **Examples**:
    ```
    DELETE /credentials/123456789
    DELETE /credentials/my-database-creds
    ```
    
    **Response**:
    ```json
    {
        "message": "Credential deleted successfully",
        "id": "123456789"
    }
    ```
    """
    try:
        result = await CredentialService.delete_credential(identifier)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting credential: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GCP Token Endpoint
# ============================================================================

@router.post("/gcp/token", response_model=GCPTokenResponse)
async def get_gcp_token(request: GCPTokenRequest) -> GCPTokenResponse:
    """
    Obtain a GCP access token using various credential sources.
    
    **Request Body**:
    ```json
    {
        "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
        "credential": "my-gcp-service-account",
        "store_as": "gcp-token-cached",
        "store_type": "httpBearerAuth",
        "store_tags": ["gcp", "token", "cached"]
    }
    ```
    
    **Credential Sources** (in priority order):
    1. `credentials_info`: Service account JSON as object or string
    2. `credential`: Stored credential name or ID
    3. `credential_id`: Stored credential ID
    4. `service_account_secret`: GCP Secret Manager path
    5. `credentials_path`: Path to service account JSON file
    6. `use_metadata`: GCE metadata server (if true)
    7. Application Default Credentials (ADC)
    
    **Token Storage**:
    If `store_as` is provided, the generated token will be saved as a credential
    for reuse. This is useful for caching tokens and avoiding repeated generation.
    
    **Response**:
    ```json
    {
        "access_token": "ya29.c.Kl6iB...",
        "token_expiry": "2025-10-12T11:00:00Z",
        "scopes": ["https://www.googleapis.com/auth/cloud-platform"]
    }
    ```
    
    **Configuration**:
    This endpoint can be disabled by setting `NOETL_ENABLE_GCP_TOKEN_API=false`.
    
    **Security Note**: Tokens are short-lived (typically 1 hour). Store tokens
    as credentials to avoid regenerating them for every request.
    """
    try:
        return await CredentialService.get_gcp_token(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error obtaining GCP token: {e}")
        raise HTTPException(status_code=500, detail=str(e))

