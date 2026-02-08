"""
Storage tier router for automatic backend selection.

Selects optimal storage tier based on:
- Data size
- Access patterns
- Scope/lifecycle
- Content type
"""

from typing import Optional, Dict, Any
from noetl.core.storage.models import StoreTier, Scope
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class StorageRouter:
    """
    Automatic storage tier selection.

    Tier thresholds:
    - memory: < 10KB, step scope only
    - kv: < 1MB, execution scope
    - object: < 10MB, any scope
    - s3/gcs: > 10MB or explicit
    - db: queryable data

    Usage:
        router = StorageRouter()
        tier = router.select_tier(size_bytes=500_000, scope=Scope.EXECUTION)
        # Returns StoreTier.KV
    """

    # Size thresholds in bytes
    MEMORY_MAX = 10 * 1024           # 10KB
    KV_MAX = 1 * 1024 * 1024         # 1MB
    OBJECT_MAX = 10 * 1024 * 1024    # 10MB

    def __init__(
        self,
        default_cloud_tier: StoreTier = StoreTier.S3,
        prefer_kv_for_small: bool = True,
        memory_max: int = None,
        kv_max: int = None,
        object_max: int = None,
    ):
        """
        Initialize the storage router.

        Args:
            default_cloud_tier: Tier to use for large blobs (S3 or GCS)
            prefer_kv_for_small: Use KV for small data even if memory is available
            memory_max: Override memory tier max size
            kv_max: Override KV tier max size
            object_max: Override object store tier max size
        """
        self.default_cloud_tier = default_cloud_tier
        self.prefer_kv_for_small = prefer_kv_for_small
        self.memory_max = memory_max or self.MEMORY_MAX
        self.kv_max = kv_max or self.KV_MAX
        self.object_max = object_max or self.OBJECT_MAX

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
            logger.debug(f"ROUTER: Query pattern -> DB")
            return StoreTier.DB

        # Step-scoped small data -> memory (if not preferring KV)
        if scope == Scope.STEP and size_bytes <= self.memory_max and not self.prefer_kv_for_small:
            logger.debug(f"ROUTER: Step-scoped small ({size_bytes}b) -> MEMORY")
            return StoreTier.MEMORY

        # Small data -> KV
        if size_bytes <= self.kv_max:
            logger.debug(f"ROUTER: Small data ({size_bytes}b) -> KV")
            return StoreTier.KV

        # Medium data -> Object store
        if size_bytes <= self.object_max:
            logger.debug(f"ROUTER: Medium data ({size_bytes}b) -> OBJECT")
            return StoreTier.OBJECT

        # Large data -> Cloud storage
        logger.debug(f"ROUTER: Large data ({size_bytes}b) -> {self.default_cloud_tier.value}")
        return self.default_cloud_tier

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
            kind = store["kind"]
            if kind == "auto":
                pass  # Fall through to auto-selection
            elif kind == "memory":
                return StoreTier.MEMORY
            elif kind == "kv":
                return StoreTier.KV
            elif kind == "object":
                return StoreTier.OBJECT
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
            StoreTier.OBJECT: {
                "bucket": "noetl_temp_objects",
                "max_size": self.object_max,
                "ttl_seconds": 1800,  # 30 min
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


# Default router instance
default_router = StorageRouter()


__all__ = [
    "StorageRouter",
    "default_router",
]
