"""
Storage backends for NoETL ResultStore.

Implements drivers for each storage tier (aligned with RisingWave
three-tier hot/warm/cold hierarchy):

- Memory (hot, <10KB, step-scoped, in-process dict)
- NATS KV (warm, <1MB, execution-scoped, distributed cache)
- DiskCache (warm, >=1MB, local SSD/NVMe + async cloud spill; phase 1)
- S3/MinIO (cold/durable, any size; MinIO via NOETL_S3_ENDPOINT)
- GCS (cold/durable, any size)

Phase 0 removes the previous `NATSObjectBackend` ("object" tier).
Payloads carrying `store: "object"` are auto-mapped to `"disk"` by
`noetl.core.storage.models._normalize_store_value` with a one-time
deprecation warning.

See `docs/features/noetl_storage_and_streaming_alignment.md`.

Each backend implements async get/put/delete operations.
"""

import asyncio
import gzip
import hashlib
import json
import os
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    async def put(self, key: str, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Store data and return storage URI."""
        pass

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve data by key."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete data by key."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        pass


class MemoryBackend(StorageBackend):
    """In-memory storage for step-scoped small data."""

    def __init__(self, max_size_bytes: int = 10 * 1024 * 1024):  # 10MB default
        self._cache: Dict[str, Tuple[bytes, Dict[str, Any]]] = {}
        self._max_size = max_size_bytes
        self._current_size = 0

    async def put(self, key: str, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> str:
        # Evict if needed
        while self._current_size + len(data) > self._max_size and self._cache:
            oldest_key = next(iter(self._cache))
            old_data, _ = self._cache.pop(oldest_key)
            self._current_size -= len(old_data)
            logger.debug(f"[MEMORY] Evicted {oldest_key} ({len(old_data)} bytes)")

        self._cache[key] = (data, metadata or {})
        self._current_size += len(data)
        logger.debug(f"[MEMORY] Stored {key} ({len(data)} bytes)")
        return f"memory://{key}"

    async def get(self, key: str) -> bytes:
        if key not in self._cache:
            raise KeyError(f"Key not found in memory: {key}")
        data, _ = self._cache[key]
        return data

    async def delete(self, key: str) -> bool:
        if key in self._cache:
            data, _ = self._cache.pop(key)
            self._current_size -= len(data)
            return True
        return False

    async def exists(self, key: str) -> bool:
        return key in self._cache


class NATSKVBackend(StorageBackend):
    """NATS JetStream KV store for distributed caching (< 1MB)."""

    def __init__(
        self,
        bucket_name: str = "noetl_result_store",
        nats_url: Optional[str] = None,
        max_value_size: int = 1024 * 1024,  # 1MB NATS limit
    ):
        self._bucket_name = bucket_name
        self._nats_url = nats_url or os.getenv("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
        self._max_value_size = max_value_size
        self._nc = None
        self._js = None
        self._kv = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self):
        """Ensure NATS connection is established."""
        if self._kv is not None:
            return

        async with self._lock:
            if self._kv is not None:
                return

            try:
                import nats
                # Use env vars directly to avoid full config validation (workers don't have DB settings)
                nats_user = os.getenv("NATS_USER", "")
                nats_password = os.getenv("NATS_PASSWORD", "")

                connect_kwargs = {
                    "servers": [self._nats_url],
                    "name": "noetl_result_store"
                }
                if nats_user and nats_password:
                    connect_kwargs["user"] = nats_user
                    connect_kwargs["password"] = nats_password

                self._nc = await nats.connect(**connect_kwargs)
                self._js = self._nc.jetstream()

                # Create or get KV bucket
                try:
                    self._kv = await self._js.create_key_value(
                        bucket=self._bucket_name,
                        description="NoETL result storage",
                        ttl=7200,  # 2 hour TTL
                        max_value_size=self._max_value_size,
                        history=1,
                    )
                    logger.info(f"[NATS-KV] Created bucket: {self._bucket_name}")
                except Exception:
                    self._kv = await self._js.key_value(self._bucket_name)
                    logger.info(f"[NATS-KV] Connected to existing bucket: {self._bucket_name}")

            except Exception as e:
                logger.error(f"[NATS-KV] Connection failed: {e}")
                raise

    def _make_key(self, key: str) -> str:
        """Sanitize key for NATS KV (dots as separators)."""
        return str(key).replace("/", ".").replace(":", ".")

    async def put(self, key: str, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> str:
        await self._ensure_connected()

        if len(data) > self._max_value_size:
            raise ValueError(f"Data too large for NATS KV: {len(data)} > {self._max_value_size}")

        nats_key = self._make_key(key)
        await self._kv.put(nats_key, data)
        logger.debug(f"[NATS-KV] Stored {nats_key} ({len(data)} bytes)")
        return f"nats-kv://{self._bucket_name}/{nats_key}"

    async def get(self, key: str) -> bytes:
        await self._ensure_connected()

        nats_key = self._make_key(key)
        try:
            entry = await self._kv.get(nats_key)
            if entry and entry.value:
                return entry.value
            raise KeyError(f"Key not found: {nats_key}")
        except Exception as e:
            if "no message found" in str(e).lower():
                raise KeyError(f"Key not found: {nats_key}")
            raise

    async def delete(self, key: str) -> bool:
        await self._ensure_connected()

        nats_key = self._make_key(key)
        try:
            await self._kv.delete(nats_key)
            return True
        except Exception as e:
            logger.warning(f"[NATS-KV] Delete failed for {nats_key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        await self._ensure_connected()

        nats_key = self._make_key(key)
        try:
            entry = await self._kv.get(nats_key)
            return entry is not None and entry.value is not None
        except Exception:
            return False


class StorageNotImplementedError(NotImplementedError):
    """Backend is declared but not yet implemented in the current phase."""


class _TokenBucket:
    """Async token bucket rate limiter (bytes/sec). 0 rate = unlimited."""

    def __init__(self, rate_bytes_per_sec: int, burst_bytes: Optional[int] = None):
        self._rate = max(0, int(rate_bytes_per_sec))
        self._capacity = burst_bytes if burst_bytes is not None else max(self._rate, 1)
        self._tokens = float(self._capacity)
        self._last = asyncio.get_event_loop().time() if False else None  # lazy-init
        self._lock = asyncio.Lock()

    async def take(self, n: int) -> None:
        if self._rate <= 0 or n <= 0:
            return
        async with self._lock:
            loop = asyncio.get_event_loop()
            if self._last is None:
                self._last = loop.time()
            while True:
                now = loop.time()
                delta = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + delta * self._rate)
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # Not enough tokens; wait for the shortfall.
                need = n - self._tokens
                wait = need / self._rate
                await asyncio.sleep(wait)


class _DiskCachePool:
    """
    Single-tier local disk cache with LRU eviction.

    Used as a building block for DiskCacheBackend's meta + data pools.
    Safe for concurrent coroutines on one event loop; not cross-process.
    """

    def __init__(
        self,
        root_dir: str,
        capacity_bytes: int,
        rate_limiter: Optional[_TokenBucket],
        name: str,
    ):
        self._root = root_dir
        self._capacity = max(0, int(capacity_bytes))
        self._rate = rate_limiter
        self._name = name
        # OrderedDict: key -> (file_path, size_bytes). move_to_end on access = LRU.
        self._index: "OrderedDict[str, tuple[str, int]]" = OrderedDict()
        self._current_bytes = 0
        self._lock = asyncio.Lock()
        self._dirs_created = False

    def _ensure_dirs(self) -> None:
        """Create cache directories on first write. Deferred so instantiation is side-effect free."""
        if self._dirs_created:
            return
        os.makedirs(os.path.join(self._root, "tmp"), exist_ok=True)
        self._dirs_created = True

    def _key_to_rel_path(self, key: str) -> str:
        # Hash keeps filenames bounded and avoids special-char issues.
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return os.path.join(h[:2], h)

    def _abs_path(self, key: str) -> str:
        return os.path.join(self._root, self._key_to_rel_path(key))

    async def warm_start(self) -> int:
        """Re-index on-disk files. Returns bytes indexed."""
        indexed = 0
        if not os.path.isdir(self._root):
            return 0
        entries: list[tuple[str, int, float]] = []
        for dirpath, _dirnames, filenames in os.walk(self._root):
            # skip tmp/
            if os.path.basename(dirpath) == "tmp":
                continue
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                entries.append((full, st.st_size, st.st_mtime))
        # Sort oldest-first so LRU order after insertion matches mtime order.
        entries.sort(key=lambda e: e[2])
        for full, size, _mt in entries:
            # On-disk layout is <root>/<hash[:2]>/<hash>. The full sha256
            # filename IS the cache-index key used by put()/get(), so we
            # just take the basename.
            cache_key = os.path.basename(full)
            async with self._lock:
                self._index[cache_key] = (full, size)
                self._current_bytes += size
                indexed += size
        logger.info(
            f"[DISK:{self._name}] warm-start indexed {len(entries)} files / {indexed} bytes"
        )
        return indexed

    async def _evict_until_fits(self, incoming: int) -> None:
        if self._capacity <= 0:
            return
        while self._current_bytes + incoming > self._capacity and self._index:
            # Pop LRU
            key, (path, size) = self._index.popitem(last=False)
            self._current_bytes -= size
            try:
                os.remove(path)
            except OSError as e:
                logger.debug(f"[DISK:{self._name}] evict remove failed {path}: {e}")
            logger.debug(
                f"[DISK:{self._name}] evicted {key[:16]}... ({size} bytes); "
                f"current={self._current_bytes}"
            )

    async def put(self, key: str, data: bytes) -> str:
        # Hash-based cache-index key (see warm_start for the reasoning).
        cache_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        abs_path = self._abs_path(key)
        size = len(data)

        if self._rate:
            await self._rate.take(size)

        self._ensure_dirs()
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        tmp_path = os.path.join(
            self._root,
            "tmp",
            f"{cache_key}.{os.getpid()}.{id(asyncio.current_task())}.tmp",
        )

        # Atomic write: tmp + rename. We offload sync I/O to the default executor.
        loop = asyncio.get_event_loop()

        def _write_and_rename() -> None:
            with open(tmp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, abs_path)

        try:
            await loop.run_in_executor(None, _write_and_rename)
        except Exception:
            # Best-effort cleanup of orphan tmp.
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

        async with self._lock:
            # If re-inserting an existing key, subtract old size first.
            if cache_key in self._index:
                _old_path, old_size = self._index.pop(cache_key)
                self._current_bytes -= old_size
            await self._evict_until_fits(size)
            self._index[cache_key] = (abs_path, size)
            self._current_bytes += size

        return f"disk://{self._name}/{cache_key}"

    async def get(self, key: str) -> bytes:
        cache_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        async with self._lock:
            entry = self._index.get(cache_key)
            if entry is None:
                raise KeyError(f"disk-cache miss: {cache_key}")
            abs_path, _size = entry
            self._index.move_to_end(cache_key)  # LRU: mark as fresh

        loop = asyncio.get_event_loop()

        def _read() -> bytes:
            with open(abs_path, "rb") as f:
                return f.read()

        try:
            return await loop.run_in_executor(None, _read)
        except FileNotFoundError:
            # On-disk entry vanished behind our back; drop index entry.
            async with self._lock:
                entry2 = self._index.pop(cache_key, None)
                if entry2 is not None:
                    self._current_bytes -= entry2[1]
            raise KeyError(f"disk-cache on-disk file missing: {cache_key}")

    async def delete(self, key: str) -> bool:
        cache_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        async with self._lock:
            entry = self._index.pop(cache_key, None)
            if entry is None:
                return False
            abs_path, size = entry
            self._current_bytes -= size
        try:
            os.remove(abs_path)
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            logger.warning(f"[DISK:{self._name}] delete failed {abs_path}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        cache_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return cache_key in self._index

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "entries": len(self._index),
            "current_bytes": self._current_bytes,
            "capacity_bytes": self._capacity,
        }


class DiskCacheBackend(StorageBackend):
    """
    Local SSD/NVMe disk cache with async spill to a cloud backend.

    RisingWave-aligned two-pool design:
    - meta pool (~10% of total capacity): small refs + metadata payloads
    - data pool (~90% of total capacity): payload blocks

    Each pool has independent capacity, LRU eviction, and a shared
    token-bucket rate limiter on insert. Pools can optionally warm-start
    by re-indexing on-disk entries (`recover_mode=Quiet`).

    On `put`:
    1. Pool decides meta vs data by `size < meta_threshold_bytes`.
    2. Bytes are written to disk atomically (tmp + rename + fsync).
    3. If a cloud backend is configured, a background task uploads the
       payload to provide durability beyond the local pod. Failures are
       logged; the local copy is authoritative for the read path.

    On `get`:
    1. Local pool is checked first (hot path).
    2. On miss, cloud backend is consulted (if configured); a hit is
       re-inserted into the local pool for future reads (read-through).
    3. On second miss, `KeyError` is raised.

    Thread-safety: every pool's in-memory index is guarded by an
    `asyncio.Lock`; the backend is intended for a single event loop per
    process.
    """

    # Entries smaller than this go to the meta pool. 10 KB matches the
    # MEMORY tier threshold in router.StorageRouter.
    META_ENTRY_THRESHOLD_BYTES = 10 * 1024

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        data_capacity_mb: Optional[int] = None,
        meta_capacity_mb: Optional[int] = None,
        insert_rate_limit_mb: Optional[int] = None,
        recover_mode: str = "None",
        cloud_backend: Optional[StorageBackend] = None,
    ):
        self._cache_dir = cache_dir or os.getenv(
            "NOETL_STORAGE_LOCAL_CACHE_DIR", "/opt/noetl/data/disk_cache"
        )
        self._data_capacity_mb = int(
            data_capacity_mb
            if data_capacity_mb is not None
            else os.getenv("NOETL_STORAGE_LOCAL_DATA_CACHE_CAPACITY_MB", "0") or 0
        )
        self._meta_capacity_mb = int(
            meta_capacity_mb
            if meta_capacity_mb is not None
            else os.getenv("NOETL_STORAGE_LOCAL_META_CACHE_CAPACITY_MB", "0") or 0
        )
        self._insert_rate_limit_mb = int(
            insert_rate_limit_mb
            if insert_rate_limit_mb is not None
            else os.getenv("NOETL_STORAGE_LOCAL_CACHE_INSERT_RATE_MB", "0") or 0
        )
        self._recover_mode = (
            recover_mode
            if recover_mode and recover_mode != "None"
            else os.getenv("NOETL_STORAGE_LOCAL_CACHE_RECOVER_MODE", "None")
        )
        self._cloud = cloud_backend

        # Shared rate limiter across both pools so total insert throughput
        # is bounded by the configured cap.
        rate_bps = self._insert_rate_limit_mb * 1024 * 1024
        self._limiter = _TokenBucket(rate_bps) if rate_bps > 0 else None

        meta_bytes = self._meta_capacity_mb * 1024 * 1024
        data_bytes = self._data_capacity_mb * 1024 * 1024
        self._meta_pool = _DiskCachePool(
            os.path.join(self._cache_dir, "meta"), meta_bytes, self._limiter, "meta"
        )
        self._data_pool = _DiskCachePool(
            os.path.join(self._cache_dir, "data"), data_bytes, self._limiter, "data"
        )

        self._warm_started = False
        self._warm_lock = asyncio.Lock()

    def _pool_for(self, size: int) -> _DiskCachePool:
        if size < self.META_ENTRY_THRESHOLD_BYTES and self._meta_pool._capacity > 0:
            return self._meta_pool
        return self._data_pool

    async def _maybe_warm_start(self) -> None:
        if self._warm_started:
            return
        async with self._warm_lock:
            if self._warm_started:
                return
            if self._recover_mode == "Quiet":
                await self._meta_pool.warm_start()
                await self._data_pool.warm_start()
            self._warm_started = True

    async def _spill_to_cloud(self, key: str, data: bytes) -> None:
        if self._cloud is None:
            return
        try:
            await self._cloud.put(key, data)
        except Exception as e:
            logger.warning(f"[DISK] cloud spill failed for {key}: {e}")

    async def put(
        self, key: str, data: bytes, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        await self._maybe_warm_start()
        pool = self._pool_for(len(data))
        uri = await pool.put(key, data)

        # Fire-and-forget cloud spill. Exceptions are caught inside.
        if self._cloud is not None:
            try:
                asyncio.create_task(self._spill_to_cloud(key, data))
            except RuntimeError:
                # No running loop — do it inline to preserve durability.
                await self._spill_to_cloud(key, data)

        logger.debug(
            f"[DISK] put key={key[:64]} size={len(data)} pool={pool._name} uri={uri}"
        )
        return uri

    async def _read_through_cloud(self, key: str) -> bytes:
        if self._cloud is None:
            raise KeyError(f"disk-cache miss and no cloud backend: {key}")
        data = await self._cloud.get(key)
        # Read-through: populate local pool for next time.
        pool = self._pool_for(len(data))
        try:
            await pool.put(key, data)
        except Exception as e:
            logger.debug(f"[DISK] read-through populate failed: {e}")
        return data

    async def get(self, key: str) -> bytes:
        await self._maybe_warm_start()
        # Try data pool first (covers the >= 1 MB hot path).
        try:
            return await self._data_pool.get(key)
        except KeyError:
            pass
        try:
            return await self._meta_pool.get(key)
        except KeyError:
            pass
        # Local miss — fall through to cloud.
        return await self._read_through_cloud(key)

    async def delete(self, key: str) -> bool:
        await self._maybe_warm_start()
        deleted = False
        deleted = await self._data_pool.delete(key) or deleted
        deleted = await self._meta_pool.delete(key) or deleted
        if self._cloud is not None:
            try:
                deleted = await self._cloud.delete(key) or deleted
            except Exception as e:
                logger.debug(f"[DISK] cloud delete failed: {e}")
        return deleted

    async def exists(self, key: str) -> bool:
        await self._maybe_warm_start()
        if await self._data_pool.exists(key):
            return True
        if await self._meta_pool.exists(key):
            return True
        if self._cloud is not None:
            try:
                return await self._cloud.exists(key)
            except Exception:
                return False
        return False

    def stats(self) -> Dict[str, Any]:
        return {
            "meta": self._meta_pool.stats(),
            "data": self._data_pool.stats(),
            "cloud": "configured" if self._cloud else None,
            "recover_mode": self._recover_mode,
        }


class S3Backend(StorageBackend):
    """S3/MinIO storage for large objects."""

    def __init__(
        self,
        bucket: str = "noetl-results",
        prefix: str = "results/",
        endpoint_url: Optional[str] = None,
        region: str = "us-east-1",
    ):
        self._bucket = bucket
        self._prefix = prefix
        self._endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT_URL")
        self._region = region
        self._client = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self):
        """Ensure S3 client is initialized."""
        if self._client is not None:
            return

        async with self._lock:
            if self._client is not None:
                return

            try:
                import aioboto3
                session = aioboto3.Session()

                client_kwargs = {
                    "service_name": "s3",
                    "region_name": self._region,
                }
                if self._endpoint_url:
                    client_kwargs["endpoint_url"] = self._endpoint_url

                self._session = session
                logger.info(f"[S3] Initialized client for bucket: {self._bucket}")
            except ImportError:
                logger.error("[S3] aioboto3 not installed. Install with: pip install aioboto3")
                raise

    def _make_key(self, key: str) -> str:
        """Create S3 object key."""
        safe_key = key.replace("noetl://", "").replace(":", "/")
        return f"{self._prefix}{safe_key}"

    async def put(self, key: str, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> str:
        await self._ensure_client()

        s3_key = self._make_key(key)
        client_kwargs = {"service_name": "s3", "region_name": self._region}
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url

        async with self._session.client(**client_kwargs) as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=data,
                ContentType="application/octet-stream",
                Metadata=metadata or {}
            )

        uri = f"s3://{self._bucket}/{s3_key}"
        logger.debug(f"[S3] Stored {s3_key} ({len(data)} bytes)")
        return uri

    async def get(self, key: str) -> bytes:
        await self._ensure_client()

        s3_key = self._make_key(key)
        client_kwargs = {"service_name": "s3", "region_name": self._region}
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url

        async with self._session.client(**client_kwargs) as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=s3_key)
                async with response["Body"] as stream:
                    return await stream.read()
            except Exception as e:
                if "NoSuchKey" in str(e):
                    raise KeyError(f"S3 object not found: {s3_key}")
                raise

    async def delete(self, key: str) -> bool:
        await self._ensure_client()

        s3_key = self._make_key(key)
        client_kwargs = {"service_name": "s3", "region_name": self._region}
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url

        try:
            async with self._session.client(**client_kwargs) as s3:
                await s3.delete_object(Bucket=self._bucket, Key=s3_key)
            return True
        except Exception as e:
            logger.warning(f"[S3] Delete failed for {s3_key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        await self._ensure_client()

        s3_key = self._make_key(key)
        client_kwargs = {"service_name": "s3", "region_name": self._region}
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url

        try:
            async with self._session.client(**client_kwargs) as s3:
                await s3.head_object(Bucket=self._bucket, Key=s3_key)
            return True
        except Exception:
            return False


class GCSBackend(StorageBackend):
    """Google Cloud Storage backend for large objects."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        credentials_json: Optional[str] = None,
    ):
        self._bucket_name = bucket or os.getenv("NOETL_GCS_BUCKET", "noetl-results")
        self._prefix = prefix or os.getenv("NOETL_GCS_PREFIX", "results/")
        self._credentials_json = credentials_json or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self._client = None
        self._bucket = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self):
        """Ensure GCS client is initialized."""
        if self._client is not None:
            return

        async with self._lock:
            if self._client is not None:
                return

            try:
                from google.cloud import storage
                from google.oauth2 import service_account

                if self._credentials_json and os.path.exists(self._credentials_json):
                    credentials = service_account.Credentials.from_service_account_file(
                        self._credentials_json
                    )
                    self._client = storage.Client(credentials=credentials)
                else:
                    # Use default credentials (ADC)
                    self._client = storage.Client()

                self._bucket = self._client.bucket(self._bucket_name)
                logger.info(f"[GCS] Initialized client for bucket: {self._bucket_name}")

            except ImportError:
                logger.error("[GCS] google-cloud-storage not installed")
                raise

    def _make_key(self, key: str) -> str:
        """Create GCS object key."""
        safe_key = key.replace("noetl://", "").replace(":", "/")
        return f"{self._prefix}{safe_key}"

    async def put(self, key: str, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> str:
        await self._ensure_client()

        gcs_key = self._make_key(key)

        # GCS operations are sync, run in executor
        loop = asyncio.get_event_loop()

        def _upload():
            blob = self._bucket.blob(gcs_key)
            if metadata:
                blob.metadata = metadata
            blob.upload_from_string(data, content_type="application/octet-stream")
            return f"gs://{self._bucket_name}/{gcs_key}"

        uri = await loop.run_in_executor(None, _upload)
        logger.debug(f"[GCS] Stored {gcs_key} ({len(data)} bytes)")
        return uri

    async def get(self, key: str) -> bytes:
        await self._ensure_client()

        gcs_key = self._make_key(key)
        loop = asyncio.get_event_loop()

        def _download():
            blob = self._bucket.blob(gcs_key)
            if not blob.exists():
                raise KeyError(f"GCS object not found: {gcs_key}")
            return blob.download_as_bytes()

        return await loop.run_in_executor(None, _download)

    async def delete(self, key: str) -> bool:
        await self._ensure_client()

        gcs_key = self._make_key(key)
        loop = asyncio.get_event_loop()

        def _delete():
            blob = self._bucket.blob(gcs_key)
            try:
                blob.delete()
                return True
            except Exception as e:
                logger.warning(f"[GCS] Delete failed for {gcs_key}: {e}")
                return False

        return await loop.run_in_executor(None, _delete)

    async def exists(self, key: str) -> bool:
        await self._ensure_client()

        gcs_key = self._make_key(key)
        loop = asyncio.get_event_loop()

        def _exists():
            blob = self._bucket.blob(gcs_key)
            return blob.exists()

        return await loop.run_in_executor(None, _exists)


# Factory function
def get_backend(tier: str, **kwargs) -> StorageBackend:
    """Get storage backend by tier name."""
    # Back-compat: map removed "object" tier to "disk" with a warning.
    # The warning itself is emitted by noetl.core.storage.models._normalize_store_value
    # on first exposure; here we just rewrite silently to avoid duplicate noise.
    tier_lc = (tier or "").lower()
    if tier_lc == "object":
        tier_lc = "disk"

    backends = {
        "memory": MemoryBackend,
        "kv": NATSKVBackend,
        "disk": DiskCacheBackend,
        "s3": S3Backend,
        "gcs": GCSBackend,
    }

    backend_class = backends.get(tier_lc)
    if not backend_class:
        raise ValueError(f"Unknown storage tier: {tier}")

    return backend_class(**kwargs)


__all__ = [
    "StorageBackend",
    "MemoryBackend",
    "NATSKVBackend",
    "DiskCacheBackend",
    "S3Backend",
    "GCSBackend",
    "StorageNotImplementedError",
    "get_backend",
]
