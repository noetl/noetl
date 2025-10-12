"""
NoETL API package - Top-level API routers and schemas.

Refactored from noetl.server.api to provide better organization
and separation of concerns.
"""

from . import routers
from .routers import router  # Main router aggregating all sub-routers

__all__ = ["routers", "router"]