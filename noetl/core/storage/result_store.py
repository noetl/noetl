"""
TempStore service for managing TempRef storage operations.

Provides a unified API for storing and retrieving temp data across
multiple storage backends with automatic tier selection.

Usage:
    store = TempStore()

    # Store data and get TempRef
    ref = await store.put(
        execution_id="123",
        name="api_response",
        data={"users": [...]},
        scope=Scope.EXECUTION
    )

    # Retrieve data by ref
    data = await store.get(ref)

    # Resolve any ref type (TempRef, ResultRef, inline)
    data = await store.resolve(ref_or_data)
"""

import asyncio
import hashlib
import json
import gzip
import os
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from datetime import datetime, timedelta, timezone

from noetl.core.storage.models import (
    TempRef,
    Manifest,
    StoreTier,
    Scope,
    TempRefMeta,
)
from noetl.core.storage.router import StorageRouter, default_router
from noetl.core.storage.extractor import create_preview
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

if TYPE_CHECKING:
    from noetl.core.storage.scope_tracker import ScopeTracker


class TempStore:
    """
    Unified temp storage service.

    Operations:
    - put(name, data, ...) -> TempRef
    - get(ref) -> data
    - resolve(ref) -> data (handles TempRef, ResultRef, inline)
    - delete(ref) -> bool
    - list_refs(execution_id, scope?) -> List[TempRef]
    - cleanup_execution(execution_id)
    """

    def __init__(
        self,
        router: Optional[StorageRouter] = None,
        default_ttl_seconds: int = 3600,  # 1 hour
        inline_max_bytes: int = 65536,    # 64KB
        preview_max_bytes: int = 1024,    # 1KB
        nats_client=None,
        scope_tracker: Optional["ScopeTracker"] = None,
        max_ref_cache_entries: Optional[int] = None,
        max_memory_cache_entries: Optional[int] = None,
    ):
        """
        Initialize TempStore.

        Args:
            router: Storage router for tier selection (uses default if None)
            default_ttl_seconds: Default TTL for temp data
            inline_max_bytes: Max bytes to store inline
            preview_max_bytes: Max bytes for preview
            nats_client: Optional NATS client (lazy initialized if None)
            scope_tracker: Optional ScopeTracker for lifecycle tracking
            max_ref_cache_entries: Max TempRef metadata entries to retain in-memory.
                Values <= 0 are invalid and fall back to defaults.
            max_memory_cache_entries: Max payload entries to retain in-memory.
                Values <= 0 are invalid and fall back to defaults.
        """
        self.router = router or default_router
        self.default_ttl_seconds = default_ttl_seconds
        self.inline_max_bytes = inline_max_bytes
        self.preview_max_bytes = preview_max_bytes
        self._nats_client = nats_client

        # In-memory caches are LRU and size-bounded to avoid unbounded process growth.
        self.max_ref_cache_entries = self._resolve_cache_limit(
            max_ref_cache_entries,
            env_name="NOETL_TEMPSTORE_MAX_REF_CACHE_ENTRIES",
            default=50000,
        )
        self.max_memory_cache_entries = self._resolve_cache_limit(
            max_memory_cache_entries,
            env_name="NOETL_TEMPSTORE_MAX_MEMORY_CACHE_ENTRIES",
            default=20000,
        )

        self._memory_cache: "OrderedDict[str, bytes]" = OrderedDict()
        self._ref_cache: "OrderedDict[str, TempRef]" = OrderedDict()

        if scope_tracker is not None:
            self._scope_tracker = scope_tracker
        else:
            try:
                from noetl.core.storage.scope_tracker import default_tracker
                self._scope_tracker = default_tracker
            except (ImportError, ModuleNotFoundError):
                self._scope_tracker = None

    @staticmethod
    def _resolve_cache_limit(value: Optional[int], env_name: str, default: int) -> int:
        """Resolve positive cache limit from explicit value or environment."""
        if value is not None:
            try:
                limit = int(value)
                if limit <= 0:
                    logger.warning(
                        "TEMP: invalid cache limit %s=%r (must be >0), using default=%s",
                        env_name,
                        value,
                        default,
                    )
                    return default
                return limit
            except (TypeError, ValueError):
                logger.warning(
                    "TEMP: invalid cache limit %s=%r, using default=%s",
                    env_name,
                    value,
                    default,
                )
                return default

        raw_value = os.getenv(env_name)
        if raw_value in (None, ""):
            return default
        try:
            limit = int(raw_value)
            if limit <= 0:
                logger.warning(
                    "TEMP: invalid cache limit %s=%r (must be >0), using default=%s",
                    env_name,
                    raw_value,
                    default,
                )
                return default
            return limit
        except ValueError:
            logger.warning("TEMP: Invalid %s=%r, using default=%s", env_name, raw_value, default)
            return default

    def _untrack_ref(self, ref_str: str) -> None:
        """Best-effort scope tracking cleanup for a removed ref."""
        tracker = getattr(self, "_scope_tracker", None)
        if not tracker:
            return
        try:
            tracker.unregister_ref(ref_str)
        except Exception:
            logger.debug("TEMP: Failed to unregister ref from scope tracker: %s", ref_str)

    def _set_memory_cache(self, ref_str: str, data_bytes: bytes) -> None:
        """Insert payload in LRU memory cache with bounded capacity."""
        self._memory_cache[ref_str] = data_bytes
        self._memory_cache.move_to_end(ref_str)

        while len(self._memory_cache) > self.max_memory_cache_entries:
            evicted_ref, _ = self._memory_cache.popitem(last=False)
            logger.debug("TEMP: Evicted memory cache entry %s due to capacity", evicted_ref)

    def _set_ref_cache(
        self,
        temp_ref: TempRef,
        execution_id: str,
        source_step: Optional[str],
        parent_execution_id: Optional[str],
    ) -> None:
        """Insert TempRef metadata into bounded LRU cache and scope tracker."""
        self._ref_cache[temp_ref.ref] = temp_ref
        self._ref_cache.move_to_end(temp_ref.ref)

        tracker = getattr(self, "_scope_tracker", None)
        if tracker:
            try:
                tracker.register_ref(
                    temp_ref,
                    execution_id=execution_id,
                    step_name=source_step,
                    parent_execution_id=parent_execution_id,
                )
            except ValueError:
                logger.debug(
                    "TEMP: Skipping scope registration for %s (scope=%s, missing step context)",
                    temp_ref.ref,
                    temp_ref.scope.value,
                )
            except Exception:
                logger.debug("TEMP: Failed to register scope for %s", temp_ref.ref)

        while len(self._ref_cache) > self.max_ref_cache_entries:
            evicted_ref, _ = self._ref_cache.popitem(last=False)
            self._memory_cache.pop(evicted_ref, None)
            logger.debug("TEMP: Evicted ref cache entry %s due to capacity", evicted_ref)

    async def _get_nats(self):
        """Get or initialize NATS client."""
        if self._nats_client is None:
            try:
                from noetl.core.cache.nats_kv import get_nats_kv_cache
                self._nats_client = await get_nats_kv_cache()
            except ImportError:
                logger.warning("NATS KV cache not available")
                return None
        return self._nats_client

    async def put(
        self,
        execution_id: str,
        name: str,
        data: Any,
        scope: Scope = Scope.EXECUTION,
        store: Optional[StoreTier] = None,
        ttl_seconds: Optional[int] = None,
        source_step: Optional[str] = None,
        parent_execution_id: Optional[str] = None,
        correlation: Optional[Dict[str, Any]] = None,
        compress: bool = False
    ) -> TempRef:
        """
        Store data and return a TempRef pointer.

        Args:
            execution_id: Execution context
            name: Logical name for the temp
            data: Data to store (any JSON-serializable type)
            scope: Lifecycle scope
            store: Storage tier (auto-selected if None)
            ttl_seconds: TTL override
            source_step: Step that created this temp
            parent_execution_id: Parent execution ID for workflow-scope tracking
            correlation: Loop/pagination tracking
            compress: Whether to compress data

        Returns:
            TempRef pointer to the stored data
        """
        # Serialize data
        serialized = json.dumps(data, default=str)
        data_bytes = serialized.encode('utf-8')
        original_size = len(data_bytes)

        # Compress if requested or data is large
        compression = "none"
        if compress or original_size > 10240:  # Auto-compress > 10KB
            data_bytes = gzip.compress(data_bytes)
            compression = "gzip"
            logger.debug(f"TEMP: Compressed {original_size}b -> {len(data_bytes)}b")

        # Determine storage tier
        if store is None:
            store = self.router.select_tier(
                size_bytes=len(data_bytes),
                scope=scope,
                access_pattern="read_once" if scope == Scope.STEP else "read_multi"
            )

        # Create TempRef
        ttl = ttl_seconds or self.default_ttl_seconds
        meta = TempRefMeta(
            bytes=len(data_bytes),
            sha256=hashlib.sha256(data_bytes).hexdigest(),
            compression=compression
        )

        temp_ref = TempRef.create(
            execution_id=execution_id,
            name=name,
            store=store,
            scope=scope,
            ttl_seconds=ttl,
            meta=meta,
            correlation=correlation
        )

        # Create preview
        preview = self._create_preview(data)
        temp_ref.preview = preview

        # Store data in appropriate backend
        await self._store_data(temp_ref, data_bytes)

        # Cache ref metadata + register scope tracking consistently for all callers.
        self._set_ref_cache(
            temp_ref=temp_ref,
            execution_id=execution_id,
            source_step=source_step,
            parent_execution_id=parent_execution_id,
        )

        logger.info(
            f"TEMP: Stored {name} -> {temp_ref.ref} "
            f"(store={store.value}, bytes={meta.bytes}, scope={scope.value})"
        )
        return temp_ref

    async def get(self, ref: Union[str, TempRef]) -> Any:
        """
        Retrieve data by TempRef.

        Args:
            ref: TempRef or ref string

        Returns:
            Deserialized data

        Raises:
            KeyError: If ref not found or expired
        """
        ref_str = ref if isinstance(ref, str) else ref.ref
        temp_ref = await self._lookup_ref(ref_str)

        if not temp_ref:
            # Ref not in local cache - try direct fetch from storage
            # This is needed for distributed workers that don't share cache
            data = await self._fetch_direct(ref_str)
            if data is not None:
                return data
            raise KeyError(f"TempRef not found: {ref_str}")

        # Check expiration
        if temp_ref.is_expired():
            await self.delete(ref_str)
            raise KeyError(f"TempRef expired: {ref_str}")

        # Retrieve data
        data = await self._retrieve_data(temp_ref)

        # Update access tracking
        temp_ref.meta.access_count += 1
        temp_ref.meta.accessed_at = datetime.now(timezone.utc)

        logger.debug(f"TEMP: Retrieved {ref_str} (access_count={temp_ref.meta.access_count})")
        return data

    async def resolve(self, ref: Union[str, TempRef, Dict, Any]) -> Any:
        """
        Resolve any ref type to actual data.

        Handles TempRef, ResultRef, and inline data transparently.

        Args:
            ref: TempRef, ResultRef dict, ref string, or inline data

        Returns:
            Resolved data
        """
        if ref is None:
            return None

        # Dict with kind field
        if isinstance(ref, dict):
            kind = ref.get("kind")
            if kind == "temp_ref":
                return await self.get(ref.get("ref"))
            elif kind == "result_ref":
                return await self._resolve_result_ref(ref)
            elif kind == "manifest":
                return await self._resolve_manifest(ref)
            else:
                # Inline data
                return ref

        # TempRef object
        elif isinstance(ref, TempRef):
            return await self.get(ref.ref)

        # Manifest object
        elif isinstance(ref, Manifest):
            return await self._resolve_manifest(ref.model_dump())

        # String URI
        elif isinstance(ref, str):
            if ref.startswith("noetl://"):
                return await self.get(ref)
            else:
                # Plain string value
                return ref

        # Pass through other types
        else:
            return ref

    async def delete(self, ref: Union[str, TempRef]) -> bool:
        """Delete a TempRef and its data."""
        ref_str = ref if isinstance(ref, str) else ref.ref
        temp_ref = await self._lookup_ref(ref_str)

        if not temp_ref:
            # Metadata may have been evicted from cache while external payload still exists.
            deleted = await self._delete_data_by_ref(ref_str)
            if deleted:
                self._ref_cache.pop(ref_str, None)
                self._memory_cache.pop(ref_str, None)
                self._untrack_ref(ref_str)
            return deleted

        # Delete from storage backend
        await self._delete_data(temp_ref)

        # Remove from cache
        self._ref_cache.pop(ref_str, None)
        self._untrack_ref(ref_str)

        logger.debug(f"TEMP: Deleted {ref_str}")
        return True

    async def list_refs(
        self,
        execution_id: str,
        scope: Optional[Scope] = None,
        source_step: Optional[str] = None
    ) -> List[TempRef]:
        """
        List TempRefs for an execution.

        Args:
            execution_id: Execution ID
            scope: Filter by scope
            source_step: Filter by source step

        Returns:
            List of TempRefs
        """
        # For now, use in-memory cache
        # TODO: Query projection table when implemented
        refs = []
        prefix = f"noetl://execution/{execution_id}/"

        for ref_str, temp_ref in self._ref_cache.items():
            if not ref_str.startswith(prefix):
                continue
            if scope and temp_ref.scope != scope:
                continue
            refs.append(temp_ref)

        return refs

    async def cleanup_execution(self, execution_id: str, scope: Scope = Scope.EXECUTION) -> int:
        """
        Clean up all temps for an execution.

        Called when playbook completes.

        Args:
            execution_id: Execution ID
            scope: Scope to clean up

        Returns:
            Number of refs deleted
        """
        refs = await self.list_refs(execution_id, scope=scope)

        deleted = 0
        for ref in refs:
            try:
                if await self.delete(ref):
                    deleted += 1
            except Exception as e:
                logger.warning(f"TEMP: Failed to delete {ref.ref}: {e}")

        logger.info(f"TEMP: Cleaned up {deleted} refs for execution {execution_id}")
        return deleted

    # === Internal methods ===

    async def _lookup_ref(self, ref_str: str) -> Optional[TempRef]:
        """Look up TempRef metadata."""
        # Check cache first
        if ref_str in self._ref_cache:
            self._ref_cache.move_to_end(ref_str)
            return self._ref_cache[ref_str]

        # TODO: Query projection table
        return None

    async def _fetch_direct(self, ref_str: str) -> Optional[Any]:
        """
        Fetch data directly from storage without cached metadata.

        This is used when a worker doesn't have the TempRef cached
        (e.g., artifact.get on a different worker than the one that stored the data).

        Tries storage tiers in order: KV -> Object -> Memory (local)
        """
        if not ref_str.startswith("noetl://"):
            return None

        # Convert ref URI to storage key
        # noetl://execution/{exec_id}/result/{step}/{id} -> execution_{exec_id}_result_{step}_{id}
        # Must match TempRef.to_key() which uses underscores
        key = ref_str.replace("noetl://", "").replace("/", "_")

        logger.debug(f"TEMP: Direct fetch attempt for key: {key}")

        # Try NATS KV first (default tier)
        try:
            from noetl.core.storage.backends import NATSKVBackend
            if not hasattr(self, '_kv_backend'):
                self._kv_backend = NATSKVBackend()
            data_bytes = await self._kv_backend.get(key)

            # Decompress if gzipped
            if data_bytes and len(data_bytes) >= 2 and data_bytes[:2] == b'\x1f\x8b':
                data_bytes = gzip.decompress(data_bytes)

            logger.debug(f"TEMP: Direct fetch from KV successful: {ref_str}")
            return json.loads(data_bytes.decode('utf-8'))
        except KeyError:
            logger.debug(f"TEMP: Key not found in KV: {key}")
        except Exception as e:
            logger.debug(f"TEMP: KV fetch failed: {e}")

        # Try NATS Object Store
        try:
            from noetl.core.storage.backends import NATSObjectBackend
            if not hasattr(self, '_object_backend'):
                self._object_backend = NATSObjectBackend()
            data_bytes = await self._object_backend.get(key)

            # Decompress if gzipped
            if data_bytes and len(data_bytes) >= 2 and data_bytes[:2] == b'\x1f\x8b':
                data_bytes = gzip.decompress(data_bytes)

            logger.debug(f"TEMP: Direct fetch from Object Store successful: {ref_str}")
            return json.loads(data_bytes.decode('utf-8'))
        except KeyError:
            logger.debug(f"TEMP: Object not found: {key}")
        except Exception as e:
            logger.debug(f"TEMP: Object Store fetch failed: {e}")

        # Try GCS if configured
        import os
        if os.getenv("NOETL_GCS_BUCKET"):
            try:
                from noetl.core.storage.backends import GCSBackend
                if not hasattr(self, '_gcs_backend'):
                    self._gcs_backend = GCSBackend()
                data_bytes = await self._gcs_backend.get(key)

                # Decompress if gzipped
                if data_bytes and len(data_bytes) >= 2 and data_bytes[:2] == b'\x1f\x8b':
                    data_bytes = gzip.decompress(data_bytes)

                logger.debug(f"TEMP: Direct fetch from GCS successful: {ref_str}")
                return json.loads(data_bytes.decode('utf-8'))
            except KeyError:
                logger.debug(f"TEMP: GCS object not found: {key}")
            except Exception as e:
                logger.debug(f"TEMP: GCS fetch failed: {e}")

        # Try local memory as last resort
        if ref_str in self._memory_cache:
            self._memory_cache.move_to_end(ref_str)
            data_bytes = self._memory_cache[ref_str]
            if data_bytes[:2] == b'\x1f\x8b':
                data_bytes = gzip.decompress(data_bytes)
            return json.loads(data_bytes.decode('utf-8'))

        return None

    async def _store_data(self, temp_ref: TempRef, data_bytes: bytes) -> str:
        """Store data in the appropriate backend."""
        store = temp_ref.store
        key = temp_ref.to_key()

        if store == StoreTier.MEMORY:
            self._set_memory_cache(temp_ref.ref, data_bytes)
            return f"memory://{temp_ref.ref}"

        elif store == StoreTier.KV:
            try:
                from noetl.core.storage.backends import NATSKVBackend
                if not hasattr(self, '_kv_backend'):
                    self._kv_backend = NATSKVBackend()
                uri = await self._kv_backend.put(key, data_bytes)
                return uri
            except Exception as e:
                logger.warning(f"TEMP: KV store failed, falling back to memory: {e}")
                self._set_memory_cache(temp_ref.ref, data_bytes)
                temp_ref.store = StoreTier.MEMORY
                return f"memory://{temp_ref.ref}"

        elif store == StoreTier.OBJECT:
            try:
                from noetl.core.storage.backends import NATSObjectBackend
                if not hasattr(self, '_object_backend'):
                    self._object_backend = NATSObjectBackend()
                uri = await self._object_backend.put(key, data_bytes)
                return uri
            except Exception as e:
                logger.warning(f"TEMP: Object store failed, falling back to KV: {e}")
                # Fallback to KV
                return await self._store_data_fallback(temp_ref, data_bytes, StoreTier.KV)

        elif store == StoreTier.S3:
            try:
                from noetl.core.storage.backends import S3Backend
                if not hasattr(self, '_s3_backend'):
                    self._s3_backend = S3Backend()
                uri = await self._s3_backend.put(key, data_bytes)
                return uri
            except Exception as e:
                logger.warning(f"TEMP: S3 store failed, falling back to Object: {e}")
                return await self._store_data_fallback(temp_ref, data_bytes, StoreTier.OBJECT)

        elif store == StoreTier.GCS:
            try:
                from noetl.core.storage.backends import GCSBackend
                if not hasattr(self, '_gcs_backend'):
                    self._gcs_backend = GCSBackend()
                uri = await self._gcs_backend.put(key, data_bytes)
                return uri
            except Exception as e:
                logger.warning(f"TEMP: GCS store failed, falling back to Object: {e}")
                return await self._store_data_fallback(temp_ref, data_bytes, StoreTier.OBJECT)

        elif store == StoreTier.DB:
            # DB storage not implemented yet, use NATS KV
            logger.warning("TEMP: DB store not implemented, using KV")
            return await self._store_data_fallback(temp_ref, data_bytes, StoreTier.KV)

        else:
            # Default to memory
            self._set_memory_cache(temp_ref.ref, data_bytes)
            return f"memory://{temp_ref.ref}"

    async def _store_data_fallback(self, temp_ref: TempRef, data_bytes: bytes, fallback_tier: StoreTier) -> str:
        """Store data using a fallback tier."""
        temp_ref.store = fallback_tier
        return await self._store_data(temp_ref, data_bytes)

    async def _retrieve_data(self, temp_ref: TempRef) -> Any:
        """Retrieve data from storage backend."""
        store = temp_ref.store
        key = temp_ref.to_key()

        if store == StoreTier.MEMORY:
            data_bytes = self._memory_cache.get(temp_ref.ref)
            if data_bytes is None:
                raise KeyError(f"TempRef not found in memory: {temp_ref.ref}")
            self._memory_cache.move_to_end(temp_ref.ref)

        elif store == StoreTier.KV:
            try:
                from noetl.core.storage.backends import NATSKVBackend
                if not hasattr(self, '_kv_backend'):
                    self._kv_backend = NATSKVBackend()
                data_bytes = await self._kv_backend.get(key)
            except KeyError:
                raise
            except Exception as e:
                raise KeyError(f"Failed to retrieve from KV: {e}")

        elif store == StoreTier.OBJECT:
            try:
                from noetl.core.storage.backends import NATSObjectBackend
                if not hasattr(self, '_object_backend'):
                    self._object_backend = NATSObjectBackend()
                data_bytes = await self._object_backend.get(key)
            except KeyError:
                raise
            except Exception as e:
                raise KeyError(f"Failed to retrieve from Object Store: {e}")

        elif store == StoreTier.S3:
            try:
                from noetl.core.storage.backends import S3Backend
                if not hasattr(self, '_s3_backend'):
                    self._s3_backend = S3Backend()
                data_bytes = await self._s3_backend.get(key)
            except KeyError:
                raise
            except Exception as e:
                raise KeyError(f"Failed to retrieve from S3: {e}")

        elif store == StoreTier.GCS:
            try:
                from noetl.core.storage.backends import GCSBackend
                if not hasattr(self, '_gcs_backend'):
                    self._gcs_backend = GCSBackend()
                data_bytes = await self._gcs_backend.get(key)
            except KeyError:
                raise
            except Exception as e:
                raise KeyError(f"Failed to retrieve from GCS: {e}")

        else:
            # Try memory as fallback for other stores
            data_bytes = self._memory_cache.get(temp_ref.ref)
            if data_bytes is None:
                raise KeyError(f"TempRef not found: {temp_ref.ref}")

        # Decompress if needed
        if temp_ref.meta.compression == "gzip":
            data_bytes = gzip.decompress(data_bytes)

        return json.loads(data_bytes.decode('utf-8'))

    async def _delete_data(self, temp_ref: TempRef):
        """Delete data from storage backend."""
        store = temp_ref.store
        key = temp_ref.to_key()

        if store == StoreTier.MEMORY:
            self._memory_cache.pop(temp_ref.ref, None)

        elif store == StoreTier.KV:
            try:
                from noetl.core.storage.backends import NATSKVBackend
                if not hasattr(self, '_kv_backend'):
                    self._kv_backend = NATSKVBackend()
                await self._kv_backend.delete(key)
            except Exception as e:
                logger.warning(f"TEMP: Failed to delete from KV: {e}")

        elif store == StoreTier.OBJECT:
            try:
                from noetl.core.storage.backends import NATSObjectBackend
                if not hasattr(self, '_object_backend'):
                    self._object_backend = NATSObjectBackend()
                await self._object_backend.delete(key)
            except Exception as e:
                logger.warning(f"TEMP: Failed to delete from Object Store: {e}")

        elif store == StoreTier.S3:
            try:
                from noetl.core.storage.backends import S3Backend
                if not hasattr(self, '_s3_backend'):
                    self._s3_backend = S3Backend()
                await self._s3_backend.delete(key)
            except Exception as e:
                logger.warning(f"TEMP: Failed to delete from S3: {e}")

        elif store == StoreTier.GCS:
            try:
                from noetl.core.storage.backends import GCSBackend
                if not hasattr(self, '_gcs_backend'):
                    self._gcs_backend = GCSBackend()
                await self._gcs_backend.delete(key)
            except Exception as e:
                logger.warning(f"TEMP: Failed to delete from GCS: {e}")

        # Also remove from memory cache in case of fallback
        self._memory_cache.pop(temp_ref.ref, None)

    async def _delete_data_by_ref(self, ref_str: str) -> bool:
        """
        Best-effort delete by URI when TempRef metadata is unavailable.

        This preserves cleanup behavior for refs evicted from _ref_cache.
        """
        self._memory_cache.pop(ref_str, None)
        if not ref_str.startswith("noetl://"):
            return False

        key = ref_str.replace("noetl://", "").replace("/", "_")
        deleted = False

        try:
            from noetl.core.storage.backends import NATSKVBackend
            if not hasattr(self, '_kv_backend'):
                self._kv_backend = NATSKVBackend()
            deleted = await self._kv_backend.delete(key) or deleted
        except Exception:
            pass

        try:
            from noetl.core.storage.backends import NATSObjectBackend
            if not hasattr(self, '_object_backend'):
                self._object_backend = NATSObjectBackend()
            deleted = await self._object_backend.delete(key) or deleted
        except Exception:
            pass

        try:
            from noetl.core.storage.backends import S3Backend
            if not hasattr(self, '_s3_backend'):
                self._s3_backend = S3Backend()
            deleted = await self._s3_backend.delete(key) or deleted
        except Exception:
            pass

        try:
            from noetl.core.storage.backends import GCSBackend
            if not hasattr(self, '_gcs_backend'):
                self._gcs_backend = GCSBackend()
            deleted = await self._gcs_backend.delete(key) or deleted
        except Exception:
            pass

        return deleted

    async def _resolve_result_ref(self, ref: Dict[str, Any]) -> Any:
        """Resolve a ResultRef to its data."""
        # ResultRef may have inline preview or external storage
        if "preview" in ref and ref.get("store") == "eventlog":
            return ref["preview"]

        # TODO: Implement artifact resolution
        artifact = ref.get("artifact")
        if artifact:
            uri = artifact.get("uri", "")
            if uri.startswith("s3://") or uri.startswith("gs://"):
                logger.warning(f"TEMP: Cloud artifact resolution not implemented: {uri}")
                return ref.get("preview", {})

        return ref.get("preview", ref)

    async def _resolve_manifest(self, manifest: Dict[str, Any]) -> List[Any]:
        """Resolve a Manifest to its combined data."""
        parts = manifest.get("parts", [])
        strategy = manifest.get("strategy", "append")
        merge_path = manifest.get("merge_path")

        results = []
        for part in parts:
            part_ref = part.get("ref")
            if part_ref:
                try:
                    data = await self.resolve(part_ref)
                    results.append(data)
                except Exception as e:
                    logger.warning(f"TEMP: Failed to resolve manifest part: {e}")

        # Combine based on strategy
        if strategy == "append":
            return results
        elif strategy == "concat" and merge_path:
            # Extract and concatenate arrays at merge_path
            combined = []
            for result in results:
                if isinstance(result, dict):
                    # Simple path extraction (e.g., "data" or "data.items")
                    value = result
                    for key in merge_path.lstrip("$.").split("."):
                        value = value.get(key, []) if isinstance(value, dict) else []
                    if isinstance(value, list):
                        combined.extend(value)
                elif isinstance(result, list):
                    combined.extend(result)
            return combined
        else:
            return results

    def _create_preview(self, data: Any) -> Dict[str, Any]:
        """Create a byte-capped preview for UI and event payloads."""
        return create_preview(data, max_bytes=self.preview_max_bytes)

    def _truncate_value(self, value: Any, max_len: int = 100) -> Any:
        """Truncate a value for preview."""
        if isinstance(value, str) and len(value) > max_len:
            return value[:max_len] + "..."
        elif isinstance(value, list) and len(value) > 3:
            return f"[{len(value)} items]"
        elif isinstance(value, dict) and len(value) > 3:
            return f"{{{len(value)} keys}}"
        return value


# Default store instance
default_store = TempStore()


__all__ = [
    "TempStore",
    "default_store",
]
