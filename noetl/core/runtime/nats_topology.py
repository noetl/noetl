"""NATS supercluster topology generator.

v2 spec Phase 4 round 3 — produces ``nats.conf`` config blocks and
Kubernetes manifests (ConfigMap + StatefulSet + headless Service)
for a meshed JetStream supercluster.

NATS distinguishes two topologies:

- **Cluster** — 3+ NATS servers connected via a ``cluster {}``
  block, sharing JetStream state via Raft consensus. Single
  account namespace, mutual ``route`` URLs between members.
- **Supercluster** — multiple clusters connected via NATS
  **gateway** connections (``gateway {}`` block). Each cluster
  has its own JetStream state; gateways enable cross-cluster
  subject routing without shared Raft.

This module emits the supercluster shape (the larger of the two);
a degenerate single-cluster supercluster (one cluster, no peers)
emits a valid cluster-only config.

Out of scope for this round:

- No live install automation. The wiki + manifest README document
  the manual ``kubectl apply`` flow.
- No edits to the existing single-node ``ci/manifests/nats/``
  deployment. The supercluster is a separate namespace +
  topology that operators can deploy alongside.
- No client-side rewiring. ``NATSCommandPublisher`` /
  ``NATSCommandSubscriber`` keep pointing at the existing
  single-cluster endpoint. Cluster-aware client routing is
  out-of-phase work.
- No per-tenant NATS accounts. The default ``$SYS`` / ``NOETL``
  account block from the existing ``nats.conf`` is preserved
  verbatim. Per-tenant accounts wait for the catalog era.
- No cross-cluster stream mirror / source configuration. The
  gateway topology enables it; nothing in this round actually
  configures a stream to mirror.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from noetl.core.resource_locator import (
    NATS_SUBJECT_ROOT,
    parse_noetl_locator,
)


#: NATS listens on these ports inside the cluster. Same defaults
#: as the existing single-node manifest plus the supercluster-only
#: gateway port (7222).
DEFAULT_CLIENT_PORT = 4222
DEFAULT_MONITORING_PORT = 8222
DEFAULT_CLUSTER_PORT = 6222
DEFAULT_GATEWAY_PORT = 7222

#: The supercluster lives in its own namespace so the existing
#: single-node deployment in the ``nats`` namespace stays
#: untouched.
DEFAULT_NAMESPACE = "nats-supercluster"

#: JetStream storage defaults — match the existing single-node
#: ConfigMap.
DEFAULT_JETSTREAM_STORE_DIR = "/data/jetstream"
DEFAULT_JETSTREAM_MAX_MEMORY = "1GB"
DEFAULT_JETSTREAM_MAX_FILE = "5GB"
DEFAULT_JETSTREAM_PVC_SIZE = "5Gi"

#: NATS server image. Pinning to ``latest`` mirrors the existing
#: single-node manifest; operators should pin a digest in
#: production.
DEFAULT_NATS_IMAGE = "nats:latest"


#: Accounts block preserved verbatim from
#: ``ci/manifests/nats/nats.yaml`` so callers — and the existing
#: ``noetl`` user — work against the supercluster without
#: rewiring credentials. Per-tenant accounts are out-of-phase
#: follow-up work.
_NATS_ACCOUNTS_BLOCK = """\
accounts {
  $SYS {
    users: [
      { user: sys, password: sys }
    ]
  }
  NOETL {
    jetstream: enabled
    users: [
      { user: noetl, password: noetl }
    ]
  }
}
"""


def _jetstream_domain_for(cluster: "ClusterTopology") -> str:
    """Derive a JetStream ``domain`` value for a cluster.

    JetStream domain names must be a single identifier (no dots,
    no slashes). When a ``cluster_urn`` is supplied, we derive the
    domain from the URN's NATS subject form (round 1's
    ``to_nats_subject()``) — stripping the ``noetl.`` prefix and
    collapsing ``.`` to ``_``. Otherwise we fall back to the
    ``cluster_id`` with ``-`` → ``_`` (since ``-`` is allowed in
    NATS subjects but typically forbidden in JetStream domains).
    """
    if cluster.cluster_urn:
        locator = parse_noetl_locator(cluster.cluster_urn)
        subject = locator.to_nats_subject()
        prefix = f"{NATS_SUBJECT_ROOT}."
        body = subject[len(prefix):] if subject.startswith(prefix) else subject
        return body.replace(".", "_").replace("-", "_")
    return cluster.cluster_id.replace("-", "_")


@dataclass(frozen=True)
class ClusterTopology:
    """One cluster within a NATS supercluster.

    Required:

    - ``cluster_id`` — short identifier (becomes the StatefulSet
      name suffix, ConfigMap name suffix, and gateway/cluster
      ``name`` field).

    Optional:

    - ``cluster_size`` (default 3) — number of replicas in the
      StatefulSet. JetStream's Raft minimum for HA is 3.
    - ``region`` / ``zone`` — locality hints; copied into pod
      labels for scheduling. The cluster_urn carries them as
      well when present.
    - ``cluster_urn`` — canonical ``noetl://`` URN (Phase 4
      round 1) that drives the JetStream ``domain`` derivation.
    - ``jetstream_domain`` — explicit override; wins over the
      URN derivation when set.
    """

    cluster_id: str
    cluster_size: int = 3
    region: Optional[str] = None
    zone: Optional[str] = None
    cluster_urn: Optional[str] = None
    jetstream_domain: Optional[str] = None

    @property
    def statefulset_name(self) -> str:
        return f"nats-cluster-{self.cluster_id}"

    @property
    def configmap_name(self) -> str:
        return f"nats-cluster-{self.cluster_id}-config"

    @property
    def service_name(self) -> str:
        # Headless Service shares the StatefulSet name so the pod
        # DNS shape is ``<statefulset>-<idx>.<service>.<ns>.svc``.
        return self.statefulset_name

    def resolve_jetstream_domain(self) -> str:
        if self.jetstream_domain:
            return self.jetstream_domain
        return _jetstream_domain_for(self)


@dataclass(frozen=True)
class SuperclusterTopology:
    """A set of clusters connected via gateway URLs.

    The supercluster's namespace + image apply to every cluster
    in ``clusters``. Per-cluster overrides live on
    :class:`ClusterTopology` itself.
    """

    clusters: tuple[ClusterTopology, ...]
    namespace: str = DEFAULT_NAMESPACE
    image: str = DEFAULT_NATS_IMAGE

    def __post_init__(self) -> None:
        # Frozen dataclass allows __post_init__ for validation.
        self.validate()

    def validate(self) -> None:
        if not self.clusters:
            raise ValueError("SuperclusterTopology requires at least one cluster")
        seen: set[str] = set()
        for cluster in self.clusters:
            if cluster.cluster_size < 1:
                raise ValueError(
                    f"cluster {cluster.cluster_id!r} cluster_size must be >= 1; "
                    f"got {cluster.cluster_size}"
                )
            if cluster.cluster_id in seen:
                raise ValueError(
                    f"duplicate cluster_id {cluster.cluster_id!r} in supercluster"
                )
            seen.add(cluster.cluster_id)

    def peers_of(self, cluster: ClusterTopology) -> tuple[ClusterTopology, ...]:
        return tuple(c for c in self.clusters if c.cluster_id != cluster.cluster_id)


def _route_url(cluster: ClusterTopology, replica_index: int, namespace: str) -> str:
    """Per-replica intra-cluster route URL."""
    pod = f"{cluster.statefulset_name}-{replica_index}"
    return (
        f"nats-route://{pod}.{cluster.service_name}.{namespace}.svc.cluster.local"
        f":{DEFAULT_CLUSTER_PORT}"
    )


def _gateway_url(peer: ClusterTopology, namespace: str) -> str:
    """Headless-service-fronted gateway URL for a peer cluster."""
    return (
        f"nats://{peer.service_name}.{namespace}.svc.cluster.local"
        f":{DEFAULT_GATEWAY_PORT}"
    )


def _indent(text: str, prefix: str = "  ") -> str:
    """Indent every non-empty line by ``prefix``."""
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def build_nats_conf(
    cluster: ClusterTopology,
    *,
    supercluster: SuperclusterTopology,
) -> str:
    """Render the ``nats.conf`` body for one cluster in the supercluster.

    The supercluster is required (rather than optional) because
    even a single-cluster supercluster needs to know the namespace
    for route URL DNS derivation.

    The output is plain HOCON-ish text — NATS' native config
    format. No Python templater is required.
    """
    namespace = supercluster.namespace
    domain = cluster.resolve_jetstream_domain()

    # Intra-cluster routes — N pod-DNS URLs, one per replica.
    # NATS de-dupes a self-route, so emitting all N entries on
    # every pod is safe and keeps the ConfigMap symmetric across
    # replicas.
    route_lines = [
        f"    {_route_url(cluster, i, namespace)}"
        for i in range(cluster.cluster_size)
    ]
    routes_block = "  routes: [\n" + "\n".join(route_lines) + "\n  ]"

    # Inter-cluster gateways — one entry per peer cluster.
    peers = supercluster.peers_of(cluster)
    if peers:
        gateway_entries = [
            f'    {{ name: "{peer.cluster_id}", urls: ["{_gateway_url(peer, namespace)}"] }}'
            for peer in peers
        ]
        gateway_block = (
            "gateway {\n"
            f'  name: "{cluster.cluster_id}"\n'
            f"  port: {DEFAULT_GATEWAY_PORT}\n"
            "  gateways: [\n"
            + "\n".join(gateway_entries) + "\n"
            "  ]\n"
            "}\n"
        )
    else:
        gateway_block = ""

    jetstream_block = (
        "jetstream {\n"
        f"  store_dir: {DEFAULT_JETSTREAM_STORE_DIR}\n"
        f'  domain: "{domain}"\n'
        f"  max_memory_store: {DEFAULT_JETSTREAM_MAX_MEMORY}\n"
        f"  max_file_store: {DEFAULT_JETSTREAM_MAX_FILE}\n"
        "}\n"
    )

    cluster_block = (
        "cluster {\n"
        f'  name: "{cluster.cluster_id}"\n'
        f"  port: {DEFAULT_CLUSTER_PORT}\n"
        + routes_block + "\n"
        "}\n"
    )

    sections = [
        f"port: {DEFAULT_CLIENT_PORT}",
        f"http_port: {DEFAULT_MONITORING_PORT}",
        "",
        jetstream_block,
        cluster_block,
    ]
    if gateway_block:
        sections.append(gateway_block)
    sections.append(_NATS_ACCOUNTS_BLOCK)

    return "\n".join(sections)


def _build_configmap(
    cluster: ClusterTopology,
    *,
    supercluster: SuperclusterTopology,
) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": cluster.configmap_name,
            "namespace": supercluster.namespace,
            "labels": _cluster_labels(cluster),
        },
        "data": {
            "nats.conf": build_nats_conf(cluster, supercluster=supercluster),
        },
    }


def _build_statefulset(
    cluster: ClusterTopology,
    *,
    supercluster: SuperclusterTopology,
) -> dict[str, Any]:
    name = cluster.statefulset_name
    labels = _cluster_labels(cluster)
    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": name,
            "namespace": supercluster.namespace,
            "labels": labels,
        },
        "spec": {
            "serviceName": cluster.service_name,
            "replicas": cluster.cluster_size,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "containers": [
                        {
                            "name": "nats",
                            "image": supercluster.image,
                            "ports": [
                                {"containerPort": DEFAULT_CLIENT_PORT, "name": "client", "protocol": "TCP"},
                                {"containerPort": DEFAULT_MONITORING_PORT, "name": "monitoring", "protocol": "TCP"},
                                {"containerPort": DEFAULT_CLUSTER_PORT, "name": "cluster", "protocol": "TCP"},
                                {"containerPort": DEFAULT_GATEWAY_PORT, "name": "gateway", "protocol": "TCP"},
                            ],
                            # NATS requires a unique `server_name` per node when
                            # JetStream runs in cluster mode. Pull the pod name
                            # via the downward API and pass it as --name so each
                            # StatefulSet replica registers under its own ID.
                            "env": [
                                {
                                    "name": "POD_NAME",
                                    "valueFrom": {
                                        "fieldRef": {"fieldPath": "metadata.name"}
                                    },
                                }
                            ],
                            "args": [
                                "-c",
                                "/etc/nats/nats.conf",
                                "--name",
                                "$(POD_NAME)",
                            ],
                            "volumeMounts": [
                                {"name": "nats-config", "mountPath": "/etc/nats"},
                                {"name": "nats-storage", "mountPath": "/data"},
                            ],
                            # NATS publishes three healthz variants. For
                            # a clustered JetStream deployment we use:
                            #   liveness:  ?js-server-only=true  — base NATS
                            #              process up. Most forgiving — only
                            #              fails when the server has crashed.
                            #   readiness: ?js-enabled-only=true — JetStream
                            #              enabled and reachable. Pod becomes
                            #              Ready once JS is up; doesn't wait
                            #              for full meta-layer recovery.
                            #   startup:   ?js-server-only=true with a long
                            #              failureThreshold — gives the
                            #              cluster time to form gateway
                            #              connections before liveness kicks in.
                            "startupProbe": {
                                "httpGet": {
                                    "path": "/healthz?js-server-only=true",
                                    "port": DEFAULT_MONITORING_PORT,
                                },
                                "periodSeconds": 5,
                                "failureThreshold": 60,
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/healthz?js-server-only=true",
                                    "port": DEFAULT_MONITORING_PORT,
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10,
                                "failureThreshold": 5,
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": "/healthz?js-enabled-only=true",
                                    "port": DEFAULT_MONITORING_PORT,
                                },
                                "initialDelaySeconds": 10,
                                "periodSeconds": 5,
                            },
                            "resources": {
                                "requests": {"memory": "512Mi", "cpu": "250m"},
                                "limits": {"memory": "2Gi", "cpu": "1000m"},
                            },
                        }
                    ],
                    "volumes": [
                        {
                            "name": "nats-config",
                            "configMap": {"name": cluster.configmap_name},
                        }
                    ],
                },
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "nats-storage"},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "resources": {"requests": {"storage": DEFAULT_JETSTREAM_PVC_SIZE}},
                    },
                }
            ],
        },
    }


def _build_service(
    cluster: ClusterTopology,
    *,
    supercluster: SuperclusterTopology,
) -> dict[str, Any]:
    labels = _cluster_labels(cluster)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": cluster.service_name,
            "namespace": supercluster.namespace,
            "labels": labels,
        },
        "spec": {
            # Headless Service — pods get stable per-replica DNS
            # names for the route URLs we emit in nats.conf.
            "clusterIP": "None",
            # Critical for supercluster: gateway URLs resolve
            # through the Service DNS, and supercluster startup
            # is a chicken-and-egg (each cluster waits for its
            # peers' Service to publish addresses). Setting this
            # to True lets the headless DNS resolve to pods
            # before they reach Ready state, breaking the cycle.
            "publishNotReadyAddresses": True,
            "selector": labels,
            "ports": [
                {"name": "client", "port": DEFAULT_CLIENT_PORT, "targetPort": DEFAULT_CLIENT_PORT, "protocol": "TCP"},
                {"name": "monitoring", "port": DEFAULT_MONITORING_PORT, "targetPort": DEFAULT_MONITORING_PORT, "protocol": "TCP"},
                {"name": "cluster", "port": DEFAULT_CLUSTER_PORT, "targetPort": DEFAULT_CLUSTER_PORT, "protocol": "TCP"},
                {"name": "gateway", "port": DEFAULT_GATEWAY_PORT, "targetPort": DEFAULT_GATEWAY_PORT, "protocol": "TCP"},
            ],
        },
    }


def _cluster_labels(cluster: ClusterTopology) -> dict[str, str]:
    labels: dict[str, str] = {
        "app": cluster.statefulset_name,
        "component": "nats",
        "cluster-id": cluster.cluster_id,
        "managed-by": "noetl",
    }
    if cluster.region:
        labels["region"] = cluster.region
    if cluster.zone:
        labels["zone"] = cluster.zone
    return labels


def build_cluster_manifests(
    cluster: ClusterTopology,
    *,
    supercluster: SuperclusterTopology,
) -> list[dict[str, Any]]:
    """Produce the ConfigMap + StatefulSet + Service for one cluster.

    Returns plain dicts in apply-order so callers can either
    serialize them with :func:`dump_manifests_yaml` or apply them
    directly via the Kubernetes Python client.
    """
    if cluster not in supercluster.clusters:
        raise ValueError(
            f"cluster {cluster.cluster_id!r} is not part of the supercluster"
        )
    return [
        _build_configmap(cluster, supercluster=supercluster),
        _build_statefulset(cluster, supercluster=supercluster),
        _build_service(cluster, supercluster=supercluster),
    ]


def dump_manifests_yaml(manifests: list[dict[str, Any]]) -> str:
    """Render a list of manifests to a single YAML stream.

    Uses ``yaml.safe_dump_all`` with ``sort_keys=False`` so the
    structural ordering set by the builders survives. ``---``
    document markers separate manifests.
    """
    return yaml.safe_dump_all(manifests, sort_keys=False, default_flow_style=False)


__all__ = [
    "ClusterTopology",
    "DEFAULT_CLIENT_PORT",
    "DEFAULT_CLUSTER_PORT",
    "DEFAULT_GATEWAY_PORT",
    "DEFAULT_JETSTREAM_MAX_FILE",
    "DEFAULT_JETSTREAM_MAX_MEMORY",
    "DEFAULT_JETSTREAM_PVC_SIZE",
    "DEFAULT_JETSTREAM_STORE_DIR",
    "DEFAULT_MONITORING_PORT",
    "DEFAULT_NAMESPACE",
    "DEFAULT_NATS_IMAGE",
    "SuperclusterTopology",
    "build_cluster_manifests",
    "build_nats_conf",
    "dump_manifests_yaml",
]
