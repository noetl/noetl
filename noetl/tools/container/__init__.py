"""Container execution tool for NoETL.

Provides a lazy import wrapper so the optional 'kubernetes' dependency is only
required when a container (K8s) task is actually executed.
"""

from typing import Any


def execute_container_task(*args: Any, **kwargs: Any):
    # Lazy import to avoid importing kubernetes client unless needed
    from .executor import execute_container_task as _impl
    return _impl(*args, **kwargs)


__all__ = ["execute_container_task"]
