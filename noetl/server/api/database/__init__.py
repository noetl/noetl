"""
NoETL Database API Module - Database execution and query operations.

Provides:
- PostgreSQL query execution
- Stored procedure calls
- Weather alert summary retrieval (example endpoint)
"""

from .endpoint import router
from .schema import (
    PostgresExecuteRequest,
    PostgresExecuteResponse,
    WeatherAlertSummaryResponse,
    AuthSessionValidateRequest,
    AuthSessionValidateResponse,
    AuthSessionUser,
)
from .service import DatabaseService

__all__ = [
    "router",
    "PostgresExecuteRequest",
    "PostgresExecuteResponse",
    "WeatherAlertSummaryResponse",
    "AuthSessionValidateRequest",
    "AuthSessionValidateResponse",
    "AuthSessionUser",
    "DatabaseService",
]
