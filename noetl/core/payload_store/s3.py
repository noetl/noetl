"""S3 / S3-compatible adapter for :class:`PayloadStore`.

Implements the same Protocol contract as
:class:`FilesystemPayloadStore`. Works against AWS S3 and any
S3-compatible endpoint (MinIO, SeaweedFS in S3 mode, LocalStack) via
the optional ``endpoint_url`` constructor argument.

Design notes:

- **Key layout** mirrors the filesystem adapter:
  ``<prefix>/<sha[0:2]>/<sha[2:4]>/<sha>``. Same sharding rationale —
  any single S3 listing stays bounded.
- **Atomicity** is intrinsic to S3 PUT — no temp + rename ceremony.
- **Content-addressing dedup** via ``HeadObject`` before PUT.
- **Metadata** rides as native S3 object metadata
  (``Metadata=...`` on PutObject; surfaced in HeadObject /
  GetObject responses). No sidecar object — keeps the bucket
  layout flat. S3 requires ASCII metadata keys + values; the
  adapter validates at the boundary.
- **Delete** is Protocol-compliant (``True`` if a payload was
  removed, ``False`` if already absent). Implemented as
  HeadObject + DeleteObject because S3's DeleteObject is
  idempotent and doesn't distinguish present-vs-absent.
- **Sync boto3 + asyncio.to_thread.** The Protocol exposes async
  methods; the implementation bridges through a thread pool. Same
  pattern as :class:`FilesystemPayloadStore`. Trade: a per-call
  thread vs. event-loop integration. Worth it for testability
  (``moto.mock_aws`` only intercepts sync boto3) and operational
  consistency with the filesystem adapter.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

try:
    import boto3  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - boto3 is a runtime dep
    boto3 = None  # type: ignore[assignment]

try:
    from botocore.exceptions import ClientError  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - botocore comes with boto3 runtime dep
    ClientError = Exception  # type: ignore[assignment,misc]

from noetl.core.logger import setup_logger

from .ports import (
    PayloadNotFound,
    PayloadReference,
    PayloadStore,
    content_hash,
)

logger = setup_logger(__name__, include_location=True)


class S3PayloadStore(PayloadStore):
    """Async S3 / S3-compatible adapter.

    Constructor takes the bucket name and optional configuration:

    - ``prefix`` — string prepended to every object key. Useful when
      a single bucket hosts payloads alongside other namespaces.
    - ``client`` — pre-configured boto3 S3 client. When ``None``, a
      default client is constructed via
      ``boto3.client("s3", region_name=region_name, endpoint_url=endpoint_url)``
      and credentials come from the standard boto3 chain.
    - ``endpoint_url`` — override for MinIO / SeaweedFS / LocalStack.
    - ``region_name`` — explicit region (used when creating the
      default client).
    - ``default_content_type`` — used when ``store(content_type=...)``
      is omitted or empty.
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        client: Optional[Any] = None,
        endpoint_url: Optional[str] = None,
        region_name: Optional[str] = None,
        default_content_type: str = "application/octet-stream",
    ) -> None:
        if boto3 is None:  # pragma: no cover - exercised when extra missing
            raise RuntimeError(
                "S3PayloadStore requires boto3; install noetl with the "
                "default runtime dependencies"
            )
        if not bucket:
            raise ValueError("bucket name is required")
        self.bucket = str(bucket)
        self.prefix = prefix.lstrip("/").rstrip("/") if prefix else ""
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.default_content_type = default_content_type
        if client is None:
            client_kwargs: dict[str, Any] = {}
            if region_name:
                client_kwargs["region_name"] = region_name
            if endpoint_url:
                client_kwargs["endpoint_url"] = endpoint_url
            self.client = boto3.client("s3", **client_kwargs)
        else:
            self.client = client

    def _key_for(self, sha256: str) -> str:
        """Return the S3 object key for a payload digest."""
        if len(sha256) < 4:
            raise ValueError(
                f"sha256 prefix must be at least 4 chars for sharding (got {len(sha256)})"
            )
        sharded = f"{sha256[0:2]}/{sha256[2:4]}/{sha256}"
        return f"{self.prefix}/{sharded}" if self.prefix else sharded

    def _uri_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    @staticmethod
    def _validate_metadata(metadata: dict[str, str]) -> dict[str, str]:
        """S3 requires ASCII-only metadata keys and values."""
        normalized: dict[str, str] = {}
        for raw_key, raw_value in metadata.items():
            key = str(raw_key)
            value = str(raw_value)
            try:
                key.encode("ascii")
                value.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f"S3 metadata key/value must be ASCII: {raw_key!r}={raw_value!r}"
                ) from exc
            normalized[key] = value
        return normalized

    @staticmethod
    def _is_not_found(exc: BaseException) -> bool:
        """True iff the boto3 client error indicates the key is missing."""
        if not isinstance(exc, ClientError):
            return False
        response = getattr(exc, "response", {}) or {}
        error = response.get("Error", {})
        code = str(error.get("Code") or "")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in {"404", "NoSuchKey", "NotFound"} or status == 404

    def _head(self, key: str) -> bool:
        """Sync helper — True iff the object exists; raises on other errors."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if self._is_not_found(exc):
                return False
            raise

    def _store_sync(
        self,
        *,
        payload: bytes,
        key: str,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        if self._head(key):
            return  # content-addressing dedup
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
            Metadata=metadata,
        )

    def _fetch_sync(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if self._is_not_found(exc):
                raise PayloadNotFound(
                    f"payload not found at s3://{self.bucket}/{key}"
                ) from exc
            raise
        body = response["Body"]
        try:
            return body.read()
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                close()

    def _delete_sync(self, key: str) -> bool:
        if not self._head(key):
            return False
        self.client.delete_object(Bucket=self.bucket, Key=key)
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
        return await asyncio.to_thread(self._head, key)

    async def delete(self, reference: PayloadReference) -> bool:
        key = self._key_for(reference.sha256)
        return await asyncio.to_thread(self._delete_sync, key)
