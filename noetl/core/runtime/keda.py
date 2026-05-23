"""KEDA scaler generator for NoETL worker pools.

v2 spec Phase 4 round 2 — produces a KEDA v1alpha1 ``ScaledObject``
manifest for the ``nats-jetstream`` scaler from a worker-pool URN +
trigger parameters. Subjects + consumer names derive from
:mod:`noetl.core.resource_locator` (round 1) so a future multi-pool
deployment can spin up scalers programmatically without copy-pasting
YAML.

Out of scope for this round:

- No live KEDA install or cluster-side automation. The wiki page
  documents the one-off ``helm install kedacore/keda`` step the
  human runs after merge.
- No edits to ``ci/manifests/noetl/worker-deployment.yaml``. The
  static ``replicas: 3`` remains as the Deployment's initial state;
  KEDA reconciles it once installed.
- No NATS supercluster topology (Phase 4 round 3).
- No catalog-driven dynamic scaling. A future round can iterate
  worker-pool URNs from the catalog and call this generator
  programmatically; this round only provides the generator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import yaml

from noetl.core.resource_locator import (
    NATS_SUBJECT_ROOT,
    NoetlResourceLocator,
    parse_noetl_locator,
)


#: KEDA ``nats-jetstream`` scaler defaults. Tuned for the existing
#: single-pool NoETL worker Deployment; expose as constants so the
#: wiki + tests reference one source of truth.
DEFAULT_LAG_THRESHOLD = 10
DEFAULT_ACTIVATION_LAG_THRESHOLD = 1
DEFAULT_POLLING_INTERVAL_SECONDS = 10
DEFAULT_COOLDOWN_SECONDS = 30
DEFAULT_MIN_REPLICAS = 1
DEFAULT_MAX_REPLICAS = 20

#: NATS stream the existing ``noetl-worker`` Deployment consumes from
#: (see ``ci/manifests/noetl/configmap-worker.yaml`` → ``NATS_STREAM``).
DEFAULT_NATS_STREAM = "NOETL_COMMANDS"

#: NATS monitoring endpoint inside the kind / Kubernetes cluster.
#: KEDA's ``nats-jetstream`` scaler scrapes this endpoint to read
#: consumer lag. Matches ``ci/manifests/nats/`` defaults.
DEFAULT_NATS_MONITORING_ENDPOINT = "nats.nats.svc.cluster.local:8222"

#: NATS default-account marker. ``$G`` is the global account; per-tenant
#: accounts come in Phase 4 round 3 (supercluster).
DEFAULT_NATS_ACCOUNT = "$G"


def worker_pool_segment(worker_pool_urn: str) -> str:
    """Return the last NATS-safe segment of a worker-pool URN.

    Useful for label selectors, scaler-name derivation, and any other
    case where the caller wants the pool's terminal identity without
    rebuilding the full ScaledObject.
    """
    locator = parse_noetl_locator(worker_pool_urn)
    if not locator.segments:
        raise ValueError(f"worker pool URN has no segments: {worker_pool_urn!r}")
    # to_nats_subject() returns "noetl.<seg-1>.<seg-2>...<seg-N>"; we
    # want the last segment with the NATS-safe collapse applied. Splitting
    # the subject form is cheaper than re-running the regex per segment.
    subject = locator.to_nats_subject()
    parts = subject.split(".")
    if len(parts) < 2:
        raise ValueError(f"worker pool URN produced empty subject body: {worker_pool_urn!r}")
    return parts[-1]


def _derive_consumer_name(worker_pool_urn: str) -> str:
    """Derive a NATS consumer name from a worker-pool URN.

    The consumer name is the URN's NATS subject form minus the
    ``noetl.`` prefix and with ``.`` collapsed to ``_`` so the result
    is a single NATS identifier (consumer names disallow ``.``).
    """
    locator = parse_noetl_locator(worker_pool_urn)
    subject = locator.to_nats_subject()
    prefix = f"{NATS_SUBJECT_ROOT}."
    body = subject[len(prefix):] if subject.startswith(prefix) else subject
    return body.replace(".", "_")


@dataclass(frozen=True)
class ScaledObjectSpec:
    """Inputs to a KEDA ``ScaledObject`` for a NoETL worker pool.

    Required fields:

    - ``worker_pool_urn`` — canonical worker URN
      (``noetl://tenant/.../worker/<pool>``). Drives name + consumer
      derivation when those aren't overridden.
    - ``deployment`` — name of the target Deployment in the same
      namespace.

    Every other field has a default; override only when the deployment
    diverges from the defaults shipped with the round-2 sample.
    """

    worker_pool_urn: str
    deployment: str
    namespace: str = "noetl"
    scaler_name: Optional[str] = None
    min_replicas: int = DEFAULT_MIN_REPLICAS
    max_replicas: int = DEFAULT_MAX_REPLICAS
    polling_interval_seconds: int = DEFAULT_POLLING_INTERVAL_SECONDS
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    nats_monitoring_endpoint: str = DEFAULT_NATS_MONITORING_ENDPOINT
    nats_account: str = DEFAULT_NATS_ACCOUNT
    nats_stream: str = DEFAULT_NATS_STREAM
    nats_consumer: Optional[str] = None
    lag_threshold: int = DEFAULT_LAG_THRESHOLD
    activation_lag_threshold: int = DEFAULT_ACTIVATION_LAG_THRESHOLD


def build_worker_scaledobject(spec: ScaledObjectSpec) -> dict[str, Any]:
    """Produce a KEDA v1alpha1 ``ScaledObject`` dict for a worker pool.

    The returned dict can be serialized to YAML via
    :func:`dump_scaledobject_yaml` or rendered directly by callers that
    apply it through the Kubernetes Python client.

    Validation rules:

    - ``worker_pool_urn`` must parse and its ``kind`` must be
      ``"tenant"`` (the worker-pool URN shape from round 1's
      ``worker_locator``). Other kinds raise :class:`ValueError`.
    - ``min_replicas >= 0``.
    - ``max_replicas >= min_replicas``.
    - ``lag_threshold > 0``.
    - ``activation_lag_threshold >= 0``.
    - ``polling_interval_seconds > 0``.
    - ``cooldown_seconds > 0``.

    Derived defaults (applied when the corresponding field is ``None``
    on the spec):

    - ``scaler_name`` →
      ``f"{spec.deployment}-scaler-{worker_pool_segment(...)}"``.
    - ``nats_consumer`` → NATS subject body of the URN with ``.``
      collapsed to ``_``.
    """
    # --- URN validation ---
    locator = parse_noetl_locator(spec.worker_pool_urn)
    if locator.kind != "tenant":
        raise ValueError(
            f"worker_pool_urn must be a tenant-shaped URN "
            f'(noetl://tenant/.../worker/...); got kind {locator.kind!r}'
        )

    # --- numeric validation ---
    if spec.min_replicas < 0:
        raise ValueError(f"min_replicas must be >= 0; got {spec.min_replicas}")
    if spec.max_replicas < spec.min_replicas:
        raise ValueError(
            f"max_replicas must be >= min_replicas; got "
            f"min={spec.min_replicas}, max={spec.max_replicas}"
        )
    if spec.lag_threshold <= 0:
        raise ValueError(f"lag_threshold must be > 0; got {spec.lag_threshold}")
    if spec.activation_lag_threshold < 0:
        raise ValueError(
            f"activation_lag_threshold must be >= 0; got {spec.activation_lag_threshold}"
        )
    if spec.polling_interval_seconds <= 0:
        raise ValueError(
            f"polling_interval_seconds must be > 0; got {spec.polling_interval_seconds}"
        )
    if spec.cooldown_seconds <= 0:
        raise ValueError(f"cooldown_seconds must be > 0; got {spec.cooldown_seconds}")

    # --- derivations ---
    pool_segment = worker_pool_segment(spec.worker_pool_urn)
    scaler_name = spec.scaler_name or f"{spec.deployment}-scaler-{pool_segment}"
    nats_consumer = spec.nats_consumer or _derive_consumer_name(spec.worker_pool_urn)

    # --- KEDA v1alpha1 ScaledObject (see https://keda.sh/docs/2.15/scalers/nats-jetstream/) ---
    # KEDA requires every trigger-metadata value to be a string, even
    # for numeric fields. The dict structure mirrors the YAML form so
    # diffs against committed manifests are reviewable.
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": scaler_name,
            "namespace": spec.namespace,
            "labels": {
                "app": spec.deployment,
                "worker-pool": pool_segment,
                "managed-by": "noetl",
            },
        },
        "spec": {
            "scaleTargetRef": {"name": spec.deployment},
            "minReplicaCount": spec.min_replicas,
            "maxReplicaCount": spec.max_replicas,
            "pollingInterval": spec.polling_interval_seconds,
            "cooldownPeriod": spec.cooldown_seconds,
            "triggers": [
                {
                    "type": "nats-jetstream",
                    "metadata": {
                        "natsServerMonitoringEndpoint": spec.nats_monitoring_endpoint,
                        "account": spec.nats_account,
                        "stream": spec.nats_stream,
                        "consumer": nats_consumer,
                        "lagThreshold": str(spec.lag_threshold),
                        "activationLagThreshold": str(spec.activation_lag_threshold),
                        "useHttps": "false",
                    },
                }
            ],
        },
    }


def dump_scaledobject_yaml(scaledobject: dict[str, Any]) -> str:
    """Render a ScaledObject dict to a YAML string with stable key order.

    Uses ``yaml.safe_dump(..., sort_keys=False)`` so the structural
    ordering set by :func:`build_worker_scaledobject` survives — the
    serialized form has ``apiVersion``, ``kind``, ``metadata``,
    ``spec`` in that order, which matches Kubernetes manifest
    conventions and keeps diffs reviewable.
    """
    return yaml.safe_dump(scaledobject, sort_keys=False, default_flow_style=False)


__all__ = [
    "DEFAULT_ACTIVATION_LAG_THRESHOLD",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_LAG_THRESHOLD",
    "DEFAULT_MAX_REPLICAS",
    "DEFAULT_MIN_REPLICAS",
    "DEFAULT_NATS_ACCOUNT",
    "DEFAULT_NATS_MONITORING_ENDPOINT",
    "DEFAULT_NATS_STREAM",
    "DEFAULT_POLLING_INTERVAL_SECONDS",
    "ScaledObjectSpec",
    "build_worker_scaledobject",
    "dump_scaledobject_yaml",
    "worker_pool_segment",
]
