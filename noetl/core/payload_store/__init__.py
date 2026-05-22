"""Payload-store port + reference adapter (v2 distributed-runtime spec phase 5).

Public surface:

- :class:`PayloadStore` — async Protocol every adapter implements.
- :class:`PayloadReference` — typed reference returned by ``store`` and
  consumed by ``fetch`` / ``exists`` / ``delete``.
- :class:`PayloadNotFound` — raised on fetch of a missing payload.
- :func:`content_hash` — canonical SHA-256 helper.
- :class:`FilesystemPayloadStore` — single-node / development reference
  adapter using a sharded, atomic-write filesystem layout.

Cloud adapters (S3 / GCS / Azure Blob / SeaweedFS) land in subsequent
rounds.
"""

from .filesystem import FilesystemPayloadStore
from .ports import (
    PayloadNotFound,
    PayloadReference,
    PayloadStore,
    content_hash,
)
from .s3 import S3PayloadStore

__all__ = [
    "PayloadStore",
    "PayloadReference",
    "PayloadNotFound",
    "content_hash",
    "FilesystemPayloadStore",
    "S3PayloadStore",
]
