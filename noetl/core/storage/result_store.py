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
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta, timezone

from noetl.core.storage.models import (
    TempRef,
    Manifest,
    StoreTier,
    Scope,
    TempRefMeta,
)
from noetl.core.storage.router import StorageRouter, default_router
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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
    ):
        """
        Initialize TempStore.

        Args:
            router: Storage router for tier selection (uses default if None)
            default_ttl_seconds: Default TTL for temp data
            inline_max_bytes: Max bytes to store inline
            preview_max_bytes: Max bytes for preview
            nats_client: Optional NATS client (lazy initialized if None)
        """
        self.router = router or default_router
        self.default_ttl_seconds = default_ttl_seconds
        self.inline_max_bytes = inline_max_bytes
        self.preview_max_bytes = preview_max_bytes
        self._nats_client = nats_client

        # In-memory cache for step-scoped refs
        self._memory_cache: Dict[str, bytes] = {}

        # Projection table cache (TempRef metadata)
        self._ref_cache: Dict[str, TempRef] = {}

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

        # Cache ref metadata
        self._ref_cache[temp_ref.ref] = temp_ref

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
            return False

        # Delete from storage backend
        await self._delete_data(temp_ref)

        # Remove from cache
        self._ref_cache.pop(ref_str, None)

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
            return self._ref_cache[ref_str]

        # TODO: Query projection table
        return None

    async def _store_data(self, temp_ref: TempRef, data_bytes: bytes) -> str:
        """Store data in the appropriate backend."""
        store = temp_ref.store

        if store == StoreTier.MEMORY:
            self._memory_cache[temp_ref.ref] = data_bytes
            return f"memory://{temp_ref.ref}"

        elif store == StoreTier.KV:
            nats = await self._get_nats()
            if nats:
                key = temp_ref.to_key()
                bucket = "noetl_temp_refs"
                try:
                    await nats.set_loop_state(
                        execution_id=temp_ref.ref.split("/")[2],
                        step_name=key,
                        state={"data": data_bytes.decode('latin-1')},  # Store as string
                        event_id=key
                    )
                    return f"kv://{bucket}/{key}"
                except Exception as e:
                    logger.warning(f"TEMP: KV store failed, falling back to memory: {e}")
                    self._memory_cache[temp_ref.ref] = data_bytes
                    temp_ref.store = StoreTier.MEMORY
                    return f"memory://{temp_ref.ref}"
            else:
                # Fallback to memory
                self._memory_cache[temp_ref.ref] = data_bytes
                temp_ref.store = StoreTier.MEMORY
                return f"memory://{temp_ref.ref}"

        elif store == StoreTier.OBJECT:
            # TODO: Implement NATS Object Store
            logger.warning("TEMP: Object store not implemented, using memory")
            self._memory_cache[temp_ref.ref] = data_bytes
            temp_ref.store = StoreTier.MEMORY
            return f"memory://{temp_ref.ref}"

        elif store in (StoreTier.S3, StoreTier.GCS):
            # TODO: Implement cloud storage
            logger.warning(f"TEMP: {store.value} not implemented, using memory")
            self._memory_cache[temp_ref.ref] = data_bytes
            temp_ref.store = StoreTier.MEMORY
            return f"memory://{temp_ref.ref}"

        elif store == StoreTier.DB:
            # TODO: Implement PostgreSQL storage
            logger.warning("TEMP: DB store not implemented, using memory")
            self._memory_cache[temp_ref.ref] = data_bytes
            temp_ref.store = StoreTier.MEMORY
            return f"memory://{temp_ref.ref}"

        else:
            # Default to memory
            self._memory_cache[temp_ref.ref] = data_bytes
            return f"memory://{temp_ref.ref}"

    async def _retrieve_data(self, temp_ref: TempRef) -> Any:
        """Retrieve data from storage backend."""
        store = temp_ref.store

        if store == StoreTier.MEMORY:
            data_bytes = self._memory_cache.get(temp_ref.ref)
            if data_bytes is None:
                raise KeyError(f"TempRef not found in memory: {temp_ref.ref}")

        elif store == StoreTier.KV:
            nats = await self._get_nats()
            if nats:
                key = temp_ref.to_key()
                try:
                    state = await nats.get_loop_state(
                        execution_id=temp_ref.ref.split("/")[2],
                        step_name=key,
                        event_id=key
                    )
                    if state and "data" in state:
                        data_bytes = state["data"].encode('latin-1')
                    else:
                        raise KeyError(f"TempRef not found in KV: {temp_ref.ref}")
                except Exception as e:
                    raise KeyError(f"Failed to retrieve from KV: {e}")
            else:
                # Try memory fallback
                data_bytes = self._memory_cache.get(temp_ref.ref)
                if data_bytes is None:
                    raise KeyError(f"TempRef not found: {temp_ref.ref}")

        else:
            # Try memory as fallback for unimplemented stores
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

        if store == StoreTier.MEMORY:
            self._memory_cache.pop(temp_ref.ref, None)

        elif store == StoreTier.KV:
            nats = await self._get_nats()
            if nats:
                key = temp_ref.to_key()
                try:
                    await nats.delete_execution_state(temp_ref.ref.split("/")[2])
                except Exception as e:
                    logger.warning(f"TEMP: Failed to delete from KV: {e}")

        # Also remove from memory cache in case of fallback
        self._memory_cache.pop(temp_ref.ref, None)

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
        """Create truncated preview for UI."""
        if isinstance(data, dict):
            return {k: self._truncate_value(v) for k, v in list(data.items())[:5]}
        elif isinstance(data, list):
            return {"_items": len(data), "_sample": data[:3] if len(data) > 3 else data}
        else:
            return {"_value": str(data)[:100]}

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
