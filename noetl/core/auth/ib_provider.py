"""
Interactive Brokers OAuth 2.0 token provider.

Uses JWT client assertion (RFC 7521) for OAuth 2.0 authentication with IBKR API.
"""

import time
from typing import Optional
from datetime import datetime, timedelta

import jwt
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class IBTokenProvider:
    """
    Interactive Brokers OAuth 2.0 token provider.
    
    IBKR uses JWT-based client assertion (RFC 7521) for OAuth 2.0 authentication.
    This requires signing a JWT with an RSA private key instead of using a simple
    client_id/client_secret flow.
    
    Authentication Flow:
    1. Create JWT assertion with client_id, signed with RSA private key
    2. POST to /oauth2/api/v1/token with signed JWT
    3. Receive access token (valid ~24 hours)
    4. Use token in Authorization: Bearer header for API calls
    
    Credential Format:
    {
        "client_id": "your-oauth-client-id",
        "key_id": "your-rsa-key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----",
        "api_base_url": "https://api.ibkr.com/v1"
    }
    """
    
    def __init__(self, credential_data: dict):
        """
        Initialize IBKR token provider.
        
        Args:
            credential_data: Dictionary containing OAuth credentials
                - client_id: OAuth application client ID
                - key_id: RSA key identifier for JWT signing
                - private_key: PEM-encoded RSA private key
                - api_base_url: Base URL for IBKR API (default: https://api.ibkr.com/v1)
        """
        self.client_id = credential_data.get('client_id')
        self.key_id = credential_data.get('key_id')
        private_key_pem = credential_data.get('private_key', '')
        
        # Handle both raw key and credential data wrapper
        if isinstance(credential_data.get('data'), dict):
            cred_data = credential_data['data']
            self.client_id = cred_data.get('client_id', self.client_id)
            self.key_id = cred_data.get('key_id', self.key_id)
            private_key_pem = cred_data.get('private_key', private_key_pem)
        
        # API configuration
        api_base = credential_data.get('api_base_url', 'https://api.ibkr.com/v1')
        self.token_url = f"{api_base}/oauth2/token"
        
        # Token cache
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        
        # Load and validate private key
        if not private_key_pem:
            raise ValueError("IBKR OAuth requires 'private_key' in credential data")
        
        try:
            self.private_key = serialization.load_pem_private_key(
                private_key_pem.encode('utf-8'),
                password=None,
                backend=default_backend()
            )
            logger.info("IBKR: Loaded RSA private key for JWT signing")
        except Exception as e:
            logger.error(f"IBKR: Failed to load private key: {e}")
            raise ValueError(f"Invalid RSA private key: {e}")
    
    def _create_client_assertion(self) -> str:
        """
        Create signed JWT client assertion for token request.
        
        JWT Format (RFC 7521):
        Header:
        {
            "alg": "RS256",
            "kid": "<key_id>"
        }
        
        Payload:
        {
            "iss": "<client_id>",
            "sub": "<client_id>",
            "aud": "<token_url>",
            "exp": <unix_timestamp + 300>,
            "iat": <unix_timestamp>
        }
        
        Returns:
            Signed JWT string
        """
        now = int(time.time())
        
        # JWT header
        headers = {
            'alg': 'RS256',
            'kid': self.key_id
        }
        
        # JWT payload
        payload = {
            'iss': self.client_id,  # Issuer
            'sub': self.client_id,  # Subject
            'aud': self.token_url,  # Audience (token endpoint)
            'exp': now + 300,       # Expiration (5 minutes)
            'iat': now              # Issued at
        }
        
        # Sign with RS256
        try:
            token = jwt.encode(
                payload,
                self.private_key,
                algorithm='RS256',
                headers=headers
            )
            logger.debug(f"IBKR: Created client assertion JWT (expires in 5 minutes)")
            return token
        except Exception as e:
            logger.error(f"IBKR: Failed to create JWT assertion: {e}")
            raise
    
    def _fetch_token_impl(self, audience: Optional[str] = None) -> str:
        """
        Fetch OAuth 2.0 access token from IBKR using JWT client assertion.
        
        Args:
            audience: Unused for IBKR (kept for interface compatibility)
        
        Returns:
            Access token string
            
        Raises:
            httpx.HTTPStatusError: If token request fails
        """
        logger.info("IBKR: Fetching new OAuth 2.0 access token")
        
        # Create signed JWT assertion
        client_assertion = self._create_client_assertion()
        
        # Token request
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.token_url,
                    data={
                        'client_assertion': client_assertion,
                        'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
                    },
                    headers={'Content-Type': 'application/x-www-form-urlencoded'}
                )
                response.raise_for_status()
                
                token_data = response.json()
                self.access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 86399)  # ~24 hours
                scopes = token_data.get('scope', 'unknown')
                
                # Cache with 5 minute buffer before expiry
                self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)
                
                logger.info(
                    f"IBKR: Successfully obtained access token "
                    f"(expires in {expires_in}s, scopes: {scopes})"
                )
                logger.debug(f"IBKR: Token will be refreshed at {self.token_expiry}")
                
                return self.access_token
                
        except httpx.HTTPStatusError as e:
            logger.error(
                f"IBKR: Token request failed with status {e.response.status_code}: "
                f"{e.response.text}"
            )
            raise
        except Exception as e:
            logger.error(f"IBKR: Unexpected error fetching token: {e}")
            raise
    
    def fetch_token(self, audience: Optional[str] = None) -> str:
        """
        Get access token, refreshing if needed.
        
        Args:
            audience: Unused for IBKR
            
        Returns:
            Valid access token
        """
        if self.is_token_valid():
            logger.debug("IBKR: Using cached access token")
            return self.access_token
        
        logger.debug("IBKR: Token expired or not cached, fetching new token")
        return self._fetch_token_impl(audience)
    
    def is_token_valid(self) -> bool:
        """
        Check if current token is still valid.
        
        Returns:
            True if token exists and hasn't expired
        """
        if not self.access_token or not self.token_expiry:
            return False
        
        is_valid = datetime.utcnow() < self.token_expiry
        if not is_valid:
            logger.debug("IBKR: Cached token has expired")
        
        return is_valid
    
    def invalidate_token(self):
        """Clear cached token, forcing refresh on next request."""
        logger.debug("IBKR: Invalidating cached token")
        self.access_token = None
        self.token_expiry = None
