---
title: Quantum Networking Runner (IBM API or NVIDIA Simulator)
description: Run a quantum-networking use case in NoETL with IBM Runtime API mode or NVIDIA simulator mode.
sidebar_position: 10
---

# Quantum Networking Runner

This example provides a runnable NoETL playbook for a quantum-networking baseline flow:

- Bell-state preparation and measurement
- Correlation-based quality output (`qber_estimate`) in simulator mode
- IBM Runtime job submit/poll/results in API mode

Playbook file:
- `tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml`

## Mode A: NVIDIA simulator

Default mode is `nvidia_simulator`.

Run:

```bash
noetl exec tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml -r local \
  --set provider=nvidia_simulator \
  --set shots=1024
```

Optional GPU request:

```bash
export NVIDIA_USE_GPU=true
noetl exec tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml -r local \
  --set provider=nvidia_simulator \
  --set shots=4096
```

Notes:
- If Qiskit Aer is available, the playbook executes on Aer.
- If unavailable, it falls back to an analytic Bell-state baseline so flow remains runnable.

## Mode B: IBM API

Set environment variables:

```bash
export IBM_QUANTUM_API_KEY="<your-token>"
export IBM_QUANTUM_INSTANCE_CRN="<your-instance-crn>"
export IBM_QUANTUM_BACKEND="ibm_brisbane"
```

Optional:

```bash
export IBM_QUANTUM_API_BASE="https://api.quantum.ibm.com/runtime"
export IBM_QUANTUM_API_VERSION="2024-06-13"
```

Run:

```bash
noetl exec tests/fixtures/playbooks/api_integration/quantum_networking/quantum_networking_runner.yaml -r local \
  --set provider=ibm_api
```

## Expected final result envelope

```json
{
  "status": "ok|error",
  "provider": "nvidia_simulator|ibm_api",
  "run": { "...details..." }
}
```

## References

- IBM Runtime jobs API: [IBM Jobs API](https://quantum.cloud.ibm.com/docs/en/api/qiskit-runtime-rest/tags/jobs)
- IBM migration examples (`sampler` payload): [IBM v2 primitives migration](https://quantum.cloud.ibm.com/docs/en/migration-guides/v2-primitives-api)
- NVIDIA cuQuantum appliance: [NVIDIA cuQuantum appliance overview](https://docs.nvidia.com/cuda/cuquantum/latest/appliance/overview.html)
