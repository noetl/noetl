---
sidebar_position: 6
title: Container Tool (Canonical v10)
description: Run scripts in Kubernetes Jobs as pipeline tasks (Canonical v10)
---

# Container Tool (Canonical v10)

The `container` tool runs a script in an isolated Kubernetes Job. Use it as a pipeline task (`kind: container`) inside `step.tool`.

Canonical reminders:
- Use `when` only (no legacy `eval`/`expr`/`case`).
- Task control flow belongs to `task.spec.policy.rules` (`retry|jump|break|fail|continue`).
- Step routing belongs to `step.next` router arcs.

---

## Basic usage

```yaml
- step: run_job
  tool:
    - job:
        kind: container
        runtime:
          provider: kubernetes
          image: python:3.11-slim
          namespace: noetl
          timeoutSeconds: 900
          env:
            API_URL: "{{ workload.api_url }}"
        script:
          uri: gs://my-bucket/scripts/job.sh
          source:
            type: gcs
            auth: gcp_service_account
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

> The container tool uses the canonical `script` descriptor (`uri` + `source`). See `documentation/docs/reference/script_execution_v2.md`.

---

## Common fields (conceptual)

| Field | Meaning |
|---|---|
| `runtime.image` | Container image |
| `runtime.namespace` | Kubernetes namespace |
| `runtime.command` / `runtime.args` | Command override (default runs the resolved script) |
| `runtime.env` | Environment variables (templated) |
| `runtime.timeoutSeconds` | Job deadline |
| `runtime.serviceAccountName` | ServiceAccount name |
| `runtime.cleanup` | Whether to clean up Job/ConfigMap artifacts |
| `runtime.files[]` | Additional file descriptors to deliver (same shape as `script`) |
| `script` | Script descriptor (required) |

---

## See also
- Script loading / script jobs: `documentation/docs/reference/script_execution_v2.md`
- Result storage (reference-first): `documentation/docs/reference/result_storage_canonical_v10.md`
