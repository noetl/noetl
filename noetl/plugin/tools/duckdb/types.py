"""
Type definitions for the DuckDB plugin.
"""

from typing import Dict, Any, Optional, List, Union, Callable
from dataclasses import dataclass
from enum import Enum


class AuthType(Enum):
    """Supported authentication types."""
    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    SNOWFLAKE = "snowflake"
    GCS = "gcs"
    GCS_HMAC = "gcs_hmac"
    S3 = "s3"
    S3_HMAC = "s3_hmac"


class DatabaseType(Enum):
    """Supported database types for attachment."""
    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLITE = "sqlite"


@dataclass
class ConnectionConfig:
    """DuckDB connection configuration."""
    database_path: str
    execution_id: str
    
    
@dataclass
class TaskConfig:
    """DuckDB task configuration."""
    task_id: str
    task_name: str
    commands: Union[str, List[str]]
    credentials: Optional[Dict[str, Any]] = None
    auth: Optional[Dict[str, Any]] = None
    database: Optional[str] = None
    auto_secrets: bool = True


@dataclass
class CloudScope:
    """Cloud storage scope definition."""
    scheme: str  # 'gs' or 's3'
    bucket: str
    full_uri: str


@dataclass
class CredentialData:
    """Credential data structure."""
    alias: str
    auth_type: AuthType
    data: Dict[str, Any]
    scope: Optional[str] = None


@dataclass
class TaskResult:
    """DuckDB task execution result."""
    task_id: str
    status: str  # 'success' or 'error'
    duration: float
    data: Optional[Any] = None
    error: Optional[str] = None
    traceback: Optional[str] = None


# Type aliases for common function signatures
JinjaEnvironment = Any  # jinja2.Environment
LogEventCallback = Optional[Callable[[str, str, str, str, str, float, Dict[str, Any], Any, Dict[str, Any], Optional[str]], str]]
ContextDict = Dict[str, Any]