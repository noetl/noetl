"""
Standardized error classification for NoETL.

Provides consistent error objects that enable intelligent retry/routing
decisions in step-level case blocks without brittle string matching.

Usage in case blocks:
    case:
      - when: "{{ event.payload.error.retryable }}"
        then:
          retry:
            action: transform
            max_attempts: 3

      - when: "{{ event.payload.error.kind == 'schema' }}"
        then:
          jump:
            action: error_handler
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ErrorKind(str, Enum):
    """Standardized error categories for case block matching."""

    # Network/connectivity errors
    CONNECTION = "connection"       # Connection refused, DNS failure
    TIMEOUT = "timeout"             # Request/response timeout

    # HTTP-specific errors
    RATE_LIMIT = "rate_limit"       # 429 Too Many Requests
    AUTH = "auth"                   # 401/403 Authentication/Authorization
    NOT_FOUND = "not_found"         # 404 Not Found
    CLIENT_ERROR = "client_error"   # 4xx (other than above)
    SERVER_ERROR = "server_error"   # 5xx Server Error

    # Data/validation errors
    SCHEMA = "schema"               # Data validation, type mismatch
    PARSE = "parse"                 # JSON/XML parsing failure
    TRANSFORM = "transform"         # Data transformation error

    # Database errors
    DB_CONNECTION = "db_connection" # Database connection failure
    DB_CONSTRAINT = "db_constraint" # Unique constraint, foreign key
    DB_DEADLOCK = "db_deadlock"     # Transaction deadlock
    DB_TIMEOUT = "db_timeout"       # Query timeout

    # Storage errors
    STORAGE_QUOTA = "storage_quota" # Quota exceeded
    STORAGE_ACCESS = "storage_access"  # Permission denied

    # Generic
    UNKNOWN = "unknown"             # Unclassified error


class ErrorInfo(BaseModel):
    """
    Standardized error object for event payloads and pipeline _err variable.

    This enables stable case conditions without brittle string matching:
    - _err.kind == 'rate_limit'
    - _err.retryable == true
    - _err.http_status == 429
    - _err.pg_code in ['40001', '40P01']
    """

    kind: ErrorKind = Field(
        default=ErrorKind.UNKNOWN,
        description="Error category for case matching"
    )
    retryable: bool = Field(
        default=False,
        description="Whether this error is worth retrying"
    )
    code: str = Field(
        default="UNKNOWN",
        description="Tool-specific error code (HTTP_429, PG_40P01, etc.)"
    )
    message: str = Field(
        default="Unknown error",
        description="Human-readable error message"
    )
    source: str = Field(
        default="unknown",
        description="Tool kind that produced this error"
    )

    # HTTP-specific fields (for direct template access)
    http_status: Optional[int] = Field(
        None, description="HTTP status code (for HTTP errors)"
    )
    retry_after: Optional[int] = Field(
        None, description="Retry-After header value in seconds"
    )

    # Database-specific fields
    pg_code: Optional[str] = Field(
        None, description="PostgreSQL error code (e.g., 40001, 40P01, 23505)"
    )

    # Python-specific fields
    exception_type: Optional[str] = Field(
        None, description="Python exception class name"
    )

    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional extra context (headers, stack trace, etc.)"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for event payload and _err template access."""
        d = {
            "kind": self.kind.value,
            "retryable": self.retryable,
            "code": self.code,
            "message": self.message,
            "source": self.source,
        }
        # Add optional fields only if set
        if self.http_status is not None:
            d["http_status"] = self.http_status
        if self.retry_after is not None:
            d["retry_after"] = self.retry_after
        if self.pg_code is not None:
            d["pg_code"] = self.pg_code
        if self.exception_type is not None:
            d["exception_type"] = self.exception_type
        if self.details:
            d["details"] = self.details
        return d


def classify_http_error(
    status_code: int,
    message: str = "",
    headers: Optional[dict] = None,
    response_body: Optional[str] = None,
) -> ErrorInfo:
    """Classify HTTP errors into standardized ErrorInfo."""
    headers = headers or {}

    # Parse Retry-After header for direct template access
    retry_after = None
    ra = headers.get("retry-after") or headers.get("Retry-After")
    if ra:
        try:
            retry_after = int(ra)
        except ValueError:
            pass

    if status_code == 429:
        return ErrorInfo(
            kind=ErrorKind.RATE_LIMIT,
            retryable=True,
            code=f"HTTP_{status_code}",
            message=message or "Too Many Requests",
            source="http",
            http_status=status_code,
            retry_after=retry_after,
        )
    elif status_code == 401:
        return ErrorInfo(
            kind=ErrorKind.AUTH,
            retryable=False,
            code=f"HTTP_{status_code}",
            message=message or "Unauthorized",
            source="http",
            http_status=status_code,
        )
    elif status_code == 403:
        return ErrorInfo(
            kind=ErrorKind.AUTH,
            retryable=False,
            code=f"HTTP_{status_code}",
            message=message or "Forbidden",
            source="http",
            http_status=status_code,
        )
    elif status_code == 404:
        return ErrorInfo(
            kind=ErrorKind.NOT_FOUND,
            retryable=False,
            code=f"HTTP_{status_code}",
            message=message or "Not Found",
            source="http",
            http_status=status_code,
        )
    elif 400 <= status_code < 500:
        return ErrorInfo(
            kind=ErrorKind.CLIENT_ERROR,
            retryable=False,
            code=f"HTTP_{status_code}",
            message=message or f"Client Error {status_code}",
            source="http",
            http_status=status_code,
        )
    elif status_code in (500, 502, 503, 504):
        return ErrorInfo(
            kind=ErrorKind.SERVER_ERROR,
            retryable=True,
            code=f"HTTP_{status_code}",
            message=message or f"Server Error {status_code}",
            source="http",
            http_status=status_code,
            retry_after=retry_after,
        )
    elif status_code >= 500:
        return ErrorInfo(
            kind=ErrorKind.SERVER_ERROR,
            retryable=True,
            code=f"HTTP_{status_code}",
            message=message or f"Server Error {status_code}",
            source="http",
            http_status=status_code,
        )
    else:
        return ErrorInfo(
            kind=ErrorKind.UNKNOWN,
            retryable=False,
            code=f"HTTP_{status_code}",
            message=message or f"HTTP Error {status_code}",
            source="http",
            http_status=status_code,
        )


def classify_connection_error(
    error: Exception,
    source: str = "http",
) -> ErrorInfo:
    """Classify connection/network errors."""
    error_str = str(error).lower()

    if "timeout" in error_str:
        return ErrorInfo(
            kind=ErrorKind.TIMEOUT,
            retryable=True,
            code="CONN_TIMEOUT",
            message=str(error),
            source=source,
        )
    elif "connection refused" in error_str:
        return ErrorInfo(
            kind=ErrorKind.CONNECTION,
            retryable=True,  # May be transient
            code="CONN_REFUSED",
            message=str(error),
            source=source,
        )
    elif "dns" in error_str or "resolve" in error_str:
        return ErrorInfo(
            kind=ErrorKind.CONNECTION,
            retryable=True,  # DNS can be transient
            code="DNS_ERROR",
            message=str(error),
            source=source,
        )
    else:
        return ErrorInfo(
            kind=ErrorKind.CONNECTION,
            retryable=True,
            code="CONN_ERROR",
            message=str(error),
            source=source,
        )


def classify_postgres_error(
    error: Exception,
    error_code: Optional[str] = None,
) -> ErrorInfo:
    """Classify PostgreSQL errors."""
    error_str = str(error).lower()

    # Extract PG error code if available
    pg_code = error_code
    if not pg_code and hasattr(error, 'pgcode'):
        pg_code = error.pgcode

    code = f"PG_{pg_code}" if pg_code else "PG_UNKNOWN"

    # Deadlock
    if "deadlock" in error_str or pg_code in ("40001", "40P01"):
        return ErrorInfo(
            kind=ErrorKind.DB_DEADLOCK,
            retryable=True,
            code=code,
            message=str(error),
            source="postgres",
            pg_code=pg_code,
        )

    # Unique constraint
    if "unique" in error_str or "duplicate" in error_str or (pg_code and pg_code.startswith("23")):
        return ErrorInfo(
            kind=ErrorKind.DB_CONSTRAINT,
            retryable=False,
            code=code,
            message=str(error),
            source="postgres",
            pg_code=pg_code,
        )

    # Connection errors
    if "connection" in error_str or (pg_code and pg_code.startswith("08")):
        return ErrorInfo(
            kind=ErrorKind.DB_CONNECTION,
            retryable=True,
            code=code,
            message=str(error),
            source="postgres",
            pg_code=pg_code,
        )

    # Query timeout
    if "timeout" in error_str or pg_code == "57014":
        return ErrorInfo(
            kind=ErrorKind.DB_TIMEOUT,
            retryable=True,
            code=code,
            message=str(error),
            source="postgres",
            pg_code=pg_code,
        )

    return ErrorInfo(
        kind=ErrorKind.UNKNOWN,
        retryable=False,
        code=code,
        message=str(error),
        source="postgres",
        pg_code=pg_code,
    )


def classify_python_error(
    error: Exception,
) -> ErrorInfo:
    """Classify Python tool errors."""
    error_str = str(error).lower()
    error_type = type(error).__name__

    # JSON parsing
    if "json" in error_str or error_type == "JSONDecodeError":
        return ErrorInfo(
            kind=ErrorKind.PARSE,
            retryable=False,
            code=f"PY_{error_type}",
            message=str(error),
            source="python",
            exception_type=error_type,
        )

    # Type/validation errors
    if error_type in ("TypeError", "ValueError", "ValidationError"):
        return ErrorInfo(
            kind=ErrorKind.SCHEMA,
            retryable=False,
            code=f"PY_{error_type}",
            message=str(error),
            source="python",
            exception_type=error_type,
        )

    # Key/index errors
    if error_type in ("KeyError", "IndexError"):
        return ErrorInfo(
            kind=ErrorKind.SCHEMA,
            retryable=False,
            code=f"PY_{error_type}",
            message=str(error),
            source="python",
            exception_type=error_type,
        )

    # Timeout
    if "timeout" in error_str:
        return ErrorInfo(
            kind=ErrorKind.TIMEOUT,
            retryable=True,
            code="PY_TIMEOUT",
            message=str(error),
            source="python",
            exception_type=error_type,
        )

    return ErrorInfo(
        kind=ErrorKind.UNKNOWN,
        retryable=False,
        code=f"PY_{error_type}",
        message=str(error),
        source="python",
        exception_type=error_type,
    )


def classify_storage_error(
    error: Exception,
    source: str = "gcs",
) -> ErrorInfo:
    """Classify storage (GCS/S3) errors."""
    error_str = str(error).lower()

    if "quota" in error_str or "limit" in error_str:
        return ErrorInfo(
            kind=ErrorKind.STORAGE_QUOTA,
            retryable=False,
            code="STORAGE_QUOTA",
            message=str(error),
            source=source,
        )

    if "permission" in error_str or "access" in error_str or "forbidden" in error_str:
        return ErrorInfo(
            kind=ErrorKind.STORAGE_ACCESS,
            retryable=False,
            code="STORAGE_ACCESS",
            message=str(error),
            source=source,
        )

    if "timeout" in error_str:
        return ErrorInfo(
            kind=ErrorKind.TIMEOUT,
            retryable=True,
            code="STORAGE_TIMEOUT",
            message=str(error),
            source=source,
        )

    if "connection" in error_str:
        return ErrorInfo(
            kind=ErrorKind.CONNECTION,
            retryable=True,
            code="STORAGE_CONN",
            message=str(error),
            source=source,
        )

    return ErrorInfo(
        kind=ErrorKind.UNKNOWN,
        retryable=True,  # Storage errors often transient
        code="STORAGE_ERROR",
        message=str(error),
        source=source,
    )


def classify_error(
    error: Exception,
    source: str = "unknown",
    context: Optional[dict] = None,
) -> ErrorInfo:
    """
    Generic error classifier that routes to specific classifiers.

    Args:
        error: The exception to classify
        source: Tool kind (http, postgres, python, gcs, s3)
        context: Optional context (e.g., HTTP status code, response headers)

    Returns:
        Standardized ErrorInfo
    """
    context = context or {}

    if source == "http":
        status_code = context.get("status_code", 0)
        if status_code:
            return classify_http_error(
                status_code=status_code,
                message=str(error),
                headers=context.get("headers"),
            )
        return classify_connection_error(error, source="http")

    elif source == "postgres":
        return classify_postgres_error(error, context.get("error_code"))

    elif source == "python":
        return classify_python_error(error)

    elif source in ("gcs", "s3"):
        return classify_storage_error(error, source=source)

    else:
        return ErrorInfo(
            kind=ErrorKind.UNKNOWN,
            retryable=False,
            code="UNKNOWN",
            message=str(error),
            source=source,
        )


__all__ = [
    "ErrorKind",
    "ErrorInfo",
    "classify_http_error",
    "classify_connection_error",
    "classify_postgres_error",
    "classify_python_error",
    "classify_storage_error",
    "classify_error",
]
