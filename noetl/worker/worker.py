"""Backward-compatible exports for worker components."""

from .errors import TaskExecutionError
from .queue_worker import QueueWorker
from .registry import (
    deregister_server_from_env,
    deregister_worker_pool_from_env,
    on_worker_terminate,
    register_server_from_env,
    register_worker_pool_from_env,
    resolve_server_settings,
    resolve_worker_settings,
)
from .worker_pool import ScalableQueueWorkerPool

__all__ = [
    "QueueWorker",
    "ScalableQueueWorkerPool",
    "TaskExecutionError",
    "register_server_from_env",
    "deregister_server_from_env",
    "register_worker_pool_from_env",
    "deregister_worker_pool_from_env",
    "resolve_server_settings",
    "resolve_worker_settings",
    "on_worker_terminate",
]
