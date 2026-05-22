"""Azure Blob Storage adapter for :class:`PayloadStore`.

Implements the same Protocol contract as
:class:`FilesystemPayloadStore`, :class:`S3PayloadStore`, and
:class:`GCSPayloadStore`.

Design notes:

- **Key layout** mirrors the other adapters:
  ``<prefix>/<sha[0:2]>/<sha[2:4]>/<sha>``. Same sharding rationale —
  any single container listing stays bounded.
- **Atomicity** is intrinsic to Azure Blob ``upload_blob`` — no temp +
  rename ceremony.
- **Content-addressing dedup** via ``BlobClient.exists()`` before
  ``upload_blob``.
- **Metadata** rides as Azure Blob custom metadata (``x-ms-meta-*``
  headers), passed via the ``metadata=`` kwarg on ``upload_blob``.
  Azure requires metadata keys to be valid **C# identifiers**
  (ASCII letters / digits / underscore; must start with a letter or
  underscore). Values must be ASCII for portability. The adapter
  validates at the boundary.
- **Content type** is conveyed through
  ``ContentSettings(content_type=...)``.
- **Delete** is Protocol-compliant (``True`` if a payload was
  removed, ``False`` if already absent). Implemented as
  ``BlobClient.exists()`` + ``BlobClient.delete_blob()`` because
  ``delete_blob`` raises ``ResourceNotFoundError`` on missing keys
  rather than reporting a boolean.
- **Sync azure-storage-blob + asyncio.to_thread.** The SDK ships an
  ``aio`` submodule, but using it would force aio-aware testing
  infrastructure and risk a repeat of the round-2 aioboto3/moto
  trap. Sync + thread bridging is the canonical cloud-adapter
  pattern in NoETL.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

try:
    from azure.storage.blob import (  # type: ignore[import-not-found]
        BlobServiceClient,
        ContentSettings,
    )
except ImportError:  # pragma: no cover - azure-storage-blob is a runtime dep
    BlobServiceClient = None  # type: ignore[assignment,misc]
    ContentSettings = None  # type: ignore[assignment,misc]

try:
    from azure.core.exceptions import ResourceNotFoundError  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - azure-core ships with azure-storage-blob
    ResourceNotFoundError = Exception  # type: ignore[assignment,misc]

from noetl.core.logger import setup_logger

from .ports import (
    PayloadNotFound,
    PayloadReference,
    PayloadStore,
    content_hash,
)

logger = setup_logger(__name__, include_location=True)

_CSHARP_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AzureBlobPayloadStore(PayloadStore):
    """Async Azure Blob Storage adapter.

    Constructor takes the container name and optional configuration:

    - ``prefix`` — string prepended to every blob name. Useful when
      a single container hosts payloads alongside other namespaces.
    - ``account_url`` — e.g.
      ``https://<account>.blob.core.windows.net``. Required when
      ``connection_string`` is not provided and ``client`` is
      ``None``.
    - ``credential`` — ``TokenCredential`` (typically
      ``DefaultAzureCredential``), account-key string, or SAS token.
      Used when constructing the default ``BlobServiceClient`` from
      ``account_url``.
    - ``connection_string`` — full Azure storage connection string.
      Preferred for local / Azurite work. When set, takes precedence
      over ``account_url`` + ``credential`` for building the default
      client.
    - ``client`` — pre-configured ``BlobServiceClient``. When
      ``None``, the adapter builds one from
      ``connection_string`` or ``account_url`` + ``credential``.
    - ``default_content_type`` — used when ``store(content_type=...)``
      is omitted or empty.
    """

    def __init__(
        self,
        container: str,
        *,
        prefix: str = "",
        account_url: Optional[str] = None,
        credential: Optional[Any] = None,
        connection_string: Optional[str] = None,
        client: Optional[Any] = None,
        default_content_type: str = "application/octet-stream",
    ) -> None:
        if BlobServiceClient is None:  # pragma: no cover - exercised when extra missing
            raise RuntimeError(
                "AzureBlobPayloadStore requires azure-storage-blob; install "
                "noetl with the default runtime dependencies"
            )
        if not container:
            raise ValueError("container name is required")
        self.container_name = str(container)
        self.prefix = prefix.lstrip("/").rstrip("/") if prefix else ""
        self.default_content_type = default_content_type
        if client is None:
            if connection_string:
                self.client = BlobServiceClient.from_connection_string(
                    connection_string
                )
            elif account_url:
                self.client = BlobServiceClient(
                    account_url=account_url, credential=credential
                )
            else:
                raise ValueError(
                    "AzureBlobPayloadStore requires one of: client, "
                    "connection_string, or account_url"
                )
        else:
            self.client = client
        self.container_client = self.client.get_container_client(self.container_name)

    def _key_for(self, sha256: str) -> str:
        """Return the blob name for a payload digest."""
        if len(sha256) < 4:
            raise ValueError(
                f"sha256 prefix must be at least 4 chars for sharding (got {len(sha256)})"
            )
        sharded = f"{sha256[0:2]}/{sha256[2:4]}/{sha256}"
        return f"{self.prefix}/{sharded}" if self.prefix else sharded

    def _uri_for(self, key: str) -> str:
        account = getattr(self.client, "account_name", None)
        if account:
            return f"azure://{account}/{self.container_name}/{key}"
        return f"azure://{self.container_name}/{key}"

    @staticmethod
    def _validate_metadata(metadata: dict[str, str]) -> dict[str, str]:
        """Azure requires C#-identifier keys + ASCII values."""
        normalized: dict[str, str] = {}
        for raw_key, raw_value in metadata.items():
            key = str(raw_key)
            value = str(raw_value)
            if not _CSHARP_IDENT.fullmatch(key):
                raise ValueError(
                    f"Azure metadata key must be a valid C# identifier "
                    f"(letters / digits / underscore, starting with a letter "
                    f"or underscore): {raw_key!r}"
                )
            try:
                value.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f"Azure metadata value must be ASCII: {raw_key!r}={raw_value!r}"
                ) from exc
            normalized[key] = value
        return normalized

    @staticmethod
    def _is_not_found(exc: BaseException) -> bool:
        """True iff the Azure client error indicates the blob is missing."""
        if isinstance(exc, ResourceNotFoundError):
            return True
        status = getattr(exc, "status_code", None)
        return status == 404

    def _blob_client(self, key: str) -> Any:
        return self.container_client.get_blob_client(key)

    def _head_sync(self, key: str) -> bool:
        """Sync helper — True iff the blob exists."""
        return bool(self._blob_client(key).exists())

    def _store_sync(
        self,
        *,
        payload: bytes,
        key: str,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        blob = self._blob_client(key)
        if blob.exists():
            return  # content-addressing dedup
        content_settings = ContentSettings(content_type=content_type)
        blob.upload_blob(
            payload,
            content_settings=content_settings,
            metadata=metadata or None,
        )

    def _fetch_sync(self, key: str) -> bytes:
        blob = self._blob_client(key)
        try:
            stream = blob.download_blob()
            return stream.readall()
        except Exception as exc:
            if self._is_not_found(exc):
                raise PayloadNotFound(
                    f"payload not found at azure://{self.container_name}/{key}"
                ) from exc
            raise

    def _delete_sync(self, key: str) -> bool:
        blob = self._blob_client(key)
        if not blob.exists():
            return False
        try:
            blob.delete_blob()
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
