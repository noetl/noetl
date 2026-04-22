"""
Storage tier router for automatic backend selection.

Selects optimal storage tier based on:
- Data size
- Access patterns
- Scope/lifecycle
- Content type

Phase 0 (RisingWave alignment): removed the `OBJECT` (NATS Object
Store) tier. Payloads >= 1 MB now route to `DISK` (local SSD cache
with async cloud spill). The `DISK` backend is a phase-0 placeholder;
TempStore falls back to the configured cloud tier (S3/MinIO or GCS)
via `default_cloud_tier` until phase 1 lands the real implementation.
See `docs/features/noetl_storage_and_streaming_alignment.md`.
"""

import os
from typing import Optional, Dict, Any

from noetl.core.storage.models import StoreTier, Scope
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def _resolve_default_cloud_tier() -> StoreTier:
    """
    Resolve default cloud tier from env var.

    `NOETL_STORAGE_CLOUD_TIER=s3|gcs` picks the durable backend. MinIO
    is S3 with a custom endpoint (`NOETL_S3_ENDPOINT`); it is not a
    separate tier value.
    """
    raw = (os.getenv("NOETL_STORAGE_CLOUD_TIER") or "s3").strip().lower()
    if raw == "gcs":
        return StoreTier.GCS
    # Default and explicit `s3` both resolve here. MinIO lives under S3.
    return StoreTier.S3


class StorageRouter:
    """
    Automatic storage tier selection.

    Tier thresholds (post-phase-0, RisingWave-aligned):
    - memory: < 10KB, step scope only (in-process)
    - kv: < 1MB, execution scope (NATS KV)
    - disk: >= 1MB (local SSD cache + async cloud spill)
    - s3/gcs: explicit durable, any size
    - db: queryable data

    Usage:
        router = StorageRouter()
        tier = router.select_tier(size_bytes=500_000, scope=Scope.EXECUTION)
        # Returns StoreTier.KV
    """

    # Size thresholds in bytes
    MEMORY_MAX = 10 * 1024           # 10KB
    KV_MAX = 1 * 1024 * 1024         # 1MB

    def __init__(
        self,
        default_cloud_tier: Optional[StoreTier] = None,
        prefer_kv_for_small: bool = True,
        memory_max: int = None,
        kv_max: int = None,
    ):
        """
        Initialize the storage router.

        Args:
            default_cloud_tier: Durable backend for disk-cache async spill and
                for `>= 1 MB` writes until the disk cache ships. Defaults to the
                value of `NOETL_STORAGE_CLOUD_TIER` (`s3` or `gcs`).
            prefer_kv_for_small: Use KV for small data even if memory is available
            memory_max: Override memory tier max size
            kv_max: Override KV tier max size
        """
        self.default_cloud_tier = default_cloud_tier or _resolve_default_cloud_tier()
        self.prefer_kv_for_small = prefer_kv_for_small
        self.memory_max = memory_max or self.MEMORY_MAX
        self.kv_max = kv_max or self.KV_MAX

    def select_tier(
        self,
        size_bytes: int,
        scope: Scope = Scope.EXECUTION,
        access_pattern: str = "read_once",
        content_type: str = "application/json",
        force_tier: Optional[StoreTier] = None
    ) -> StoreTier:
        """
        Select optimal storage tier.

        Args:
            size_bytes: Data size in bytes
            scope: Lifecycle scope (step, execution, workflow)
            access_pattern: How data will be accessed:
                - "read_once": Single read after write
                - "read_multi": Multiple reads during execution
                - "query": SQL-like queries needed
            content_type: MIME type of the data
            force_tier: Override automatic selection

        Returns:
            Selected StoreTier
        """
        if force_tier:
            logger.debug(f"ROUTER: Forced tier {force_tier.value}")
            return force_tier

        # Query pattern always goes to DB
        if access_pattern == "query":
            logger.debug("ROUTER: Query pattern -> DB")
            return StoreTier.DB

        # Step-scoped small data -> memory (if not preferring KV)
        if scope == Scope.STEP and size_bytes <= self.memory_max and not self.prefer_kv_for_small:
            logger.debug(f"ROUTER: Step-scoped small ({size_bytes}b) -> MEMORY")
            return StoreTier.MEMORY

        # Small data -> KV
        if size_bytes <= self.kv_max:
            logger.debug(f"ROUTER: Small data ({size_bytes}b) -> KV")
            return StoreTier.KV

        # Everything else -> DISK (local cache + async cloud spill).
        # The actual disk-cache backend ships in phase 1; in phase 0 TempStore
        # transparently serves disk-tier writes from the configured cloud tier.
        logger.debug(f"ROUTER: Large data ({size_bytes}b) -> DISK (cloud={self.default_cloud_tier.value})")
        return StoreTier.DISK

    def select_tier_for_output(
        self,
        estimated_bytes: int,
        output_config: Dict[str, Any],
        scope: Scope = Scope.EXECUTION
    ) -> StoreTier:
        """
        Select tier based on step output configuration.

        Args:
            estimated_bytes: Estimated data size
            output_config: Step output block configuration
            scope: Default scope if not specified in config

        Returns:
            StoreTier
        """
        store = output_config.get("store", {})

        # Explicit tier from config
        if "kind" in store:
            kind = (store["kind"] or "").lower()
            if kind == "auto":
                pass  # Fall through to auto-selection
            elif kind == "memory":
                return StoreTier.MEMORY
            elif kind == "kv":
                return StoreTier.KV
            elif kind == "disk":
                return StoreTier.DISK
            elif kind == "object":
                # Back-compat: old playbooks still use 'object'. One warn
                # per process is emitted by models._normalize_store_value.
                from noetl.core.storage.models import _normalize_store_value
                _normalize_store_value("object")
                return StoreTier.DISK
            elif kind == "s3":
                return StoreTier.S3
            elif kind == "gcs":
                return StoreTier.GCS
            elif kind == "db":
                return StoreTier.DB
            elif kind == "duckdb":
                return StoreTier.DUCKDB

        # Check for query access pattern
        access_pattern = "read_once"
        if store.get("queryable", False):
            access_pattern = "query"

        # Auto-select based on size
        return self.select_tier(
            size_bytes=estimated_bytes,
            scope=scope,
            access_pattern=access_pattern
        )

    def get_tier_config(self, tier: StoreTier) -> Dict[str, Any]:
        """
        Get default configuration for a storage tier.

        Args:
            tier: Storage tier

        Returns:
            Configuration dict with bucket names, TTL, etc.
        """
        configs = {
            StoreTier.MEMORY: {
                "max_size": self.memory_max,
                "ttl_seconds": 300,  # 5 min default
            },
            StoreTier.KV: {
                "bucket": "noetl_temp_refs",
                "max_size": self.kv_max,
                "ttl_seconds": 3600,  # 1 hour
                "history": 1,
            },
            StoreTier.DISK: {
                # Reserved for phase 1. See
                # docs/features/noetl_storage_and_streaming_alignment.md
                "cache_dir": os.getenv(
                    "NOETL_STORAGE_LOCAL_CACHE_DIR", "/opt/noetl/data/disk_cache"
                ),
                "data_capacity_mb": int(
                    os.getenv("NOETL_STORAGE_LOCAL_DATA_CACHE_CAPACITY_MB", "0") or 0
                ),
                "meta_capacity_mb": int(
                    os.getenv("NOETL_STORAGE_LOCAL_META_CACHE_CAPACITY_MB", "0") or 0
                ),
                "insert_rate_limit_mb": int(
                    os.getenv("NOETL_STORAGE_LOCAL_CACHE_INSERT_RATE_MB", "0") or 0
                ),
                "recover_mode": os.getenv(
                    "NOETL_STORAGE_LOCAL_CACHE_RECOVER_MODE", "None"
                ),
                "ttl_seconds": 1800,  # 30 min hot band
            },
            StoreTier.S3: {
                "bucket": "noetl-temp",
                "prefix": "temp/",
                "ttl_seconds": 7200,  # 2 hours
            },
            StoreTier.GCS: {
                "bucket": "noetl-temp",
                "prefix": "temp/",
                "ttl_seconds": 7200,  # 2 hours
            },
            StoreTier.DB: {
                "schema": "noetl",
                "table_prefix": "temp_",
                "ttl_seconds": 7200,  # 2 hours
            },
            StoreTier.DUCKDB: {
                "path": ":memory:",
                "ttl_seconds": 3600,  # 1 hour
            },
            StoreTier.EVENTLOG: {
                "max_size": 65536,  # 64KB inline limit
                "ttl_seconds": None,  # Permanent in event log
            },
        }
        return configs.get(tier, {})


# Default router instance (resolves cloud tier from env at import time)
default_router = StorageRouter()


__all__ = [
    "StorageRouter",
    "default_router",
]
