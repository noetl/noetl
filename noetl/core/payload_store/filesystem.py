"""Filesystem reference adapter for :class:`PayloadStore`.

Content-addressed under a sharded directory layout. Atomic writes via
temp-file + ``os.replace``. Optional per-blob metadata sidecar.

Intended uses:
- Single-node edge deployments.
- Development + tests (no cloud / Postgres / NATS required).
- The canonical reference adapter against which cloud adapters can be
  diffed in compliance tests.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from noetl.core.logger import setup_logger

from .ports import (
    PayloadNotFound,
    PayloadReference,
    PayloadStore,
    content_hash,
)

logger = setup_logger(__name__, include_location=True)

_DEFAULT_SHARD_DEPTH = 2
_DEFAULT_SHARD_WIDTH = 2  # chars per shard level
_SIDECAR_SUFFIX = ".meta.json"


class FilesystemPayloadStore(PayloadStore):
    """Content-addressed filesystem adapter.

    Layout (with default ``shard_depth=2``, ``shard_width=2``):

        <root>/<sha[0:2]>/<sha[2:4]>/<sha>
        <root>/<sha[0:2]>/<sha[2:4]>/<sha>.meta.json   (when metadata supplied)

    Two shard levels keep any single directory under ~10k entries even
    at billions of blobs. Adjustable via the constructor.
    """

    def __init__(
        self,
        root: Union[str, Path],
        *,
        shard_depth: int = _DEFAULT_SHARD_DEPTH,
        shard_width: int = _DEFAULT_SHARD_WIDTH,
        default_content_type: str = "application/octet-stream",
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        if shard_depth < 0:
            raise ValueError("shard_depth must be >= 0")
        if shard_width <= 0:
            raise ValueError("shard_width must be > 0")
        if shard_depth * shard_width > 32:
            raise ValueError(
                "shard_depth * shard_width must be <= 32 (SHA-256 hex length / 2)"
            )
        self.shard_depth = int(shard_depth)
        self.shard_width = int(shard_width)
        self.default_content_type = default_content_type
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, sha256: str) -> Path:
        if len(sha256) < self.shard_depth * self.shard_width:
            raise ValueError(
                f"sha256 prefix is shorter than the configured sharding "
                f"({len(sha256)} < {self.shard_depth * self.shard_width})"
            )
        parts: list[str] = []
        for level in range(self.shard_depth):
            start = level * self.shard_width
            parts.append(sha256[start : start + self.shard_width])
        return self.root.joinpath(*parts, sha256)

    def _sidecar_for(self, blob_path: Path) -> Path:
        return blob_path.with_name(blob_path.name + _SIDECAR_SUFFIX)

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
        target = self._path_for(sha)
        normalized_metadata = {str(k): str(v) for k, v in (metadata or {}).items()}
        effective_content_type = (
            content_type if content_type else self.default_content_type
        )

        await asyncio.to_thread(
            self._write_atomic,
            target=target,
            payload=payload_bytes,
            content_type=effective_content_type,
            metadata=normalized_metadata,
        )

        return PayloadReference(
            sha256=sha,
            byte_length=len(payload_bytes),
            content_type=effective_content_type,
            uri=str(target),
            metadata=normalized_metadata,
        )

    def _write_atomic(
        self,
        *,
        target: Path,
        payload: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        """Synchronous helper — atomic write + sidecar.

        Skips the rewrite if the blob already exists (content-addressing
        dedup). The sidecar is written even on dedup hits when metadata
        is non-empty so callers always see their metadata reflected.
        """
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)

        blob_existed = target.exists()
        if not blob_existed:
            tmp = tempfile.NamedTemporaryFile(
                delete=False,
                dir=str(parent),
                prefix=".tmp-",
                suffix=".blob",
            )
            try:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                os.replace(tmp.name, target)
            except BaseException:
                # Clean up the temp file if anything went wrong before replace
                try:
                    os.unlink(tmp.name)
                except FileNotFoundError:
                    pass
                raise

        sidecar_path = self._sidecar_for(target)
        if metadata:
            sidecar = {
                "content_type": content_type,
                "metadata": metadata,
                "byte_length": len(payload),
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            sidecar_path.write_text(json.dumps(sidecar, sort_keys=True))
        elif sidecar_path.exists() and not blob_existed:
            # Brand-new blob with no metadata: leave any stale sidecar alone;
            # callers that want clean metadata should pass it explicitly.
            pass

    async def fetch(self, reference: PayloadReference) -> bytes:
        target = self._path_for(reference.sha256)
        try:
            return await asyncio.to_thread(target.read_bytes)
        except FileNotFoundError as exc:
            raise PayloadNotFound(
                f"payload {reference.sha256} not found at {target}"
            ) from exc

    async def exists(self, reference: PayloadReference) -> bool:
        target = self._path_for(reference.sha256)
        return await asyncio.to_thread(target.exists)

    async def delete(self, reference: PayloadReference) -> bool:
        target = self._path_for(reference.sha256)
        sidecar = self._sidecar_for(target)
        return await asyncio.to_thread(self._delete_sync, target, sidecar)

    @staticmethod
    def _delete_sync(target: Path, sidecar: Path) -> bool:
        removed = False
        try:
            target.unlink()
            removed = True
        except FileNotFoundError:
            pass
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass
        return removed
