"""Unit tests for the NATS supercluster topology generator
(v2 spec Phase 4 round 3)."""

from __future__ import annotations

import pytest
import yaml

from noetl.core.runtime.nats_topology import (
    DEFAULT_CLIENT_PORT,
    DEFAULT_CLUSTER_PORT,
    DEFAULT_GATEWAY_PORT,
    DEFAULT_MONITORING_PORT,
    DEFAULT_NAMESPACE,
    ClusterTopology,
    SuperclusterTopology,
    build_cluster_manifests,
    build_nats_conf,
    dump_manifests_yaml,
)


def _two_cluster_topo() -> tuple[ClusterTopology, ClusterTopology, SuperclusterTopology]:
    a = ClusterTopology(
        cluster_id="a",
        cluster_size=3,
        region="us-east-1",
        cluster_urn="noetl://tenant/default/org/default/region/us-east-1/cluster/a",
    )
    b = ClusterTopology(
        cluster_id="b",
        cluster_size=3,
        region="us-west-2",
        cluster_urn="noetl://tenant/default/org/default/region/us-west-2/cluster/b",
    )
    return a, b, SuperclusterTopology(clusters=(a, b))


# ---------------------------------------------------------------------------
# ClusterTopology / SuperclusterTopology
# ---------------------------------------------------------------------------


def test_cluster_topology_jetstream_domain_default_from_id():
    cluster = ClusterTopology(cluster_id="east-1")
    # "east-1" has '-' which JetStream domains discourage; we collapse to '_'.
    assert cluster.resolve_jetstream_domain() == "east_1"


def test_cluster_topology_jetstream_domain_from_urn():
    cluster = ClusterTopology(
        cluster_id="a",
        cluster_urn="noetl://tenant/acme/org/research/region/us-east1/cluster/a",
    )
    # URN subject form: noetl.tenant.acme.org.research.region.us-east1.cluster.a
    # → strip noetl. → "tenant.acme.org.research.region.us-east1.cluster.a"
    # → "." → "_", "-" → "_"
    assert cluster.resolve_jetstream_domain() == (
        "tenant_acme_org_research_region_us_east1_cluster_a"
    )


def test_cluster_topology_explicit_domain_wins_over_urn():
    cluster = ClusterTopology(
        cluster_id="a",
        cluster_urn="noetl://tenant/x/org/y/cluster/a",
        jetstream_domain="explicit_value",
    )
    assert cluster.resolve_jetstream_domain() == "explicit_value"


def test_cluster_topology_statefulset_and_service_names():
    cluster = ClusterTopology(cluster_id="a")
    assert cluster.statefulset_name == "nats-cluster-a"
    assert cluster.configmap_name == "nats-cluster-a-config"
    assert cluster.service_name == "nats-cluster-a"


def test_supercluster_validate_rejects_empty_clusters():
    with pytest.raises(ValueError, match="at least one cluster"):
        SuperclusterTopology(clusters=())


def test_supercluster_validate_rejects_duplicate_cluster_ids():
    a = ClusterTopology(cluster_id="a")
    a_dup = ClusterTopology(cluster_id="a", cluster_size=5)
    with pytest.raises(ValueError, match="duplicate cluster_id"):
        SuperclusterTopology(clusters=(a, a_dup))


def test_supercluster_validate_rejects_cluster_size_zero():
    a = ClusterTopology(cluster_id="a", cluster_size=0)
    with pytest.raises(ValueError, match="cluster_size"):
        SuperclusterTopology(clusters=(a,))


def test_supercluster_peers_of_excludes_self():
    a, b, topo = _two_cluster_topo()
    assert topo.peers_of(a) == (b,)
    assert topo.peers_of(b) == (a,)


def test_supercluster_peers_of_returns_empty_for_solo():
    a = ClusterTopology(cluster_id="a")
    topo = SuperclusterTopology(clusters=(a,))
    assert topo.peers_of(a) == ()


# ---------------------------------------------------------------------------
# build_nats_conf
# ---------------------------------------------------------------------------


def test_build_nats_conf_includes_cluster_routes():
    a, _, topo = _two_cluster_topo()
    conf = build_nats_conf(a, supercluster=topo)
    # N pod-DNS routes, one per replica
    for i in range(a.cluster_size):
        expected = (
            f"nats-route://nats-cluster-a-{i}.nats-cluster-a"
            f".nats-supercluster.svc.cluster.local:{DEFAULT_CLUSTER_PORT}"
        )
        assert expected in conf


def test_build_nats_conf_includes_gateway_entries():
    a, b, topo = _two_cluster_topo()
    conf = build_nats_conf(a, supercluster=topo)
    # One gateway entry per peer cluster
    assert 'name: "b"' in conf
    assert (
        f"nats://nats-cluster-b.nats-supercluster.svc.cluster.local"
        f":{DEFAULT_GATEWAY_PORT}"
    ) in conf


def test_build_nats_conf_omits_gateway_block_for_solo_cluster():
    a = ClusterTopology(cluster_id="a")
    topo = SuperclusterTopology(clusters=(a,))
    conf = build_nats_conf(a, supercluster=topo)
    assert "gateway {" not in conf
    # Cluster block still present
    assert "cluster {" in conf


def test_build_nats_conf_preserves_accounts_block():
    a, _, topo = _two_cluster_topo()
    conf = build_nats_conf(a, supercluster=topo)
    assert "accounts {" in conf
    assert "$SYS" in conf
    assert "NOETL" in conf
    assert "jetstream: enabled" in conf


def test_build_nats_conf_jetstream_domain_present():
    a, _, topo = _two_cluster_topo()
    conf = build_nats_conf(a, supercluster=topo)
    assert (
        'domain: "tenant_default_org_default_region_us_east_1_cluster_a"'
        in conf
    )


def test_build_nats_conf_uses_cluster_name():
    a, _, topo = _two_cluster_topo()
    conf = build_nats_conf(a, supercluster=topo)
    assert 'name: "a"' in conf


def test_build_nats_conf_listens_on_default_ports():
    a, _, topo = _two_cluster_topo()
    conf = build_nats_conf(a, supercluster=topo)
    assert f"port: {DEFAULT_CLIENT_PORT}" in conf
    assert f"http_port: {DEFAULT_MONITORING_PORT}" in conf
    assert f"port: {DEFAULT_CLUSTER_PORT}" in conf
    assert f"port: {DEFAULT_GATEWAY_PORT}" in conf


# ---------------------------------------------------------------------------
# build_cluster_manifests
# ---------------------------------------------------------------------------


def test_build_cluster_manifests_emits_configmap_statefulset_service():
    a, _, topo = _two_cluster_topo()
    manifests = build_cluster_manifests(a, supercluster=topo)
    kinds = [m["kind"] for m in manifests]
    assert kinds == ["ConfigMap", "StatefulSet", "Service"]


def test_build_cluster_manifests_rejects_unknown_cluster():
    a, _, topo = _two_cluster_topo()
    stray = ClusterTopology(cluster_id="z")
    with pytest.raises(ValueError, match="not part of the supercluster"):
        build_cluster_manifests(stray, supercluster=topo)


def test_build_cluster_manifests_statefulset_replicas_match_cluster_size():
    a, _, topo = _two_cluster_topo()
    cm, sts, svc = build_cluster_manifests(a, supercluster=topo)
    assert sts["spec"]["replicas"] == a.cluster_size
    assert sts["spec"]["serviceName"] == "nats-cluster-a"


def test_build_cluster_manifests_configmap_carries_nats_conf():
    a, _, topo = _two_cluster_topo()
    cm, _, _ = build_cluster_manifests(a, supercluster=topo)
    assert cm["data"]["nats.conf"] == build_nats_conf(a, supercluster=topo)


def test_build_cluster_manifests_service_is_headless():
    a, _, topo = _two_cluster_topo()
    _, _, svc = build_cluster_manifests(a, supercluster=topo)
    assert svc["spec"]["clusterIP"] == "None"
    port_names = {p["name"] for p in svc["spec"]["ports"]}
    assert port_names == {"client", "monitoring", "cluster", "gateway"}


def test_build_cluster_manifests_service_publishes_not_ready_addresses():
    """Live-validation guard: gateway URLs resolve through the
    Service DNS, and supercluster startup is a chicken-and-egg
    (each cluster waits for its peers' Service to publish
    addresses). publishNotReadyAddresses=True breaks the cycle.
    """
    a, _, topo = _two_cluster_topo()
    _, _, svc = build_cluster_manifests(a, supercluster=topo)
    assert svc["spec"]["publishNotReadyAddresses"] is True


def test_build_cluster_manifests_statefulset_passes_pod_name_via_args():
    """Live-validation guard: NATS requires a unique `server_name`
    per node when JetStream runs in cluster mode. We pull pod name
    via downward API and pass it as --name so each StatefulSet
    replica registers under its own ID.
    """
    a, _, topo = _two_cluster_topo()
    _, sts, _ = build_cluster_manifests(a, supercluster=topo)
    container = sts["spec"]["template"]["spec"]["containers"][0]
    # POD_NAME env via downward API
    env = container["env"]
    assert any(
        e.get("name") == "POD_NAME"
        and e.get("valueFrom", {}).get("fieldRef", {}).get("fieldPath") == "metadata.name"
        for e in env
    )
    # --name $(POD_NAME) on the args list
    assert "--name" in container["args"]
    name_idx = container["args"].index("--name")
    assert container["args"][name_idx + 1] == "$(POD_NAME)"


def test_build_cluster_manifests_uses_split_healthz_endpoints():
    """Live-validation guard: the plain /healthz path returns
    failure during JetStream's meta-layer recovery, which kills
    the pod via liveness before the cluster forms. Use the
    js-server-only and js-enabled-only variants instead.
    """
    a, _, topo = _two_cluster_topo()
    _, sts, _ = build_cluster_manifests(a, supercluster=topo)
    container = sts["spec"]["template"]["spec"]["containers"][0]

    # Liveness probes base NATS only
    assert (
        container["livenessProbe"]["httpGet"]["path"]
        == "/healthz?js-server-only=true"
    )
    # Readiness probes JetStream enabled-only (not full recovery)
    assert (
        container["readinessProbe"]["httpGet"]["path"]
        == "/healthz?js-enabled-only=true"
    )
    # Startup probe with a long failureThreshold gives cluster
    # formation time before liveness kicks in.
    assert container["startupProbe"]["httpGet"]["path"] == "/healthz?js-server-only=true"
    assert container["startupProbe"]["failureThreshold"] >= 30


def test_build_cluster_manifests_statefulset_labels_carry_locality():
    a, _, topo = _two_cluster_topo()
    _, sts, _ = build_cluster_manifests(a, supercluster=topo)
    labels = sts["metadata"]["labels"]
    assert labels["cluster-id"] == "a"
    assert labels["region"] == "us-east-1"
    assert labels["managed-by"] == "noetl"


def test_build_cluster_manifests_uses_supercluster_namespace_default():
    a, _, topo = _two_cluster_topo()
    manifests = build_cluster_manifests(a, supercluster=topo)
    for m in manifests:
        assert m["metadata"]["namespace"] == DEFAULT_NAMESPACE


# ---------------------------------------------------------------------------
# dump_manifests_yaml
# ---------------------------------------------------------------------------


def test_dump_manifests_yaml_round_trip():
    a, _, topo = _two_cluster_topo()
    manifests = build_cluster_manifests(a, supercluster=topo)
    rendered = dump_manifests_yaml(manifests)
    loaded = list(yaml.safe_load_all(rendered))
    assert loaded == manifests


def test_dump_manifests_yaml_uses_doc_separators():
    a, _, topo = _two_cluster_topo()
    rendered = dump_manifests_yaml(build_cluster_manifests(a, supercluster=topo))
    # 3 manifests → at least 2 `---` separators (PyYAML may also
    # emit a leading one; we don't care about the exact count, just
    # that the docs are demarcated).
    assert rendered.count("---") >= 2


