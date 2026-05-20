from __future__ import annotations


def test_worker_locality_from_env_uses_topology_values():
    from noetl.core.runtime.topology import worker_locality_from_env

    env = {
        "NOETL_NODE_ID": "node-a",
        "NOETL_CLUSTER_ID": "cluster-a",
        "NOETL_REGION": "us-central1",
        "NOETL_ZONE": "us-central1-a",
        "NOETL_WORKER_POOL_NAME": "worker-cpu-01",
        "NOETL_WORKER_POOL_RUNTIME": "cpu",
    }

    assert worker_locality_from_env(env) == {
        "node_id": "node-a",
        "cluster_id": "cluster-a",
        "region": "us-central1",
        "zone": "us-central1-a",
        "worker_pool": "worker-cpu-01",
        "runtime": "cpu",
    }


def test_worker_locator_builds_canonical_identity():
    from noetl.core.runtime.topology import worker_locator

    assert (
        worker_locator(
            tenant_id="tenant-a",
            organization_id="org-a",
            worker_id="worker-a",
            locality={
                "cluster_id": "cluster-a",
                "node_id": "node-a",
                "worker_pool": "worker-cpu-01",
            },
        )
        == "noetl://tenant/tenant-a/org/org-a/cluster/cluster-a/node/node-a/worker/worker-cpu-01"
    )


def test_worker_locator_returns_none_for_invalid_segments():
    from noetl.core.runtime.topology import worker_locator

    assert (
        worker_locator(
            tenant_id="tenant/a",
            organization_id="org-a",
            worker_id="worker-a",
            locality={},
        )
        is None
    )
