"""
Cloud storage integration for DuckDB.
"""

from .scopes import detect_uri_scopes, infer_object_store_scope, validate_cloud_output_requirement
from .credentials import configure_cloud_credentials