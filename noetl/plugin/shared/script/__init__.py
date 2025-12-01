"""
NoETL Script Resolution Module

This package provides standardized external script execution from various sources:
- GCS (Google Cloud Storage)
- S3 (AWS S3)
- Local files
- HTTP/HTTPS endpoints

Aligns with Azure Data Factory's linked service pattern for enterprise data pipelines.
"""

from .resolver import resolve_script
from .validation import validate_script_config

__all__ = [
    'resolve_script',
    'validate_script_config',
]
