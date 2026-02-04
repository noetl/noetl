"""
NoETL Result Storage System.

Zero-copy, borrow-like architecture for efficient data passing between playbook steps.
Data is stored externally and only lightweight pointers (ResultRef) are passed
through the event log and context.

Storage Tiers:
- memory: In-process (<10KB, step-scoped)
- kv: NATS KV (<1MB, execution-scoped)
- object: NATS Object Store (<10MB)
- s3/gcs: Cloud storage (large blobs)
- db: PostgreSQL (queryable intermediate data)

Scopes:
- step: Cleaned when step completes
- execution: Cleaned when playbook completes
- workflow: Persists across nested playbook calls
- forever: Never auto-cleaned (permanent storage)

Key Components:
- ResultRef: MCP-compatible result reference pointer
- Manifest: Aggregated results for pagination/loops
- StorageRouter: Automatic tier selection
- ResultStore: Unified storage service (put/get/resolve)
- ScopeTracker: Lifecycle management
- GarbageCollector: TTL-based and execution-finalizer cleanup
"""

from noetl.core.storage.models import (
    StoreTier,
    Scope,
    ResultRefMeta,
    ResultRef,
    ManifestPart,
    Manifest,
    AnyRef,
    # Legacy aliases
    TempRefMeta,
    TempRef,
)

from noetl.core.storage.router import (
    StorageRouter,
    default_router,
)

from noetl.core.storage.result_store import (
    TempStore,
    default_store,
)

from noetl.core.storage.scope_tracker import (
    ScopeContext,
    ScopeTracker,
    default_tracker,
)

from noetl.core.storage.gc import (
    TempGarbageCollector,
    default_gc,
)

from noetl.core.storage.backends import (
    StorageBackend,
    MemoryBackend,
    NATSKVBackend,
    NATSObjectBackend,
    S3Backend,
    GCSBackend,
    get_backend,
)

from noetl.core.storage.extractor import (
    extract_output_select,
    estimate_size,
    should_externalize,
    create_preview,
    DEFAULT_EXTRACT_FIELDS,
)

# Aliases for new naming
ResultStore = TempStore
default_result_store = default_store
ResultGarbageCollector = TempGarbageCollector

__all__ = [
    # Models
    'StoreTier',
    'Scope',
    'ResultRefMeta',
    'ResultRef',
    'ManifestPart',
    'Manifest',
    'AnyRef',
    # Legacy model aliases
    'TempRefMeta',
    'TempRef',
    # Router
    'StorageRouter',
    'default_router',
    # Store (both names)
    'TempStore',
    'ResultStore',
    'default_store',
    'default_result_store',
    # Scope Tracker
    'ScopeContext',
    'ScopeTracker',
    'default_tracker',
    # Garbage Collector
    'TempGarbageCollector',
    'ResultGarbageCollector',
    'default_gc',
    # Backends
    'StorageBackend',
    'MemoryBackend',
    'NATSKVBackend',
    'NATSObjectBackend',
    'S3Backend',
    'GCSBackend',
    'get_backend',
    # Extractor
    'extract_output_select',
    'estimate_size',
    'should_externalize',
    'create_preview',
    'DEFAULT_EXTRACT_FIELDS',
]
