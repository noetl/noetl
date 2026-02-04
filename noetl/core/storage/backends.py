"""
Storage backends for NoETL ResultStore.

Implements drivers for each storage tier:
- NATS KV: < 1MB, execution-scoped (distributed cache)
- NATS Object Store: < 10MB, larger objects with streaming
- S3/MinIO: Large blobs, cloud storage
- GCS: Google Cloud Storage for large blobs

Each backend implements async get/put/delete operations.
"""

import asyncio
import gzip
import hashlib
import json
import os
from abc import ABC, abstractmethod
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
        return key.replace("/", ".").replace(":", ".")

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


class NATSObjectBackend(StorageBackend):
    """NATS JetStream Object Store for larger objects (< 10MB)."""

    def __init__(
        self,
        bucket_name: str = "noetl_result_objects",
        nats_url: Optional[str] = None,
        max_object_size: int = 10 * 1024 * 1024,  # 10MB
    ):
        self._bucket_name = bucket_name
        self._nats_url = nats_url or os.getenv("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
        self._max_object_size = max_object_size
        self._nc = None
        self._js = None
        self._obs = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self):
        """Ensure NATS Object Store connection."""
        if self._obs is not None:
            return

        async with self._lock:
            if self._obs is not None:
                return

            try:
                import nats
                # Use env vars directly to avoid full config validation (workers don't have DB settings)
                nats_user = os.getenv("NATS_USER", "")
                nats_password = os.getenv("NATS_PASSWORD", "")

                connect_kwargs = {
                    "servers": [self._nats_url],
                    "name": "noetl_object_store"
                }
                if nats_user and nats_password:
                    connect_kwargs["user"] = nats_user
                    connect_kwargs["password"] = nats_password

                self._nc = await nats.connect(**connect_kwargs)
                self._js = self._nc.jetstream()

                # Create or get Object Store bucket
                try:
                    self._obs = await self._js.create_object_store(
                        bucket=self._bucket_name,
                        description="NoETL result objects",
                        max_bytes=1024 * 1024 * 1024,  # 1GB total bucket size
                    )
                    logger.info(f"[NATS-OBJ] Created bucket: {self._bucket_name}")
                except Exception:
                    self._obs = await self._js.object_store(self._bucket_name)
                    logger.info(f"[NATS-OBJ] Connected to existing bucket: {self._bucket_name}")

            except Exception as e:
                logger.error(f"[NATS-OBJ] Connection failed: {e}")
                raise

    async def put(self, key: str, data: bytes, metadata: Optional[Dict[str, Any]] = None) -> str:
        await self._ensure_connected()

        if len(data) > self._max_object_size:
            raise ValueError(f"Data too large for NATS Object Store: {len(data)} > {self._max_object_size}")

        # Object store uses names directly
        obj_name = key.replace("/", "_").replace(":", "_")

        await self._obs.put(obj_name, data)
        logger.debug(f"[NATS-OBJ] Stored {obj_name} ({len(data)} bytes)")
        return f"nats-obj://{self._bucket_name}/{obj_name}"

    async def get(self, key: str) -> bytes:
        await self._ensure_connected()

        obj_name = key.replace("/", "_").replace(":", "_")
        try:
            result = await self._obs.get(obj_name)
            return result.data
        except Exception as e:
            if "object not found" in str(e).lower():
                raise KeyError(f"Object not found: {obj_name}")
            raise

    async def delete(self, key: str) -> bool:
        await self._ensure_connected()

        obj_name = key.replace("/", "_").replace(":", "_")
        try:
            await self._obs.delete(obj_name)
            return True
        except Exception as e:
            logger.warning(f"[NATS-OBJ] Delete failed for {obj_name}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        await self._ensure_connected()

        obj_name = key.replace("/", "_").replace(":", "_")
        try:
            info = await self._obs.info(obj_name)
            return info is not None
        except Exception:
            return False


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
        bucket: str = "noetl-results",
        prefix: str = "results/",
        credentials_json: Optional[str] = None,
    ):
        self._bucket_name = bucket
        self._prefix = prefix
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
    backends = {
        "memory": MemoryBackend,
        "kv": NATSKVBackend,
        "object": NATSObjectBackend,
        "s3": S3Backend,
        "gcs": GCSBackend,
    }

    backend_class = backends.get(tier.lower())
    if not backend_class:
        raise ValueError(f"Unknown storage tier: {tier}")

    return backend_class(**kwargs)


__all__ = [
    "StorageBackend",
    "MemoryBackend",
    "NATSKVBackend",
    "NATSObjectBackend",
    "S3Backend",
    "GCSBackend",
    "get_backend",
]
