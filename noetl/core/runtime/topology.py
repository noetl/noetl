"""Runtime topology helpers for worker identity and placement metadata."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from noetl.core.resource_locator import ResourceLocatorError, build_noetl_locator

LOCALITY_DISTANCES = ("node", "zone", "region", "cluster", "any")


def worker_locality_from_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return best-effort worker topology from environment variables."""
    env = env or os.environ
    values = {
        "node_id": env.get("NOETL_NODE_ID") or env.get("NODE_NAME") or "",
        "cluster_id": env.get("NOETL_CLUSTER_ID") or env.get("NOETL_CLUSTER_NAME") or "",
        "region": env.get("NOETL_REGION") or "",
        "zone": env.get("NOETL_ZONE") or "",
        "worker_pool": env.get("NOETL_WORKER_POOL_NAME") or "worker-cpu-01",
        "runtime": env.get("NOETL_WORKER_POOL_RUNTIME") or "cpu",
    }
    return {key: value for key, value in values.items() if value}


def worker_locator(
    *,
    tenant_id: Any,
    organization_id: Any,
    worker_id: str,
    locality: Mapping[str, Any] | None = None,
) -> str | None:
    """Build a canonical worker locator from tenant/org and locality metadata."""
    locality = locality or {}
    try:
        segments: list[Any] = [
            "tenant",
            tenant_id or "default",
            "org",
            organization_id or "default",
        ]
        cluster_id = locality.get("cluster_id")
        node_id = locality.get("node_id")
        worker_pool = locality.get("worker_pool") or worker_id
        if cluster_id:
            segments.extend(["cluster", cluster_id])
        if node_id:
            segments.extend(["node", node_id])
        segments.extend(["worker", worker_pool])
        return build_noetl_locator(*segments)
    except (ResourceLocatorError, TypeError, ValueError):
        return None


def locality_distance(
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
) -> str:
    """Return the closest shared locality level between two topology hints."""
    source = source or {}
    target = target or {}
    if _same_non_empty(source, target, "node_id"):
        return "node"
    if _same_non_empty(source, target, "zone"):
        return "zone"
    if _same_non_empty(source, target, "region"):
        return "region"
    if _same_non_empty(source, target, "cluster_id"):
        return "cluster"
    return "any"


def locality_within(
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
    *,
    max_distance: str,
) -> bool:
    """Return whether target is within the requested locality distance."""
    distance = locality_distance(source, target)
    try:
        return LOCALITY_DISTANCES.index(distance) <= LOCALITY_DISTANCES.index(max_distance)
    except ValueError:
        return False


def _same_non_empty(source: Mapping[str, Any], target: Mapping[str, Any], key: str) -> bool:
    source_value = str(source.get(key) or "").strip()
    target_value = str(target.get(key) or "").strip()
    return bool(source_value and target_value and source_value == target_value)


__all__ = [
    "LOCALITY_DISTANCES",
    "locality_distance",
    "locality_within",
    "worker_locality_from_env",
    "worker_locator",
]
