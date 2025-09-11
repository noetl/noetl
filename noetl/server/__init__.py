"""
Server assembly, APIs and orchestration services.

This package exposes `create_app` at the top-level so ASGI servers can
load the app via the string reference "noetl.server:create_app".
"""

from .app import create_app

__all__ = ["create_app"]

