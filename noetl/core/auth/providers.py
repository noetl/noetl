"""
Token provider abstraction for OAuth and service account authentication.

Provides a base class and factory for token providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class TokenProvider(ABC):
    """
    Abstract base class for token providers.
    
    Token providers handle OAuth flows, service account impersonation,
    and other token-based authentication mechanisms.
    """
    
    def __init__(self, credential_data: Dict[str, Any]):
        """
        Initialize token provider with credential data.
        
        Args:
            credential_data: Decrypted credential data from database
        """
        self.credential_data = credential_data
        self._cached_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
    
    @abstractmethod
    def fetch_token(self, audience: Optional[str] = None) -> str:
        """
        Fetch a valid token, using cache if available.
        
        Args:
            audience: Optional audience/scope for the token
            
        Returns:
            Valid access token string
            
        Raises:
            Exception: If token fetch fails
        """
        pass
    
    def is_token_valid(self) -> bool:
        """
        Check if cached token is still valid.
        
        Returns:
            True if token exists and hasn't expired
        """
        if not self._cached_token or not self._token_expiry:
            return False
        
        # Add 60 second buffer before expiry
        now = datetime.now(timezone.utc)
        return now < self._token_expiry
    
    def clear_cache(self):
        """Clear cached token and force refresh on next fetch."""
        self._cached_token = None
        self._token_expiry = None


def get_token_provider(credential_type: str, credential_data: Dict[str, Any]) -> TokenProvider:
    """
    Factory function to create appropriate token provider.
    
    Args:
        credential_type: Type of credential (e.g., 'google_service_account', 'oauth2')
        credential_data: Decrypted credential data
        
    Returns:
        TokenProvider instance for the credential type
        
    Raises:
        ValueError: If credential type is not supported
    """
    from .google_provider import GoogleTokenProvider
    
    provider_map = {
        'google_service_account': GoogleTokenProvider,
        'google_oauth': GoogleTokenProvider,
        'gcp': GoogleTokenProvider,
    }
    
    provider_class = provider_map.get(credential_type)
    
    if not provider_class:
        raise ValueError(
            f"Unsupported credential type for token provider: {credential_type}. "
            f"Supported types: {list(provider_map.keys())}"
        )
    
    logger.debug(f"Creating token provider for type: {credential_type}")
    return provider_class(credential_data)
