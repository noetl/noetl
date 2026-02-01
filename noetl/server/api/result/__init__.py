"""
Result Storage REST API module.

Provides endpoints for result storage operations with the preferred 'result' naming.
This is the recommended API - the /api/temp endpoints are maintained for backwards compatibility.
"""

from noetl.server.api.result.endpoint import router

__all__ = ["router"]
