# Quantum Networking Runner (NoETL)

This playbook provides a runnable NoETL use case for quantum networking with two modes:

- `nvidia_simulator`: local Bell-state simulation using Qiskit Aer (with analytic fallback if Aer is unavailable)
- `ibm_api`: IBM Quantum Runtime REST submission/polling/results flow

File:
- `tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml`

## What it runs

The playbook executes a simple Bell-state workflow relevant to quantum networking:

- Creates a Bell-state circuit pattern (`H` + `CX` + measurement)
- Produces correlated measurement outcomes (`00` / `11` baseline)
- Reports a `qber_estimate` in simulator mode
- In IBM mode, submits a Runtime `sampler` job and retrieves status/results

## Quick run (local NoETL)

```bash
noetl exec tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml -r local
```

Default provider is `nvidia_simulator`.

## Mode 1: NVIDIA simulator path

### Optional dependencies

If you want real simulator execution instead of fallback:

```bash
pip install qiskit qiskit-aer
```

### Run commands

CPU/default device:

```bash
noetl exec tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml -r local \
  --set provider=nvidia_simulator \
  --set shots=1024
```

Request GPU device in Aer:

```bash
export NVIDIA_USE_GPU=true
noetl exec tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml -r local \
  --set provider=nvidia_simulator \
  --set shots=4096
```

Notes:
- If GPU mode is unsupported by the installed backend, the playbook records the reason and continues.
- If Qiskit/Aer is not installed, the playbook uses an analytic Bell-state fallback so the flow is still runnable.

## Mode 2: IBM Quantum Runtime API path

### Required environment variables

```bash
export IBM_QUANTUM_API_KEY="<your-ibm-token>"
export IBM_QUANTUM_INSTANCE_CRN="<your-instance-crn>"
export IBM_QUANTUM_BACKEND="ibm_brisbane"
```

Optional:

```bash
export IBM_QUANTUM_API_BASE="https://api.quantum.ibm.com/runtime"
export IBM_QUANTUM_API_VERSION="2024-06-13"
```

### Run command

```bash
noetl exec tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml -r local \
  --set provider=ibm_api
```

The playbook performs:
- `POST {IBM_QUANTUM_API_BASE}/jobs`
- `GET  {IBM_QUANTUM_API_BASE}/jobs/{id}` (poll)
- `GET  {IBM_QUANTUM_API_BASE}/jobs/{id}/results`

## Output shape

Final step returns:

```json
{
  "status": "ok|error",
  "provider": "nvidia_simulator|ibm_api",
  "run": { "...provider-specific details..." }
}
```

## Troubleshooting

### `status=error` with IBM mode
- Verify `IBM_QUANTUM_API_KEY` and `IBM_QUANTUM_INSTANCE_CRN` are set.
- Verify backend name is valid for your instance.
- Inspect `run.response` and `run.http_status` in the returned payload.

### `mode=analytic_fallback` in simulator mode
- Install `qiskit` and `qiskit-aer` if you want backend-executed simulation.
- Keep fallback for CI/local smoke tests where quantum packages are unavailable.

## References

- IBM Quantum Runtime REST jobs API (submit/poll/results):
  - https://quantum.cloud.ibm.com/docs/en/api/qiskit-runtime-rest/tags/jobs
- IBM migration examples with `sampler` + OpenQASM payload:
  - https://quantum.cloud.ibm.com/docs/en/migration-guides/v2-primitives-api
- NVIDIA cuQuantum Appliance (Qiskit/Cirq support):
  - https://docs.nvidia.com/cuda/cuquantum/latest/appliance/overview.html
