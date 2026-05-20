"""Runtime topology helpers for worker identity and placement metadata."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from noetl.core.resource_locator import ResourceLocatorError, build_noetl_locator


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


__all__ = ["worker_locality_from_env", "worker_locator"]
