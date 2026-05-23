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


def test_parse_worker_locator_returns_cloud_os_parts():
    from noetl.core.runtime.topology import parse_worker_locator

    parts = parse_worker_locator(
        "noetl://tenant/tenant-a/org/org-a/cluster/cluster-a/node/node-a/worker/worker-cpu-01"
    )

    assert parts.tenant_id == "tenant-a"
    assert parts.organization_id == "org-a"
    assert parts.cluster_id == "cluster-a"
    assert parts.node_id == "node-a"
    assert parts.worker_pool == "worker-cpu-01"
    assert parts.as_locality() == {
        "cluster_id": "cluster-a",
        "node_id": "node-a",
        "worker_pool": "worker-cpu-01",
    }


def test_parse_worker_locator_rejects_non_worker_locator():
    import pytest

    from noetl.core.resource_locator import ResourceLocatorError
    from noetl.core.runtime.topology import parse_worker_locator

    with pytest.raises(ResourceLocatorError, match="must start with tenant"):
        parse_worker_locator("noetl://execution/123/result/load/abcd")

    with pytest.raises(ResourceLocatorError, match="missing required segments"):
        parse_worker_locator("noetl://tenant/tenant-a/org/org-a")


def test_worker_locator_emits_region_and_zone_in_coarse_to_fine_order():
    from noetl.core.runtime.topology import worker_locator

    uri = worker_locator(
        tenant_id="acme",
        organization_id="research",
        worker_id="worker-cpu-01",
        locality={
            "region": "us-east1",
            "zone": "us-east1-b",
            "cluster_id": "prod",
            "node_id": "node-a",
            "worker_pool": "worker-cpu-01",
        },
    )

    # Coarse-to-fine: region → zone → cluster → node → worker
    assert (
        uri
        == "noetl://tenant/acme/org/research/region/us-east1/zone/us-east1-b"
        "/cluster/prod/node/node-a/worker/worker-cpu-01"
    )


def test_worker_locator_emits_region_only_when_zone_unset():
    from noetl.core.runtime.topology import worker_locator

    uri = worker_locator(
        tenant_id="acme",
        organization_id="research",
        worker_id="worker-cpu-01",
        locality={"region": "us-east1", "worker_pool": "worker-cpu-01"},
    )

    assert (
        uri
        == "noetl://tenant/acme/org/research/region/us-east1/worker/worker-cpu-01"
    )


def test_worker_locator_without_region_or_zone_is_back_compat():
    """Existing call shape produces the pre-round-1 URN unchanged."""
    from noetl.core.runtime.topology import worker_locator

    uri = worker_locator(
        tenant_id="tenant-a",
        organization_id="org-a",
        worker_id="worker-a",
        locality={
            "cluster_id": "cluster-a",
            "node_id": "node-a",
            "worker_pool": "worker-cpu-01",
        },
    )

    # Pre-round-1 canonical form — no region/zone segments.
    assert (
        uri
        == "noetl://tenant/tenant-a/org/org-a/cluster/cluster-a/node/node-a/worker/worker-cpu-01"
    )


def test_parse_worker_locator_populates_region_and_zone():
    from noetl.core.runtime.topology import parse_worker_locator

    parts = parse_worker_locator(
        "noetl://tenant/acme/org/research/region/us-east1/zone/us-east1-b"
        "/cluster/prod/node/node-a/worker/worker-cpu-01"
    )

    assert parts.region == "us-east1"
    assert parts.zone == "us-east1-b"
    assert parts.cluster_id == "prod"
    assert parts.node_id == "node-a"
    assert parts.worker_pool == "worker-cpu-01"


def test_parse_worker_locator_back_compat_without_region_zone():
    from noetl.core.runtime.topology import parse_worker_locator

    parts = parse_worker_locator(
        "noetl://tenant/acme/org/research/cluster/prod/worker/worker-cpu-01"
    )

    assert parts.region is None
    assert parts.zone is None
    assert parts.cluster_id == "prod"
    assert parts.worker_pool == "worker-cpu-01"


def test_worker_locator_parts_as_locality_includes_region_zone():
    from noetl.core.runtime.topology import WorkerLocatorParts

    parts = WorkerLocatorParts(
        tenant_id="acme",
        organization_id="research",
        worker_pool="cpu-01",
        cluster_id="prod",
        node_id="node-a",
        region="us-east1",
        zone="us-east1-b",
    )

    assert parts.as_locality() == {
        "worker_pool": "cpu-01",
        "region": "us-east1",
        "zone": "us-east1-b",
        "cluster_id": "prod",
        "node_id": "node-a",
    }


def test_parse_worker_locator_rejects_unknown_segment():
    """The allowlist still bars segments outside the known schema."""
    import pytest

    from noetl.core.resource_locator import ResourceLocatorError
    from noetl.core.runtime.topology import parse_worker_locator

    with pytest.raises(ResourceLocatorError, match="unknown segments: country"):
        parse_worker_locator(
            "noetl://tenant/acme/org/research/country/uk/worker/worker-cpu-01"
        )


def test_locality_distance_prefers_closest_match():
    from noetl.core.runtime.topology import locality_distance, locality_within, placement_evaluation

    source = {
        "cluster_id": "cluster-a",
        "region": "us-central1",
        "zone": "us-central1-a",
        "node_id": "node-a",
    }

    assert locality_distance(source, {**source, "node_id": "node-a"}) == "node"
    assert locality_distance(source, {**source, "node_id": "node-b"}) == "zone"
    assert locality_distance(source, {**source, "zone": "us-central1-b", "node_id": "node-c"}) == "region"
    assert (
        locality_distance(
            source,
            {"cluster_id": "cluster-a", "region": "us-east1", "zone": "us-east1-b", "node_id": "node-d"},
        )
        == "cluster"
    )
    assert locality_distance(source, {"cluster_id": "cluster-b"}) == "any"
    assert locality_within(source, {**source, "node_id": "node-b"}, max_distance="zone")
    assert not locality_within(source, {"cluster_id": "cluster-b"}, max_distance="region")
    assert placement_evaluation(
        source=source,
        target={**source, "node_id": "node-b"},
        max_distance="zone",
    ) == {
        "distance": "zone",
        "max_distance": "zone",
        "within_max_distance": True,
    }
