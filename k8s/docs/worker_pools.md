# NoETL Worker Pools: CPU vs QPU

This guide explains how to run NoETL workers in separate Kubernetes pools for CPU and QPU workloads, keeping quantum SDKs (Qiskit) installed only in the QPU worker pool and not in the server image.

## What’s included in this repo

- QPU worker image Dockerfile that installs NoETL + Quantum SDKs:
  - docker/noetl/worker-qpu/Dockerfile
- Worker pool deployments:
  - k8s/noetl/worker-cpu-deployment.yaml (uses noetl-pip:latest)
  - k8s/noetl/worker-qpu-deployment.yaml (uses noetl-worker-qpu:latest)
- IBM Quantum credentials Secret template:
  - k8s/noetl/ibm-quantum-secret.yaml

The NoETL server deployment remains unchanged and lean (no Qiskit SDK inside):
- k8s/noetl/noetl-deployment.yaml (uses image noetl-pip:latest)

## Build the QPU worker image

Build and tag the QPU worker image locally (or in your registry):

```bash
docker build -t noetl-worker-qpu:latest -f docker/noetl/worker-qpu/Dockerfile .
```

Push to your registry if needed:

```bash
docker tag noetl-worker-qpu:latest <REGISTRY>/noetl-worker-qpu:latest
docker push <REGISTRY>/noetl-worker-qpu:latest
```

Then update `k8s/noetl/worker-qpu-deployment.yaml` image to your registry if you pushed it.

## Label nodes for CPU and QPU pools

Pick nodes to host CPU and QPU workers. Label them:

```bash
# For CPU pool
kubectl label nodes <cpu-node-name> noetlPool=cpu

# For QPU pool
kubectl label nodes <qpu-node-name> noetlPool=qpu
```

Optionally, taint your QPU nodes so only pods that tolerate the taint are scheduled:

```bash
kubectl taint nodes <qpu-node-name> noetl/qpu=true:NoSchedule
```

Then uncomment the `tolerations` block in `k8s/noetl/worker-qpu-deployment.yaml`.

## Configure Secrets and ConfigMaps

Apply the standard NoETL config/secret (if not already):

```bash
kubectl apply -f k8s/noetl/noetl-configmap.yaml
kubectl apply -f k8s/noetl/noetl-service.yaml
# Your cluster should also have noetl-secret; see project docs for how to create it
```

Add IBM Quantum credentials for QPU workers (fill in the token first):

```bash
# Edit the YAML to set QISKIT_IBM_TOKEN, or create via CLI:
kubectl apply -f k8s/noetl/ibm-quantum-secret.yaml
# or
kubectl create secret generic ibm-quantum-secret \
  --from-literal=QISKIT_IBM_TOKEN=<YOUR_TOKEN> \
  --from-literal=QISKIT_IBM_INSTANCE=ibm-q/open/main \
  --from-literal=QISKIT_IBM_BACKEND=ibm_brisbane
```

## Deploy worker pools

```bash
# CPU workers (no Qiskit SDK)
kubectl apply -f k8s/noetl/worker-cpu-deployment.yaml

# QPU workers (Qiskit SDK installed in image)
kubectl apply -f k8s/noetl/worker-qpu-deployment.yaml
```

Both deployments default to running `noetl cli` to keep pods alive. You can change the container args to run persistent workers on a specific playbook using the built-in worker command.

### Example: Run Grover Qiskit playbook on QPU worker

Edit `k8s/noetl/worker-qpu-deployment.yaml` and set:

```yaml
containers:
  - name: noetl-worker-qpu
    image: noetl-worker-qpu:latest
    command: ["noetl"]
    args: ["worker", "quantum/grover_qiskit", "--version", "latest"]
```

Ensure the playbook is registered in the NoETL catalog and IBM credentials are set in the secret.

### Example: Run CPU-only work on CPU worker

Edit `k8s/noetl/worker-cpu-deployment.yaml` and set:

```yaml
containers:
  - name: noetl-worker-cpu
    image: noetl-pip:latest
    command: ["noetl"]
    args: ["worker", "examples/weather_example", "--version", "latest"]
```

## Why this design?

- The NoETL server remains lean (no quantum SDKs). It serves APIs and catalog.
- CPU and QPU workers run in separate pools, scheduled onto nodes via nodeSelector (and optionally taints/tolerations).
- Only the QPU worker image includes Qiskit SDKs and IBM Runtime, satisfying the requirement to install SDKs in the worker pool, not in the server.

## Notes

- Ensure your workers have network access to the server service and Postgres.
- You can scale each worker pool independently via the Deployment replicas.
- For ad-hoc runs, consider Jobs that use the same images but run `noetl worker ...` and exit.


## Worker API endpoint (single task execution)

The server now exposes a dedicated Worker API (enabled by default) under `/api/worker`.

- Env flag to disable: `NOETL_ENABLE_WORKER_API=false`
- Endpoint: `POST /api/worker/task/execute`

Example request to execute a simple inline Python task and receive a callback:

```bash
echo '{
  "task": {
    "type": "python",
    "code": "def main(x):\n    return {\"x2\": x*x}",
    "with": {"x": 7}
  },
  "context": {"env": {}},
  "requirements": [],
  "callback_url": "http://noetl-server:8084/api/events"
}' | \
  curl -sS -X POST http://noetl-server:8084/api/worker/task/execute \
    -H 'Content-Type: application/json' \
    -d @-
```

Notes:
- `requirements` is optional; if provided, the worker will attempt to `pip install` them when `NOETL_WORKER_ALLOW_INSTALLS=true`.
- The worker will send intermediate events and a final `task_final` event to the `callback_url` if provided.
- Local ephemeral state is stored in an in-memory DuckDB table (fallback to a process-level dict) for fast lookups.

### State store choice: DuckDB vs Redis/Key-Value

- DuckDB (in-memory) is ideal for per-pod, ephemeral state: ultra-fast, zero external deps, and easy to query. This is the default in the Worker API; it falls back to an in-process dict if DuckDB isn’t available.
- Redis/external key-value store is recommended when you need:
  - Cross-pod/shared state or pub/sub semantics
  - Persistence beyond a pod lifecycle
  - Rate limiting/queues or coordination across multiple workers
- Guidance: Start with DuckDB-in-memory for simplicity. If you later need shared or durable state, add a Redis client and forward events/results to Redis in your deployment (without changing the server image).


## Services and apply order

Recommended apply order so in-cluster URLs resolve immediately:

```bash
# 1) Config and Secrets
kubectl apply -f k8s/noetl/noetl-configmap.yaml
kubectl apply -f k8s/noetl/ibm-quantum-secret.yaml   # only if using QPU workers
# plus your project-specific noetl-secret

# 2) Services (server + workers)
kubectl apply -f k8s/noetl/noetl-service.yaml
kubectl apply -f k8s/noetl/worker-cpu-service.yaml
kubectl apply -f k8s/noetl/worker-qpu-service.yaml

# 3) Deployments (server + workers)
kubectl apply -f k8s/noetl/noetl-deployment.yaml
kubectl apply -f k8s/noetl/worker-cpu-deployment.yaml
kubectl apply -f k8s/noetl/worker-qpu-deployment.yaml
```

Environment variables in the ConfigMap preconfigure the Broker routing:
- NOETL_SERVER_URL=http://noetl:8084
- NOETL_WORKER_CPU_URL=http://noetl-worker-cpu:8084
- NOETL_WORKER_QPU_URL=http://noetl-worker-qpu:8084
- NOETL_ENABLE_WORKER_API=true

## Validate the setup

1) Check Services and Pods:
```bash
kubectl get svc -n <ns>
kubectl get pods -n <ns> -l app=noetl
kubectl get pods -n <ns> -l app=noetl-worker
```

2) Port-forward the server and check health:
```bash
kubectl port-forward -n <ns> deploy/noetl 8084:8084
curl -s http://localhost:8084/health
```

3) Optionally port-forward a worker and test Worker API directly:
```bash
# CPU worker
kubectl port-forward -n <ns> deploy/noetl-worker-cpu 18084:8084 &

# Simple inline python task
curl -sS -X POST http://localhost:18084/api/worker/task/execute \
  -H 'Content-Type: application/json' \
  -d '{
        "task": {"type": "python", "code": "def main(x):\n    return {\"x2\": x*x}", "with": {"x": 7}},
        "context": {"env": {}},
        "requirements": []
      }'
```

4) End-to-end: register a playbook and execute via the server API (port-forward to server as above):
```bash
noetl register examples/weather/weather_example.yaml --port 8084 --host localhost
noetl execute --path "weather/weather_example" --port 8084 --host localhost --payload '{}'
```

If your playbook contains steps with names including "qpu" or "quantum", the Broker will route those tasks to the QPU worker pool by default. You can also override per-step by adding `runtime: cpu|qpu` in the step or its `with` block.
