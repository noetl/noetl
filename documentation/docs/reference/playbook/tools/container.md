# Container Tool

## Overview

`tool: container` lets playbooks execute arbitrary shell scripts inside an ephemeral container (Kubernetes Job) while reusing the existing `script` attribute for code delivery. The worker resolves the script from any supported source (`file`, `gcs`, `s3`, `http`), mounts it into the container, and tracks execution until completion.

## DSL

```yaml
- step: run_init
  tool: container
  desc: Initialize tradetrend DB via bash script
  runtime:
    provider: kubernetes                   # required
    namespace: "{{ workload.namespace | default('noetl') }}"
    image: tradetrend/tradedb-tools:latest # required
    command: ["/bin/bash", "/workspace/script.sh"]
    args: []
    serviceAccountName: noetl-worker       # optional
    backoffLimit: 0                        # optional
    activeDeadlineSeconds: 900             # optional timeout
    cleanup: true                          # delete job+configmap afterwards
    resources:                             # optional k8s resources block
      limits:
        cpu: "1"
        memory: 1Gi
    files:
      - uri: ./scripts/tradedb/tradedb_ddl.sql
        source:
          type: file
        mountPath: tradedb_ddl.sql
      - uri: ./scripts/tradedb/create_dictionaries.sql
        source:
          type: file
        mountPath: create_dictionaries.sql
  env:
    POSTGRES_DB: "{{ workload.pg.db }}"
    POSTGRES_USER: "{{ workload.pg.user }}"
    POSTGRES_PASSWORD: "{{ workload.pg.password }}"
    TRADDB_DDL_PATH: "/workspace/tradedb_ddl.sql"
    TRADDB_DICT_PATH: "/workspace/create_dictionaries.sql"
  script:
    uri: ./scripts/tradedb/init_tradedb.sh
    source:
      type: file
```

Key fields:
- `runtime.provider`: currently `kubernetes`. Future `docker` support can reuse the same schema.
- `runtime.image`: container image that already contains required CLIs (psql, bash, etc.).
- `command`/`args`: override entrypoint; defaults to `/bin/sh /workspace/script.sh` when omitted.
- `env`: rendered key/value map merged with pod env.
- `script`: standard NoETL script schema; content is mounted as `/workspace/script.sh` (chmod 0755).
- `runtime.files`: optional list of additional artifacts fetched via the same schema as `script` (uri + source). Specify `mountPath`/`relativePath` to control the filename under `/workspace` and `mode` for chmod.

## Execution flow

1. Worker validates `runtime` + `script` sections and renders templates via `render_template`.
2. Script content resolved through `noetl.plugin.shared.script.resolve_script`.
3. Worker ensures Kubernetes credentials by loading in-cluster config first, falling back to local kubeconfig.
4. A ConfigMap stores the rendered script (and any `runtime.files`). A Kubernetes Job is created with:
   - Label `noetl.step=<step-name>` and `noetl.execution=<execution_id>`.
  - Volume mount `/workspace` (or a custom `scriptMountPath`) containing every resolved artifact.
   - User-provided env, command, args, and resources.
5. Worker polls Job status until success/failure/timeout (configurable via `activeDeadlineSeconds` and `runtime.timeoutSeconds`).
6. On completion, pod logs and exit codes are captured and surfaced in the step result; ConfigMap/Job deleted when `cleanup` is true.
7. Failures raise descriptive errors (job failed, pod image pull, deadline exceeded) which map to `status: error` and include pod logs + delivered file metadata.

## Result payload

Successful steps return:

```json
{
  "status": "success",
  "data": {
    "job_name": "noetl-run-init-1a2b3c",
    "namespace": "noetl",
    "provider": "kubernetes",
    "exit_code": 0,
    "logs": "...pod log text...",
    "start_time": "2025-11-27T14:07:12Z",
    "completion_time": "2025-11-27T14:07:33Z",
    "files": [
      {"key": "script.sh", "path": "/workspace/script.sh", "mode": 493},
      {"key": "tradedb_ddl.sql", "path": "/workspace/tradedb_ddl.sql", "mode": 420}
    ]
  }
}
```

Errors set `status: error` and include `error`, `job_name`, and the last known pod message to simplify troubleshooting.

## RBAC & bootstrap

Workers require permissions in the target namespace to manage Jobs, Pods, and ConfigMaps:

```yaml
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "get", "list", "watch", "delete"]
- apiGroups: [""]
  resources: ["pods", "pods/log", "configmaps"]
  verbs: ["create", "get", "list", "watch", "delete"]
```

The bootstrap script grants cluster-admin in Kind, but production clusters should bind a scoped Role to the NoETL service account.

## Future work

- Add `provider: docker` for local execution without Kubernetes.
- Expose pod log streams as live events for long-running jobs.

```
