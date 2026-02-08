"""
Worker result handler with output_select pattern support.

Handles large results by:
1. Detecting when result exceeds inline threshold
2. Storing large results in external storage (NATS KV/Object, S3, GCS)
3. Extracting small fields for render_context (output_select)
4. Returning ResultRef pointer with extracted fields

Usage in worker:
    from noetl.worker.result_handler import ResultHandler

    handler = ResultHandler(execution_id="123", server_url="http://...")
    processed = await handler.process_result(
        step_name="fetch_data",
        result=large_result,
        output_config=step.get("result", {})
    )
    # Returns: {"_ref": ResultRef, "status": "ok", "count": 100, ...extracted fields}
"""

import os
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from noetl.core.storage import (
    ResultStore,
    ResultRef,
    StoreTier,
    Scope,
    default_store,
    extract_output_select,
    estimate_size,
    should_externalize,
    create_preview,
)
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


# Default thresholds (can be overridden via env vars)
INLINE_MAX_BYTES = int(os.getenv("NOETL_INLINE_MAX_BYTES", "65536"))  # 64KB
PREVIEW_MAX_BYTES = int(os.getenv("NOETL_PREVIEW_MAX_BYTES", "1024"))  # 1KB


class ResultHandler:
    """
    Handles result storage and output_select extraction for workers.

    Automatically externalizes large results while keeping small fields
    available for templating in subsequent steps.
    """

    def __init__(
        self,
        execution_id: str,
        store: Optional[ResultStore] = None,
        inline_max_bytes: int = INLINE_MAX_BYTES,
        default_tier: Optional[StoreTier] = None,
    ):
        """
        Initialize result handler.

        Args:
            execution_id: Current execution ID
            store: ResultStore instance (uses default if None)
            inline_max_bytes: Threshold for inline vs external storage
            default_tier: Default storage tier for large results
        """
        self.execution_id = execution_id
        self.store = store or default_store
        self.inline_max_bytes = inline_max_bytes
        self.default_tier = default_tier or self._get_default_tier()

    def _get_default_tier(self) -> StoreTier:
        """Get default storage tier from environment."""
        tier_name = os.getenv("NOETL_DEFAULT_STORAGE_TIER", "kv").lower()
        tier_map = {
            "memory": StoreTier.MEMORY,
            "kv": StoreTier.KV,
            "object": StoreTier.OBJECT,
            "s3": StoreTier.S3,
            "gcs": StoreTier.GCS,
        }
        return tier_map.get(tier_name, StoreTier.KV)

    async def process_result(
        self,
        step_name: str,
        result: Any,
        output_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process step result for storage and template access.

        If result is small enough, returns it inline.
        If result is large, stores externally and returns:
        - _ref: ResultRef for lazy loading
        - _preview: Truncated preview
        - ...extracted fields from output_select

        Args:
            step_name: Name of the step
            result: Raw result data
            output_config: Optional result configuration from step definition:
                {
                    "store": {"kind": "auto"|"s3"|"gcs"|..., ...},
                    "output_select": ["field1", "data.nested.field"],
                    "inline_max_bytes": 65536
                }

        Returns:
            Processed result dict suitable for render_context
        """
        if result is None:
            return {"_value": None}

        output_config = output_config or {}

        # Check size
        size_bytes = estimate_size(result)
        threshold = output_config.get("inline_max_bytes", self.inline_max_bytes)

        logger.debug(
            f"[RESULT] Step {step_name}: size={size_bytes}b, threshold={threshold}b, "
            f"externalize={size_bytes > threshold}"
        )

        # Small result - return inline
        if size_bytes <= threshold:
            logger.info(f"[RESULT] Step {step_name}: inline result ({size_bytes}b)")
            # Still extract output_select if specified for consistency
            if "output_select" in output_config:
                extracted = extract_output_select(
                    result, output_config.get("output_select")
                )
                return {**extracted, "_inline": result}
            return result

        # Large result - store externally
        logger.info(f"[RESULT] Step {step_name}: externalizing result ({size_bytes}b)")

        # Determine storage tier
        store_config = output_config.get("store", {})
        tier = self._select_tier(size_bytes, store_config)
        logger.debug(f"[RESULT] Step {step_name}: store_config={store_config}, selected_tier={tier.value}")

        # Store result
        try:
            ref = await self.store.put(
                execution_id=self.execution_id,
                name=step_name,
                data=result,
                scope=Scope.EXECUTION,
                store=tier,
                source_step=step_name,
            )
            logger.info(f"[RESULT] Stored {step_name} -> {ref.ref} (tier={tier.value})")
        except Exception as e:
            logger.error(f"[RESULT] Failed to store {step_name}: {e}")
            # Fallback to inline on storage failure
            return result

        # Extract output_select fields
        select_paths = output_config.get("output_select")
        extracted = extract_output_select(result, select_paths)

        # Create preview
        preview = create_preview(result, PREVIEW_MAX_BYTES)

        # Build result with ref and extracted fields
        # Use mode="json" to ensure datetime fields are serialized as ISO strings
        processed = {
            "_ref": ref.model_dump(mode="json"),
            "_preview": preview,
            "_size_bytes": size_bytes,
            "_store": tier.value,
            **extracted,
        }

        return processed

    def _select_tier(self, size_bytes: int, store_config: Dict[str, Any]) -> StoreTier:
        """Select storage tier based on size and config."""
        # Explicit tier from config
        kind = store_config.get("kind", "auto")
        if kind != "auto":
            tier_map = {
                "memory": StoreTier.MEMORY,
                "kv": StoreTier.KV,
                "object": StoreTier.OBJECT,
                "s3": StoreTier.S3,
                "gcs": StoreTier.GCS,
            }
            return tier_map.get(kind, self.default_tier)

        # Auto-select based on size
        if size_bytes < 1024 * 1024:  # < 1MB -> NATS KV
            return StoreTier.KV
        elif size_bytes < 10 * 1024 * 1024:  # < 10MB -> NATS Object
            return StoreTier.OBJECT
        else:  # >= 10MB -> Cloud storage (prefer GCS if configured, else S3)
            if self.default_tier in (StoreTier.S3, StoreTier.GCS):
                return self.default_tier
            # Check if GCS is configured
            if os.getenv("NOETL_GCS_BUCKET"):
                return StoreTier.GCS
            return StoreTier.S3

    async def resolve_ref(self, ref: Any) -> Any:
        """
        Resolve a ResultRef to its full data.

        Used when a step needs full access to externalized data.

        Args:
            ref: ResultRef dict, ResultRef object, or ref string

        Returns:
            Full result data
        """
        return await self.store.resolve(ref)


def wrap_result_with_ref(
    result: Any,
    ref: ResultRef,
    extracted: Dict[str, Any],
    preview: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Wrap a result with ResultRef for render_context.

    Creates a dict that:
    - Has extracted fields available directly ({{ step_name.status }})
    - Has _ref for lazy loading ({{ step_name._ref }})
    - Has _preview for UI display

    Args:
        result: Original result (not included in output)
        ref: ResultRef pointer
        extracted: Extracted output_select fields
        preview: Optional preview

    Returns:
        Dict for render_context
    """
    wrapped = {
        "_ref": ref.model_dump(mode="json") if isinstance(ref, ResultRef) else ref,
        "_size_bytes": ref.meta.bytes if isinstance(ref, ResultRef) else 0,
        "_store": ref.store.value if isinstance(ref, ResultRef) else "unknown",
    }

    if preview:
        wrapped["_preview"] = preview

    # Add extracted fields at top level for easy template access
    wrapped.update(extracted)

    return wrapped


def is_result_ref(value: Any) -> bool:
    """Check if a value is a ResultRef wrapper."""
    if isinstance(value, dict):
        return "_ref" in value and isinstance(value["_ref"], dict)
    return False


def get_ref_from_result(value: Any) -> Optional[Dict[str, Any]]:
    """Extract ResultRef dict from a wrapped result."""
    if is_result_ref(value):
        return value["_ref"]
    return None


__all__ = [
    "ResultHandler",
    "wrap_result_with_ref",
    "is_result_ref",
    "get_ref_from_result",
    "INLINE_MAX_BYTES",
    "PREVIEW_MAX_BYTES",
]
