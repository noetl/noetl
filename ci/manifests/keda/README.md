# KEDA autoscaling for NoETL workers

This directory holds the KEDA `ScaledObject` manifest(s) that scale
the existing `noetl-worker` Deployment based on NATS JetStream
consumer lag. The generator that produced the YAML lives at
[`noetl/core/runtime/keda.py`](../../../noetl/core/runtime/keda.py)
and is documented on the wiki at
[`noetl/core/runtime/keda`](https://github.com/noetl/noetl/wiki/keda).

KEDA install + apply is a **manual one-off step** today. It is
deliberately not bundled into the stock `noetl k8s deploy` workflow
in this round so the diff stays small and reviewable.

## One-time KEDA install

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.15.0
```

Verify the operator is healthy:

```bash
kubectl get pods -n keda
kubectl rollout status deployment/keda-operator -n keda
```

## Apply the worker-pool scaler

```bash
kubectl apply -f ci/manifests/keda/scaledobject-worker-cpu-01.yaml
```

## Verify

```bash
# The ScaledObject itself
kubectl get scaledobject -n noetl noetl-worker-scaler-worker-cpu-01

# KEDA creates an HPA behind the scenes
kubectl get hpa -n noetl

# Full status (active flag, last scale time, trigger health)
kubectl describe scaledobject noetl-worker-scaler-worker-cpu-01 -n noetl
```

To exercise the scaler, drive load through the NATS command stream
(e.g. by submitting playbook executions that fan out work) and watch
`kubectl get deploy -n noetl noetl-worker` replica count climb as
consumer lag exceeds `lagThreshold` (default 10).

## Regenerating after a generator change

The sample manifest is committed verbatim so a unit test
(`tests/core/runtime/test_keda.py::test_sample_manifest_matches_generator_output`)
catches hand-edits. To regenerate after a `noetl.core.runtime.keda`
change:

```python
from noetl.core.runtime.keda import (
    ScaledObjectSpec, build_worker_scaledobject, dump_scaledobject_yaml,
)
spec = ScaledObjectSpec(
    worker_pool_urn="noetl://tenant/default/org/default/worker/worker-cpu-01",
    deployment="noetl-worker",
    nats_consumer="noetl_worker_pool",
)
print(dump_scaledobject_yaml(build_worker_scaledobject(spec)))
```

Pipe the output into `ci/manifests/keda/scaledobject-worker-cpu-01.yaml`,
preserving the header comments.
