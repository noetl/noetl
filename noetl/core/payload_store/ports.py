"""Payload-store port: backend-neutral interface for content-addressed blobs.

Sibling of :mod:`noetl.core.event_store.ports` and
:mod:`noetl.core.projection_store.ports`. Where the event store owns the
durable append-only log and the projection store owns queryable read
models, the payload store owns **immutable, content-addressed byte blobs**
— the third leg of the v2 distributed-runtime spec's three-port shape.

The port is intentionally minimal so adapters (filesystem, S3, GCS,
Azure Blob, SeaweedFS) can be added without leaking backend-specific
shape into callers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional, Protocol


class PayloadNotFound(KeyError):
    """Raised when a fetch / delete targets a missing payload."""


def content_hash(payload: bytes) -> str:
    """Return the lowercase hex SHA-256 of ``payload``.

    The payload store's canonical reference id. Two byte sequences that
    hash to the same value are considered identical — adapters MAY
    deduplicate on this hash.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")
    return hashlib.sha256(bytes(payload)).hexdigest()


@dataclass(frozen=True)
class PayloadReference:
    """Backend-neutral pointer to a stored payload.

    ``sha256`` is the canonical id; ``uri`` carries the backend-specific
    locator (filesystem path / ``s3://...`` / ``gs://...``) but is
    optional — callers that only need to verify by hash can ignore it.

    ``metadata`` is small, opaque, and meant for human-debuggable
    annotations (originating step name, content schema digest, etc.).
    Adapters MAY persist it in a sidecar; consumers MUST NOT depend on
    it for correctness.
    """

    sha256: str
    byte_length: int
    content_type: str = "application/octet-stream"
    uri: Optional[str] = None
    metadata: dict[str, str] = field(default_factory=dict)


class PayloadStore(Protocol):
    """Async port for content-addressed payload storage.

    Implementations are expected to be safe to call concurrently from
    multiple coroutines in the same process. Cross-process / cross-host
    safety is backend-specific.
    """

    async def store(
        self,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> PayloadReference:
        """Write ``payload`` and return a reference.

        Content-addressed: storing the same bytes twice returns
        references with the same ``sha256``. Adapters MAY skip the
        physical write on the second call.
        """

    async def fetch(self, reference: PayloadReference) -> bytes:
        """Return the bytes for ``reference``.

        Raises :class:`PayloadNotFound` when the payload is missing.
        """

    async def exists(self, reference: PayloadReference) -> bool:
        """Return ``True`` iff the referenced payload is present."""

    async def delete(self, reference: PayloadReference) -> bool:
        """Remove the referenced payload.

        Returns ``True`` if a payload was removed; ``False`` if it was
        already absent. Never raises for the missing-payload case
        (mirrors :py:meth:`os.unlink` after a ``missing_ok=True`` pass).
        """
