"""
Google OAuth and Service Account token provider.

Supports:
- Service account impersonation
- ID token generation with audience
- Access token generation
- Automatic token refresh and caching
"""

import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone

import google.auth
import google.auth.transport.requests
from google.auth import impersonated_credentials
from google.oauth2 import service_account
from google.oauth2 import credentials as oauth2_credentials
from google.oauth2 import id_token as id_token_module

from noetl.core.logger import setup_logger
from .providers import TokenProvider

logger = setup_logger(__name__, include_location=True)


class GoogleTokenProvider(TokenProvider):
    """
    Google Cloud token provider for service accounts and OAuth.
    
    Supports multiple authentication patterns:
    1. Service account key file (JSON)
    2. Service account impersonation
    3. Application default credentials with impersonation
    """
    
    def __init__(self, credential_data: Dict[str, Any]):
        """
        Initialize Google token provider.
        
        Expected credential_data formats:
        
        Service Account Key:
        {
            "type": "service_account",
            "project_id": "...",
            "private_key_id": "...",
            "private_key": "...",
            "client_email": "...",
            ...
        }
        
        Service Account Impersonation:
        {
            "impersonate_service_account": "sa@project.iam.gserviceaccount.com",
            "scopes": ["https://www.googleapis.com/auth/cloud-platform"],  # optional
            "lifetime": 3600  # optional, seconds
        }
        
        Args:
            credential_data: Decrypted credential data from database
        """
        super().__init__(credential_data)
        self._credentials = None
        self._initialize_credentials()
    
    def _initialize_credentials(self):
        """Initialize Google credentials from credential data."""
        try:
            # Check if this is a service account key (has private_key)
            if 'private_key' in self.credential_data:
                logger.debug("Initializing Google credentials from service account key")
                self._credentials = service_account.Credentials.from_service_account_info(
                    self.credential_data,
                    scopes=self.credential_data.get('scopes', [
                        'https://www.googleapis.com/auth/cloud-platform'
                    ])
                )
                logger.info("Google service account credentials initialized")
            
            # Check if this is authorized_user (OAuth user credentials)
            elif self.credential_data.get('type') == 'authorized_user':
                logger.debug("Initializing Google credentials from authorized_user (OAuth)")
                # Create OAuth2 credentials from user tokens
                self._credentials = oauth2_credentials.Credentials(
                    token=None,  # Will be refreshed
                    refresh_token=self.credential_data.get('refresh_token'),
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=self.credential_data.get('client_id'),
                    client_secret=self.credential_data.get('client_secret'),
                    scopes=self.credential_data.get('scopes', [
                        'https://www.googleapis.com/auth/cloud-platform'
                    ])
                )
                logger.info("Google authorized_user credentials initialized")
            
            # Check if this is service account impersonation
            elif 'impersonate_service_account' in self.credential_data:
                logger.debug("Initializing Google credentials with impersonation")
                target_service_account = self.credential_data['impersonate_service_account']
                scopes = self.credential_data.get('scopes', [
                    'https://www.googleapis.com/auth/cloud-platform'
                ])
                lifetime = self.credential_data.get('lifetime', 3600)
                
                # Use application default credentials as source
                source_credentials, project = google.auth.default()
                
                self._credentials = impersonated_credentials.Credentials(
                    source_credentials=source_credentials,
                    target_principal=target_service_account,
                    target_scopes=scopes,
                    lifetime=lifetime
                )
                logger.info(f"Google impersonated credentials initialized for: {target_service_account}")
            
            else:
                # Fallback to application default credentials
                logger.debug("Initializing Google application default credentials")
                self._credentials, project = google.auth.default()
                logger.info(f"Google default credentials initialized for project: {project}")
                
        except Exception as e:
            logger.error(f"Failed to initialize Google credentials: {e}")
            raise
    
    def fetch_token(self, audience: Optional[str] = None) -> str:
        """
        Fetch a Google access or ID token.
        
        Args:
            audience: If provided, returns an ID token for this audience.
                     If None, returns an access token.
        
        Returns:
            Valid token string
            
        Raises:
            Exception: If token fetch fails
        """
        # Check cache first
        if self.is_token_valid():
            logger.debug("Using cached Google token")
            return self._cached_token
        
        try:
            if audience:
                # Fetch ID token with audience
                logger.debug(f"Fetching Google ID token with audience: {audience}")
                token = self._fetch_id_token(audience)
            else:
                # Fetch access token
                logger.debug("Fetching Google access token")
                token = self._fetch_access_token()
            
            # Cache token with expiry
            self._cached_token = token
            self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=3000)  # 50 min buffer
            
            logger.info("Google token fetched and cached successfully")
            return token
            
        except Exception as e:
            logger.error(f"Failed to fetch Google token: {e}")
            raise
    
    def _fetch_id_token(self, audience: str) -> str:
        """
        Fetch Google ID token for specified audience.
        
        Args:
            audience: Target audience for the ID token
            
        Returns:
            ID token string
        """
        request = google.auth.transport.requests.Request()
        
        # For service account credentials, use id_token module
        if isinstance(self._credentials, service_account.Credentials):
            token = id_token_module.fetch_id_token(request, audience)
            return token
        
        # For other credential types, refresh and get token
        self._credentials.refresh(request)
        
        # Check if credentials have id_token attribute
        if hasattr(self._credentials, 'id_token'):
            return self._credentials.id_token
        
        # Fallback: use the access token
        logger.warning("ID token not available, using access token instead")
        return self._credentials.token
    
    def _fetch_access_token(self) -> str:
        """
        Fetch Google access token.
        
        Returns:
            Access token string
        """
        request = google.auth.transport.requests.Request()
        self._credentials.refresh(request)
        
        if not self._credentials.token:
            raise Exception("Failed to obtain access token from credentials")
        
        return self._credentials.token
    
    def get_credentials(self):
        """
        Get the underlying Google credentials object.
        
        Returns:
            Google credentials object
        """
        return self._credentials
