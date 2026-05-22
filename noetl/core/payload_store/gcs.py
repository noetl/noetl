"""Google Cloud Storage adapter for :class:`PayloadStore`.

Implements the same Protocol contract as
:class:`FilesystemPayloadStore` and :class:`S3PayloadStore`.

Design notes:

- **Key layout** mirrors the filesystem + S3 adapters:
  ``<prefix>/<sha[0:2]>/<sha[2:4]>/<sha>``. Same sharding rationale —
  any single GCS listing stays bounded.
- **Atomicity** is intrinsic to GCS uploads — no temp + rename
  ceremony.
- **Content-addressing dedup** via ``Blob.exists()`` before
  ``upload_from_string``.
- **Metadata** rides as GCS custom blob metadata (the
  ``Blob.metadata`` dict, persisted by ``Blob.patch()``). No sidecar
  object — keeps the bucket layout flat. GCS technically tolerates
  UTF-8 in custom metadata, but the adapter requires ASCII at the
  boundary for portability with the S3 adapter and for predictable
  on-wire headers.
- **Delete** is Protocol-compliant (``True`` if a payload was
  removed, ``False`` if already absent). Implemented as
  ``exists`` + ``delete`` because ``Blob.delete()`` raises ``NotFound``
  on missing keys rather than reporting a boolean.
- **Sync google-cloud-storage + asyncio.to_thread.** The Protocol
  exposes async methods; the implementation bridges through a thread
  pool. The ``google-cloud-storage`` SDK has no native async client,
  so this is the canonical pattern for cloud adapters in NoETL (same
  shape as the S3 adapter).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

try:
    from google.cloud import storage as gcs_storage  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - google-cloud-storage is a runtime dep
    gcs_storage = None  # type: ignore[assignment]

try:
    from google.api_core import exceptions as gax_exceptions  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - google-api-core ships with google-cloud-storage
    gax_exceptions = None  # type: ignore[assignment]

from noetl.core.logger import setup_logger

from .ports import (
    PayloadNotFound,
    PayloadReference,
    PayloadStore,
    content_hash,
)

logger = setup_logger(__name__, include_location=True)


class GCSPayloadStore(PayloadStore):
    """Async Google Cloud Storage adapter.

    Constructor takes the bucket name and optional configuration:

    - ``prefix`` — string prepended to every object key. Useful when
      a single bucket hosts payloads alongside other namespaces.
    - ``client`` — pre-configured ``google.cloud.storage.Client``.
      When ``None``, a default client is constructed via
      ``storage.Client(project=project, credentials=credentials)``
      and credentials come from the standard Google auth chain (ADC).
    - ``project`` — explicit GCP project id (used when creating the
      default client).
    - ``credentials`` — credentials object passed through to
      ``storage.Client``. Pass a
      ``google.oauth2.service_account.Credentials`` instance for
      service-account auth. Mirrors the shape used by NoETL's existing
      GCS tool.
    - ``default_content_type`` — used when ``store(content_type=...)``
      is omitted or empty.
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        client: Optional[Any] = None,
        project: Optional[str] = None,
        credentials: Optional[Any] = None,
        default_content_type: str = "application/octet-stream",
    ) -> None:
        if gcs_storage is None:  # pragma: no cover - exercised when extra missing
            raise RuntimeError(
                "GCSPayloadStore requires google-cloud-storage; install "
                "noetl with the default runtime dependencies"
            )
        if not bucket:
            raise ValueError("bucket name is required")
        self.bucket_name = str(bucket)
        self.prefix = prefix.lstrip("/").rstrip("/") if prefix else ""
        self.project = project
        self.default_content_type = default_content_type
        if client is None:
            client_kwargs: dict[str, Any] = {}
            if project:
                client_kwargs["project"] = project
            if credentials is not None:
                client_kwargs["credentials"] = credentials
            self.client = gcs_storage.Client(**client_kwargs)
        else:
            self.client = client
        self.bucket = self.client.bucket(self.bucket_name)

    def _key_for(self, sha256: str) -> str:
        """Return the GCS object key for a payload digest."""
        if len(sha256) < 4:
            raise ValueError(
                f"sha256 prefix must be at least 4 chars for sharding (got {len(sha256)})"
            )
        sharded = f"{sha256[0:2]}/{sha256[2:4]}/{sha256}"
        return f"{self.prefix}/{sharded}" if self.prefix else sharded

    def _uri_for(self, key: str) -> str:
        return f"gs://{self.bucket_name}/{key}"

    @staticmethod
    def _validate_metadata(metadata: dict[str, str]) -> dict[str, str]:
        """Require ASCII-only metadata keys and values.

        GCS itself tolerates UTF-8 in custom metadata, but the adapter
        keeps the same boundary check as the S3 adapter so the
        cross-backend contract is uniform.
        """
        normalized: dict[str, str] = {}
        for raw_key, raw_value in metadata.items():
            key = str(raw_key)
            value = str(raw_value)
            try:
                key.encode("ascii")
                value.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f"GCS metadata key/value must be ASCII: {raw_key!r}={raw_value!r}"
                ) from exc
            normalized[key] = value
        return normalized

    @staticmethod
    def _is_not_found(exc: BaseException) -> bool:
        """True iff the GCS client error indicates the blob is missing."""
        if gax_exceptions is not None and isinstance(exc, gax_exceptions.NotFound):
            return True
        # Fallback for environments where the exception type can't be
        # resolved — match on duck-typed status / code.
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        return status == 404

    def _head_sync(self, key: str) -> bool:
        """Sync helper — True iff the blob exists."""
        blob = self.bucket.blob(key)
        return bool(blob.exists())

    def _store_sync(
        self,
        *,
        payload: bytes,
        key: str,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        blob = self.bucket.blob(key)
        if blob.exists():
            return  # content-addressing dedup
        if metadata:
            blob.metadata = metadata
        blob.upload_from_string(payload, content_type=content_type)

    def _fetch_sync(self, key: str) -> bytes:
        blob = self.bucket.blob(key)
        try:
            return blob.download_as_bytes()
        except Exception as exc:
            if self._is_not_found(exc):
                raise PayloadNotFound(
                    f"payload not found at gs://{self.bucket_name}/{key}"
                ) from exc
            raise

    def _delete_sync(self, key: str) -> bool:
        blob = self.bucket.blob(key)
        if not blob.exists():
            return False
        try:
            blob.delete()
        except Exception as exc:
            if self._is_not_found(exc):
                return False
            raise
        return True

    async def store(
        self,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> PayloadReference:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes-like")
        payload_bytes = bytes(payload)
        sha = content_hash(payload_bytes)
        key = self._key_for(sha)
        normalized_metadata = self._validate_metadata(metadata or {})
        effective_content_type = (
            content_type if content_type else self.default_content_type
        )

        await asyncio.to_thread(
            self._store_sync,
            payload=payload_bytes,
            key=key,
            content_type=effective_content_type,
            metadata=normalized_metadata,
        )

        return PayloadReference(
            sha256=sha,
            byte_length=len(payload_bytes),
            content_type=effective_content_type,
            uri=self._uri_for(key),
            metadata=normalized_metadata,
        )

    async def fetch(self, reference: PayloadReference) -> bytes:
        key = self._key_for(reference.sha256)
        return await asyncio.to_thread(self._fetch_sync, key)

    async def exists(self, reference: PayloadReference) -> bool:
        key = self._key_for(reference.sha256)
        return await asyncio.to_thread(self._head_sync, key)

    async def delete(self, reference: PayloadReference) -> bool:
        key = self._key_for(reference.sha256)
        return await asyncio.to_thread(self._delete_sync, key)
