"""Runtime topology helpers for worker identity and placement metadata."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from noetl.core.resource_locator import ResourceLocatorError, build_noetl_locator, parse_noetl_locator

LOCALITY_DISTANCES = ("node", "zone", "region", "cluster", "any")


@dataclass(frozen=True)
class WorkerLocatorParts:
    """Cloud OS identity fields encoded by a worker locator."""

    tenant_id: str
    organization_id: str
    worker_pool: str
    cluster_id: str | None = None
    node_id: str | None = None
    region: str | None = None
    zone: str | None = None

    def as_locality(self) -> dict[str, str]:
        locality: dict[str, str] = {"worker_pool": self.worker_pool}
        if self.region:
            locality["region"] = self.region
        if self.zone:
            locality["zone"] = self.zone
        if self.cluster_id:
            locality["cluster_id"] = self.cluster_id
        if self.node_id:
            locality["node_id"] = self.node_id
        return locality


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
        region = locality.get("region")
        zone = locality.get("zone")
        cluster_id = locality.get("cluster_id")
        node_id = locality.get("node_id")
        worker_pool = locality.get("worker_pool") or worker_id
        # Coarse-to-fine: region → zone → cluster → node → worker.
        if region:
            segments.extend(["region", region])
        if zone:
            segments.extend(["zone", zone])
        if cluster_id:
            segments.extend(["cluster", cluster_id])
        if node_id:
            segments.extend(["node", node_id])
        segments.extend(["worker", worker_pool])
        return build_noetl_locator(*segments)
    except (ResourceLocatorError, TypeError, ValueError):
        return None


def parse_worker_locator(value: str) -> WorkerLocatorParts:
    """Parse and validate a canonical Cloud OS worker locator."""
    locator = parse_noetl_locator(value)
    if locator.kind != "tenant":
        raise ResourceLocatorError("worker locator must start with tenant")

    try:
        parts = locator.pairs()
    except ResourceLocatorError as exc:
        raise ResourceLocatorError("worker locator must use alternating key/value segments") from exc

    unknown = sorted(
        set(parts) - {"tenant", "org", "region", "zone", "cluster", "node", "worker"}
    )
    if unknown:
        raise ResourceLocatorError(f"worker locator contains unknown segments: {', '.join(unknown)}")

    required = ("tenant", "org", "worker")
    missing = [key for key in required if not parts.get(key)]
    if missing:
        raise ResourceLocatorError(f"worker locator missing required segments: {', '.join(missing)}")

    return WorkerLocatorParts(
        tenant_id=parts["tenant"],
        organization_id=parts["org"],
        cluster_id=parts.get("cluster"),
        node_id=parts.get("node"),
        region=parts.get("region"),
        zone=parts.get("zone"),
        worker_pool=parts["worker"],
    )


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


def placement_evaluation(
    *,
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
    max_distance: str = "any",
) -> dict[str, Any]:
    """Return a replayable placement evaluation for scheduler/audit metadata."""
    distance = locality_distance(source, target)
    return {
        "distance": distance,
        "max_distance": max_distance,
        "within_max_distance": locality_within(source, target, max_distance=max_distance),
    }


def _same_non_empty(source: Mapping[str, Any], target: Mapping[str, Any], key: str) -> bool:
    source_value = str(source.get(key) or "").strip()
    target_value = str(target.get(key) or "").strip()
    return bool(source_value and target_value and source_value == target_value)


__all__ = [
    "LOCALITY_DISTANCES",
    "locality_distance",
    "locality_within",
    "placement_evaluation",
    "parse_worker_locator",
    "WorkerLocatorParts",
    "worker_locality_from_env",
    "worker_locator",
]
