"""
Cloud storage integration for DuckDB.
"""

from noetl.tools.duckdb.cloud.scopes import detect_uri_scopes, infer_object_store_scope, validate_cloud_output_requirement
from noetl.tools.duckdb.cloud.credentials import configure_cloud_credentials