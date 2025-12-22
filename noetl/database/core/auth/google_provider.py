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
from google.oauth2.service_account import IDTokenCredentials

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
        self._sa_info: Optional[Dict[str, Any]] = None
        self._initialize_credentials()
    
    def _initialize_credentials(self):
        """Initialize Google credentials from credential data."""
        try:
            scopes = self.credential_data.get('scopes', [
                'https://www.googleapis.com/auth/cloud-platform'
            ])

            # 1) Inline service account info under `service_account_info`
            if isinstance(self.credential_data.get('service_account_info'), dict):
                logger.debug("Initializing Google credentials from service_account_info (inline JSON)")
                self._sa_info = self.credential_data['service_account_info']
                self._credentials = service_account.Credentials.from_service_account_info(
                    self._sa_info,
                    scopes=scopes,
                )
                logger.info("Google service account credentials initialized from service_account_info")

            # 2) Direct inline service account fields (has `private_key` at top level)
            elif 'private_key' in self.credential_data and self.credential_data.get('type') == 'service_account':
                logger.debug("Initializing Google credentials from inline service account fields")
                self._sa_info = self.credential_data
                self._credentials = service_account.Credentials.from_service_account_info(
                    self._sa_info,
                    scopes=scopes,
                )
                logger.info("Google service account credentials initialized from inline fields")

            # 3) Service account JSON file path
            elif self.credential_data.get('service_account_file') or self.credential_data.get('file') or self.credential_data.get('path'):
                path = (
                    self.credential_data.get('service_account_file')
                    or self.credential_data.get('file')
                    or self.credential_data.get('path')
                )
                logger.debug(f"Initializing Google credentials from service account file: {path}")
                # Load the file content and create credentials
                with open(path, 'r') as f:
                    info = json.load(f)
                self._credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
                logger.info("Google service account credentials initialized from file")

            # 4) OAuth user credentials (authorized_user)
            elif self.credential_data.get('type') == 'authorized_user':
                logger.debug("Initializing Google credentials from authorized_user (OAuth)")
                self._credentials = oauth2_credentials.Credentials(
                    token=None,  # Will be refreshed
                    refresh_token=self.credential_data.get('refresh_token'),
                    token_uri=self.credential_data.get('token_uri') or 'https://oauth2.googleapis.com/token',
                    client_id=self.credential_data.get('client_id'),
                    client_secret=self.credential_data.get('client_secret'),
                    scopes=scopes,
                )
                logger.info("Google authorized_user credentials initialized")

            # 5) Service account impersonation (optionally with explicit source SA info)
            elif 'impersonate_service_account' in self.credential_data:
                logger.debug("Initializing Google credentials with impersonation")
                target_service_account = self.credential_data['impersonate_service_account']
                lifetime = int(self.credential_data.get('lifetime', 3600))

                # Source credentials from inline service account info if provided; otherwise ADC
                source_creds = None
                if isinstance(self.credential_data.get('source_service_account_info'), dict):
                    logger.debug("Using provided source_service_account_info for impersonation source credentials")
                    source_creds = service_account.Credentials.from_service_account_info(
                        self.credential_data['source_service_account_info'], scopes=scopes
                    )
                if source_creds is None:
                    source_creds, project = google.auth.default()

                self._credentials = impersonated_credentials.Credentials(
                    source_credentials=source_creds,
                    target_principal=target_service_account,
                    target_scopes=scopes,
                    lifetime=lifetime,
                )
                logger.info(f"Google impersonated credentials initialized for: {target_service_account}")

            else:
                # 6) Fallback to application default credentials (ADC)
                logger.debug("Initializing Google application default credentials (ADC)")
                self._credentials, project = google.auth.default()
                logger.info(f"Google default credentials initialized for project: {project}")

        except FileNotFoundError as e:
            logger.error(f"Failed to initialize Google credentials: File {getattr(e, 'filename', 'not found')} was not found.")
            raise
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

        # If we have inline service account info, build IDTokenCredentials directly
        if isinstance(self._sa_info, dict):
            logger.debug("Creating IDTokenCredentials from inline service account info")
            id_creds = IDTokenCredentials.from_service_account_info(
                self._sa_info,
                target_audience=audience,
            )
            id_creds.refresh(request)
            if not id_creds.token:
                raise Exception("Failed to obtain ID token from service account info")
            return id_creds.token
        
        # For service account credentials without stored info, use id_token module (will use ADC or metadata)
        if isinstance(self._credentials, service_account.Credentials):
            token = id_token_module.fetch_id_token(request, audience)
            return token
        
        # For other credential types, refresh and get token if supported
        self._credentials.refresh(request)
        if hasattr(self._credentials, 'id_token') and self._credentials.id_token:
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
