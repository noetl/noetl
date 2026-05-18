"""
Server assembly, APIs and orchestration services.

This package exposes `create_app` at the top-level so ASGI servers can load the
app via the string reference "noetl.server:create_app". Keep the import lazy so
server submodules can be imported by standalone workers without assembling the
FastAPI application.
"""

from __future__ import annotations


def create_app(*args, **kwargs):
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)

__all__ = ["create_app"]
