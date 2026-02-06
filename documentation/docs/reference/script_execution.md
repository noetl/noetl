---
sidebar_position: 14
title: Script Loading and Script Jobs (Canonical v10)
description: Unified specification for external script loading (script attribute) and Kubernetes job-based script execution (script tool kind) — Canonical v10
---

# Script Loading and Script Jobs (Canonical v10)

This document consolidates and replaces the prior **Script Attribute** and **Script Tool** documents and aligns them to the **Canonical v10** execution model.

Canonical alignment:
- Playbook root sections are `metadata`, `keychain` (optional), `executor` (optional), `workload`, `workflow`, `workbook` (optional)
- A step is `spec.policy` (admission/lifecycle) + `tool` (ordered pipeline) + `next` (router with arcs)
- Each pipeline item is a **tool task** with `kind` and optional `spec`
- Auth material is resolved **at runtime** by workers (credential caching + refresh); playbooks reference credential names only
- Results are **reference-first**; large outputs should be stored externally and referenced
- No legacy `eval`/`expr` or step-level `case`

> This document describes two related capabilities:
> 1) **External script loading** for tools that support code/queries/templates (the `script` attribute)  
> 2) **Isolated script execution as a Kubernetes Job** (the `script` tool kind)

---

## 1) Conceptual overview

### 1.1 “Script” as a code source
Many tools accept code-like inputs:
- Python code
- SQL queries
- request templates
- transformation logic

Canonical v10 supports providing that code from:
- inline fields (tool-specific)
- encoded fields (tool-specific)
- external locations via a common `script` descriptor

### 1.2 “Script tool” as an execution environment
Some workloads require isolation, resource control, and dependency packaging. For those, Canonical v10 supports a dedicated tool kind:

- `kind: script` — runs a script as an isolated Kubernetes Job, with resource policies and controlled environment injection.

These are separate concepts:
- `script:` **loads code**
- `kind: script` **runs code in a job**

---

## 2) Placement in the canonical step pipeline

In Canonical v10, steps execute an ordered pipeline:

- `step.tool` is a list of named tasks
- Each task has `kind` and tool-specific configuration
- Task outcome handling is expressed via **policy rules**: `task.spec.policy.rules` (`when` → `then.do`)

This document only defines the script-related configuration surfaces. It does not change pipeline semantics.

---

## 3) External script loading: `script` attribute

### 3.1 Purpose
The `script` attribute lets a tool load its executable code/query/template from an external source (object store, HTTP, filesystem). This is useful for:
- reusing versioned scripts without embedding them in playbooks
- separating orchestration from code artifacts
- supporting multi-cloud script repositories

### 3.2 Applicability
A tool kind MAY support `script` if it accepts code-like input. Typical kinds include:
- `python` (code)
- `postgres` / `duckdb` (SQL)
- other query-like tools (implementation-defined)
- templated tools (implementation-defined)

### 3.3 Script resolution precedence
If a tool supports multiple code sources, the canonical precedence is:

1. `script` (external) — highest priority  
2. encoded fields (tool-specific)  
3. inline fields (tool-specific) — lowest priority

If none are provided, the tool behavior is tool-specific (often an error).

### 3.4 Script descriptor fields
The `script` object contains:
- `uri` — location of the script artifact
- `source` — resolver configuration

`source` contains:
- `type` — one of: `gcs`, `s3`, `http`, `file` (extensible)
- `auth` — credential reference name (optional, depends on source type)
- transport options — timeouts, headers, region, etc. (type-specific)

### 3.5 Source types

#### a) Object storage (GCS/S3)
- `uri` uses a scheme such as `gs://...` or `s3://...`
- `source.auth` references a credential name used to access the bucket/object
- workers resolve credentials at runtime (caching + refresh)
- downloaded content may be cached locally by workers (implementation-defined)

#### b) HTTP/HTTPS
- `source.endpoint` + `uri` or a full URL (implementation-defined)
- `source.headers` may be present
- for Authorization headers, prefer referencing credentials (runtime injects material) rather than embedding tokens

#### c) Local filesystem
- `uri` is a relative or absolute path
- used for local dev and controlled worker images
- production deployments should prefer object storage or artifact registries

### 3.6 Security requirements (MUST)
- Script artifacts MUST be treated as untrusted input unless verified.
- The runtime SHOULD support integrity checks (checksum/signature) when configured.
- Credentials used to fetch scripts MUST NOT be logged or returned in outputs.
- Script content should not be persisted into the event log; store only references and integrity metadata.

---

## 4) Kubernetes Job execution: `kind: script`

### 4.1 Purpose
The `script` tool kind runs a script inside a dedicated Kubernetes Job, enabling:
- isolated execution per invocation
- CPU/memory limits and timeouts
- dependency control through container images
- standardized logging collection
- bounded retry policies

### 4.2 Inputs
A `kind: script` task typically includes:
- `script` — where to fetch the script artifact (same descriptor as above)
- `args` — JSON-like arguments passed to the job (runtime-defined mechanism)
- `job` / `spec` — Kubernetes execution policy

### 4.3 Job policy fields (conceptual)
Common job policy knobs include:
- container image reference
- namespace
- resource requests/limits
- deadline/timeout
- retry/backoff limit
- TTL cleanup after completion
- environment variables (see credential handling below)

These fields may be placed under `spec` (canonical policy container).

### 4.4 Credential injection (canonical)
Jobs often need cloud/database credentials. Canonical v10 requires:
- playbooks reference credential names, not secret values
- workers materialize credentials and inject them into the job environment securely
- tokens are refreshed according to runtime policy (threshold-based)

Recommended approach:
- `env` entries are declared as *bindings* to credential references or workload values
- the worker resolves and injects values at runtime
- the event log records only metadata (no secret bytes)

### 4.5 Outputs and result references
Job outputs can be large (logs, artifacts, produced datasets). Canonical v10 recommends:
- store large outputs externally (object store, DB)
- return a ResultRef describing the stored location
- include only minimal metadata in events and pipeline outcomes

---

## 5) Retry and failure handling

### 5.1 Task policy applies
Both external script loading and job execution produce task outcomes. Retry is expressed via task policy rules, for example:
- retry on transient fetch failures (timeouts, 429/5xx)
- retry on transient job failures (node preemption, image pull transient)
- fail fast on permanent errors (permission denied, invalid script)

### 5.2 Job retry vs task retry
There are two retry layers (implementation-defined but recommended):
- **Job retry** (Kubernetes backoff limit) — retries inside the cluster job controller
- **Task retry** (NoETL `then.do: retry`) — reruns the task from the worker perspective

Canonical guidance:
- Use Kubernetes retry for quick transient pod failures.
- Use NoETL task retry for higher-level policy (backoff, jitter, cross-node rescheduling) and for script download failures.
- Ensure idempotency when retries can re-run the same script.

---

## 6) Observability

The runtime should emit events for:
- script fetch started/completed (metadata only)
- job created, running, completed/failed
- captured logs references (not necessarily full logs)
- timing metrics and resource usage summaries (if available)

Avoid embedding raw logs into events when large; store and reference.

---

## 7) Recommended usage patterns

### 7.1 Small logic: use native tools + `script`
If you just need versioned code/query templates, use the native tool kind (`python`, `postgres`, etc.) with `script` to load external code.

### 7.2 Heavy workloads: use `kind: script`
If you need isolation, heavy dependencies, GPUs, or strong resource controls, use the `script` tool kind to run a Kubernetes Job.

### 7.3 Keep orchestration separate from artifacts
Use object storage paths that incorporate:
- playbook version
- script semantic version
- environment (dev/stage/prod)

---

## 8) Migration notes (from legacy docs)

- Replace step-level `tool: python` shorthand with canonical pipeline tasks under `step.tool`.
- Treat `script` as a **tool task attribute**, not a separate top-level mechanism.
- Prefer referencing credentials by name (e.g., `auth: pg_k8s`, root `keychain` declarations) over embedding secret bytes into templated strings. If you template `keychain.*` values into headers, ensure the runtime redacts inputs in events/logs.
- Keep script content out of events; store references + integrity metadata.

---

## See also
- Credential caching: `credential_caching_v2.md`
- Token refresh: `keychain_token_refresh_v2.md`
- Result storage (reference-first): `result_storage_canonical_v10.md`
- Pipeline execution: `pipeline_execution_v2.md`
