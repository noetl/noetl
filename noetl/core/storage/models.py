"""
Result/Reference storage models for NoETL.

MCP-compatible pointer system for efficient data passing between steps.
Data is stored externally and only lightweight pointers are passed through
the event log and context.

Storage Tiers:
- memory: In-process (<10KB, step-scoped)
- kv: NATS KV (<1MB, execution-scoped)
- object: NATS Object Store (<10MB)
- s3/gcs: Cloud storage (large blobs)
- db: PostgreSQL (queryable intermediate data)

Scopes:
- step: Cleaned up when step completes
- execution: Cleaned up when playbook completes
- workflow: Persists across nested playbook calls
- forever: Never auto-cleaned (permanent storage)
"""

from typing import Optional, Dict, Any, List, Literal, Union
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field, field_validator
from enum import Enum
import uuid


class StoreTier(str, Enum):
    """Storage tier for result data."""
    MEMORY = "memory"       # In-process memory (fastest, step-scoped)
    KV = "kv"              # NATS KV (< 1MB, execution-scoped)
    OBJECT = "object"      # NATS Object Store (< 10MB)
    S3 = "s3"              # S3/MinIO (large blobs)
    GCS = "gcs"            # Google Cloud Storage
    DB = "db"              # PostgreSQL (queryable)
    DUCKDB = "duckdb"      # DuckDB (local analytics)
    EVENTLOG = "eventlog"  # Event log inline (default for small results)


class Scope(str, Enum):
    """Lifecycle scope for result data."""
    STEP = "step"           # Cleaned up when step completes
    EXECUTION = "execution" # Cleaned up when playbook completes
    WORKFLOW = "workflow"   # Persists across nested playbook calls
    PERMANENT = "permanent" # Never auto-cleaned (permanent storage)


class ResultRefMeta(BaseModel):
    """Metadata for ResultRef."""
    content_type: str = Field(default="application/json")
    bytes: int = Field(default=0, description="Size in bytes")
    sha256: Optional[str] = Field(default=None, description="Content hash")
    compression: str = Field(default="none", description="Compression: gzip, lz4, none")
    encoding: str = Field(default="utf-8")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    accessed_at: Optional[datetime] = Field(default=None)
    access_count: int = Field(default=0)


# Legacy alias
TempRefMeta = ResultRefMeta


class ResultRef(BaseModel):
    """
    MCP-compatible result reference pointer.

    The ResultRef is a lightweight pointer that can be:
    - Serialized to JSON for event payloads
    - Passed between steps via templates
    - Resolved to actual data on demand

    URI format: noetl://execution/<eid>/result/<step>/<id>

    Access in templates:
    - {{ step_name.result }}       - Full result (triggers resolution)
    - {{ step_name.field_name }}   - Extracted field (no resolution)
    - {{ step_name.accumulated }}  - Accumulated results manifest
    - {{ step_name._ref }}         - Raw reference URI
    """
    kind: Literal["result_ref", "temp_ref"] = Field(default="result_ref")
    ref: str = Field(
        ...,
        description="Logical URI: noetl://execution/<eid>/result/<step>/<id>"
    )
    store: StoreTier = Field(
        default=StoreTier.KV,
        description="Storage tier where data resides"
    )
    scope: Scope = Field(
        default=Scope.EXECUTION,
        description="Lifecycle scope"
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="TTL expiration timestamp (None for forever scope)"
    )
    meta: ResultRefMeta = Field(default_factory=ResultRefMeta)
    preview: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Truncated sample for UI/debugging (max 1KB)"
    )
    extracted: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Extracted fields from output.select (available without resolution)"
    )
    correlation: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Loop/pagination/retry tracking keys"
    )
    # Accumulation fields
    is_accumulated: bool = Field(default=False, description="Is part of accumulation")
    accumulation_index: Optional[int] = Field(default=None, description="Index in accumulation")
    accumulation_manifest_ref: Optional[str] = Field(default=None, description="Parent manifest ref")

    @field_validator('ref')
    @classmethod
    def validate_ref_format(cls, v: str) -> str:
        """Validate ref URI format."""
        if not v.startswith("noetl://"):
            raise ValueError("ResultRef ref must start with noetl://")
        return v

    @classmethod
    def create(
        cls,
        execution_id: str,
        name: str,
        store: StoreTier = StoreTier.KV,
        scope: Scope = Scope.EXECUTION,
        ttl_seconds: Optional[int] = None,
        meta: Optional[ResultRefMeta] = None,
        correlation: Optional[Dict[str, Any]] = None,
        extracted: Optional[Dict[str, Any]] = None
    ) -> "ResultRef":
        """Factory method to create a new ResultRef."""
        ref_id = str(uuid.uuid4())[:8]
        ref = f"noetl://execution/{execution_id}/result/{name}/{ref_id}"

        expires_at = None
        # For forever scope, never set expiry
        if scope != Scope.PERMANENT and ttl_seconds and ttl_seconds > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        return cls(
            ref=ref,
            store=store,
            scope=scope,
            expires_at=expires_at,
            meta=meta or ResultRefMeta(),
            correlation=correlation,
            extracted=extracted
        )

    def is_expired(self) -> bool:
        """Check if this ResultRef has expired."""
        # Forever scope never expires
        if self.scope == Scope.PERMANENT:
            return False
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def to_key(self) -> str:
        """Convert ref URI to a storage key (safe for KV/Object stores)."""
        return self.ref.replace("noetl://", "").replace("/", "_")

    @classmethod
    def from_key(cls, key: str, store: StoreTier = StoreTier.KV) -> str:
        """Convert storage key back to ref URI."""
        return "noetl://" + key.replace("_", "/")


# Legacy alias for backwards compatibility
TempRef = ResultRef


class ManifestPart(BaseModel):
    """Single part in a manifest."""
    ref: Union[str, Dict[str, Any]] = Field(
        ..., description="Reference to part data (TempRef URI or inline dict)"
    )
    index: int = Field(..., description="Part order index")
    bytes_size: int = Field(default=0, description="Part size in bytes")
    meta: Optional[Dict[str, Any]] = Field(default=None)


class Manifest(BaseModel):
    """
    Manifest for aggregated results (pagination, loops).

    Instead of merging large datasets in memory, a manifest
    references the parts for streaming access.

    URI format: noetl://execution/<eid>/manifest/<name>/<id>
    """
    kind: Literal["manifest"] = Field(default="manifest")
    ref: str = Field(
        ...,
        description="Logical URI for the manifest itself"
    )
    execution_id: str = Field(..., description="Execution this manifest belongs to")
    strategy: Literal["append", "replace", "merge", "concat"] = Field(
        default="append",
        description="How to combine parts"
    )
    merge_path: Optional[str] = Field(
        default=None,
        description="JSONPath for nested array merge (e.g., $.data.items)"
    )
    parts: List[ManifestPart] = Field(default_factory=list)
    total_parts: int = Field(default=0)
    total_bytes: int = Field(default=0)
    source_step: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)
    correlation: Optional[Dict[str, Any]] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)

    @classmethod
    def create(
        cls,
        execution_id: str,
        name: str,
        strategy: str = "append",
        merge_path: Optional[str] = None,
        source_step: Optional[str] = None,
        correlation: Optional[Dict[str, Any]] = None
    ) -> "Manifest":
        """Factory method to create a new Manifest."""
        ref_id = str(uuid.uuid4())[:8]
        ref = f"noetl://execution/{execution_id}/manifest/{name}/{ref_id}"

        return cls(
            ref=ref,
            execution_id=execution_id,
            strategy=strategy,
            merge_path=merge_path,
            source_step=source_step,
            correlation=correlation
        )

    def add_part(
        self,
        part_ref: Union[str, TempRef, Dict[str, Any]],
        bytes_size: int = 0,
        meta: Optional[Dict[str, Any]] = None
    ) -> ManifestPart:
        """Add a part to the manifest."""
        if isinstance(part_ref, TempRef):
            ref_value = part_ref.ref
        elif isinstance(part_ref, dict):
            ref_value = part_ref
        else:
            ref_value = part_ref

        part = ManifestPart(
            ref=ref_value,
            index=len(self.parts),
            bytes_size=bytes_size,
            meta=meta
        )
        self.parts.append(part)
        self.total_parts = len(self.parts)
        self.total_bytes += bytes_size
        return part

    def mark_complete(self):
        """Mark the manifest as complete."""
        self.completed_at = datetime.now(timezone.utc)
        self.total_parts = len(self.parts)


# Type aliases for convenience
AnyRef = Union[ResultRef, Manifest, Dict[str, Any], str]


__all__ = [
    "StoreTier",
    "Scope",
    "ResultRefMeta",
    "ResultRef",
    "ManifestPart",
    "Manifest",
    "AnyRef",
    # Legacy aliases
    "TempRefMeta",
    "TempRef",
]
