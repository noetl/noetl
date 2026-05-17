"""Best-effort same-node IPC cache for serialized Arrow payloads."""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from multiprocessing import shared_memory
from typing import Optional

from noetl.core.logger import setup_logger
from noetl.core.storage.models import IpcHint

logger = setup_logger(__name__, include_location=True)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True)
class IpcCacheEntry:
    """Internal shared-memory allocation metadata."""

    name: str
    byte_length: int
    lease_expires_at: datetime


class ArrowIpcSharedMemoryCache:
    """Small same-node cache for Arrow IPC byte streams.

    Durable payload storage remains the authority. This class only creates and
    resolves optional `IpcHint` handles for colocated producers/consumers.
    """

    def __init__(
        self,
        *,
        namespace: str = "noetl",
        budget_bytes: Optional[int] = None,
        default_lease_seconds: float = 60.0,
        producer: Optional[str] = None,
    ) -> None:
        self.namespace = _sanitize(namespace)[:32] or "noetl"
        self.budget_bytes = int(
            budget_bytes
            if budget_bytes is not None
            else os.getenv("NOETL_IPC_CACHE_BUDGET_BYTES", 256 * 1024 * 1024)
        )
        self.default_lease_seconds = float(default_lease_seconds)
        self.producer = producer or os.getenv("HOSTNAME") or "unknown"
        self._entries: dict[str, IpcCacheEntry] = {}

    @property
    def used_bytes(self) -> int:
        return sum(entry.byte_length for entry in self._entries.values())

    def put_arrow_ipc(
        self,
        payload: bytes,
        *,
        schema_digest: str,
        row_count: Optional[int] = None,
        lease_seconds: Optional[float] = None,
        media_type: str = "application/vnd.apache.arrow.stream",
    ) -> IpcHint:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes-like")
        payload_bytes = bytes(payload)
        if not schema_digest:
            raise ValueError("schema_digest is required")
        if len(payload_bytes) > self.budget_bytes:
            raise ValueError(
                f"payload exceeds IPC cache budget: {len(payload_bytes)} > {self.budget_bytes}"
            )

        self.sweep_expired()
        self._evict_until_fits(len(payload_bytes))

        digest = hashlib.sha256(payload_bytes).hexdigest()[:8]
        stamp = format(int(time.time() * 1_000_000), "x")[-8:]
        name = f"{self.namespace[:12]}_{stamp}_{digest}"
        shm = shared_memory.SharedMemory(name=name, create=True, size=len(payload_bytes))
        try:
            shm.buf[: len(payload_bytes)] = payload_bytes
        finally:
            shm.close()

        lease = float(lease_seconds if lease_seconds is not None else self.default_lease_seconds)
        lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=lease)
        self._entries[name] = IpcCacheEntry(
            name=name,
            byte_length=len(payload_bytes),
            lease_expires_at=lease_expires_at,
        )
        return IpcHint(
            shm_name=name,
            schema_digest=schema_digest,
            byte_length=len(payload_bytes),
            row_count=row_count,
            producer=self.producer,
            lease_expires_at=lease_expires_at,
            media_type=media_type,
        )

    def get(self, hint: IpcHint) -> bytes:
        if hint.is_expired():
            raise KeyError(f"IPC hint expired: {hint.shm_name}")
        shm = shared_memory.SharedMemory(name=hint.shm_name, create=False)
        try:
            return bytes(shm.buf[: hint.byte_length])
        finally:
            shm.close()

    def delete(self, hint_or_name: IpcHint | str) -> bool:
        name = hint_or_name.shm_name if isinstance(hint_or_name, IpcHint) else str(hint_or_name)
        self._entries.pop(name, None)
        try:
            shm = shared_memory.SharedMemory(name=name, create=False)
            try:
                shm.unlink()
            finally:
                shm.close()
            return True
        except FileNotFoundError:
            return False

    def sweep_expired(self, *, now: Optional[datetime] = None, grace_seconds: float = 0) -> int:
        check_time = now or datetime.now(timezone.utc)
        if check_time.tzinfo is None:
            check_time = check_time.replace(tzinfo=timezone.utc)
        deleted = 0
        for name, entry in list(self._entries.items()):
            expires_at = entry.lease_expires_at + timedelta(seconds=grace_seconds)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if check_time > expires_at and self.delete(name):
                deleted += 1
        return deleted

    def _evict_until_fits(self, incoming_bytes: int) -> None:
        while self.used_bytes + incoming_bytes > self.budget_bytes and self._entries:
            oldest = min(self._entries.values(), key=lambda entry: entry.lease_expires_at)
            if not self.delete(oldest.name):
                self._entries.pop(oldest.name, None)
        if self.used_bytes + incoming_bytes > self.budget_bytes:
            raise ValueError("not enough IPC cache budget after eviction")


def _sanitize(value: str) -> str:
    return _SAFE_NAME.sub("_", value)


__all__ = ["ArrowIpcSharedMemoryCache", "IpcCacheEntry"]
