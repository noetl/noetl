---
sidebar_position: 5
title: Artifact Tool (Canonical v10)
description: Load/store externally stored results referenced by ResultRef/TempRef (Canonical v10)
---

# Artifact Tool (Canonical v10)

The `artifact` tool loads (and optionally stores) externally stored results referenced by **ResultRef/TempRef**.

Use it when a prior step/task externalized a large output and you need the full body in a downstream step.

Canonical reminders:
- Prefer **reference-first** results for large payloads.
- Keep secrets out of event logs and out of `ctx`/`iter`.
- Handle control flow via `task.spec.policy.rules` and server routing via `step.next.arcs[]`.

---

## Basic usage (load)

```yaml
- step: load_large_output
  tool:
    - load:
        kind: artifact
        action: get
        result_ref: "{{ ctx.some_result_ref }}"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

You can also load directly by `uri`:

```yaml
- load:
    kind: artifact
    action: get
    uri: "gs://my-bucket/results/run-123/output.json.gz"
    credential: gcp_service_account
```

---

## Actions

### `action: get`

Inputs (one of):
- `result_ref` (string or ResultRef/TempRef object)
- `uri` (string)

Optional:
- `credential` (string) for cloud URIs (S3/GCS)

Common URI schemes:
- `noetl://...` (ResultStore)
- `nats-kv://...`
- `nats-obj://...`
- `s3://...`
- `gs://...`
- `eventlog://...`
- `file://...` (or plain paths)

Outputs (tool result; wrapper depends on runtime):
- `data` (parsed JSON when possible, otherwise string)
- `uri`
- `size_bytes`
- `compressed`

### `action: put` (optional)

Store `data` to a target `uri` and return metadata:

```yaml
- store:
    kind: artifact
    action: put
    uri: "gs://my-bucket/exports/report.json.gz"
    credential: gcp_service_account
    compress: true
    data: "{{ ctx.report }}"
```

---

## See also
- Result storage model: `documentation/docs/reference/result_storage_canonical_v10.md`
- ResultRef / TempRef: `documentation/docs/reference/tempref_storage.md`
