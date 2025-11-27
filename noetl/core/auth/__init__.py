"""
NoETL Authentication Module - Token providers and OAuth integration.

This module provides token-based authentication capabilities:
- Token provider abstraction
- Google OAuth/Service Account integration
- Token caching and refresh
- Dynamic token resolution for plugins
"""

from .providers import TokenProvider, get_token_provider
from .google_provider import GoogleTokenProvider

__all__ = [
    'TokenProvider',
    'get_token_provider',
    'GoogleTokenProvider',
]
