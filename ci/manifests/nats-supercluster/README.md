# NATS supercluster topology

Manifests for a 2-cluster NATS supercluster (cluster `a` in
`us-east-1` and cluster `b` in `us-west-2`), each a 3-node
StatefulSet with mutual gateway connections. Lives in the
`nats-supercluster` namespace so it can coexist with the
existing single-node NATS deployment in `nats`.

Generator: [`noetl/core/runtime/nats_topology.py`](../../../noetl/core/runtime/nats_topology.py).
Wiki: [`noetl/core/runtime/nats_supercluster`](https://github.com/noetl/noetl/wiki/nats_supercluster).

> **Do not delete `ci/manifests/nats/`.** This round does **not**
> replace the existing single-node deployment. The single-node
> deployment is still the default `noetl k8s deploy` target;
> the supercluster is opt-in.

## Manual install

```bash
kubectl apply -f ci/manifests/nats-supercluster/namespace.yaml
kubectl apply -f ci/manifests/nats-supercluster/cluster-a.yaml
kubectl apply -f ci/manifests/nats-supercluster/cluster-b.yaml
```

Wait for the StatefulSets to roll out:

```bash
kubectl rollout status statefulset/nats-cluster-a -n nats-supercluster
kubectl rollout status statefulset/nats-cluster-b -n nats-supercluster
```

## Verify

```bash
# All pods Running / Ready
kubectl get pods -n nats-supercluster -o wide

# Cluster + gateway state from inside a pod
kubectl exec -n nats-supercluster nats-cluster-a-0 -- \
  nats-server --version
kubectl exec -n nats-supercluster nats-cluster-a-0 -- \
  /bin/sh -c 'curl -s http://localhost:8222/varz | head -40'
kubectl exec -n nats-supercluster nats-cluster-a-0 -- \
  /bin/sh -c 'curl -s http://localhost:8222/routez'
kubectl exec -n nats-supercluster nats-cluster-a-0 -- \
  /bin/sh -c 'curl -s http://localhost:8222/gatewayz'
```

If you have the `nats` CLI available locally and a kubectl port-forward
to one of the cluster monitoring ports:

```bash
kubectl port-forward -n nats-supercluster nats-cluster-a-0 8222:8222
nats server list  # uses default 127.0.0.1
nats server gateway list
nats stream cluster-info <stream-name>
```

## Regenerating manifests

The sample manifests are committed verbatim and a unit test
(`tests/core/runtime/test_nats_topology.py::test_sample_cluster_a_yaml_matches_generator_output`
+ the `cluster_b` variant) catches any hand-edit. To regenerate
after a `noetl.core.runtime.nats_topology` change:

```python
from noetl.core.runtime.nats_topology import (
    ClusterTopology, SuperclusterTopology,
    build_cluster_manifests, dump_manifests_yaml,
)
a = ClusterTopology(
    cluster_id="a", cluster_size=3, region="us-east-1",
    cluster_urn="noetl://tenant/default/org/default/region/us-east-1/cluster/a",
)
b = ClusterTopology(
    cluster_id="b", cluster_size=3, region="us-west-2",
    cluster_urn="noetl://tenant/default/org/default/region/us-west-2/cluster/b",
)
topo = SuperclusterTopology(clusters=(a, b))

print(dump_manifests_yaml(build_cluster_manifests(a, supercluster=topo)))  # → cluster-a.yaml body
print(dump_manifests_yaml(build_cluster_manifests(b, supercluster=topo)))  # → cluster-b.yaml body
```

Pipe each output into the matching file, preserving the header
comments.

## What's NOT wired in this round

- Client-side cluster-aware routing. `NATSCommandPublisher`,
  `NATSCommandSubscriber`, and the worker ConfigMap still point at
  the single-node `nats.nats.svc.cluster.local` endpoint. A
  future out-of-phase round adds cluster-aware client routing
  once the catalog can pick the right cluster per request.
- Per-tenant NATS accounts. The default `NOETL` account from the
  existing single-node manifest is preserved verbatim.
- Cross-cluster stream mirror / source. The gateway topology
  makes it possible; no stream is configured to use it.
