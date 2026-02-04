---
sidebar_position: 15
title: Result Storage System
description: Zero-copy data passing between playbook steps using result references
---

# Result Storage System

The Result Storage system provides efficient, zero-copy data passing between playbook steps. Instead of embedding large results directly in the event log, data is stored externally and only lightweight pointers (ResultRef) are passed through the workflow.

## Overview

### The Problem

Traditional result handling embeds all step outputs in the event log:
- Large API responses bloat the event table
- Copying data between steps is expensive
- Memory usage grows with result size
- Database queries slow down with large JSONB columns

### The Solution

ResultRef uses a pointer-based architecture:
- **Store data externally** in the optimal backend (NATS KV, Object Store, S3, etc.)
- **Pass lightweight pointers** between steps
- **Resolve on demand** when data is actually needed
- **Automatic cleanup** based on scope (step, execution, workflow, permanent)

```
Tool produces result
    ↓
Store in storage tier → Get ResultRef pointer
    ↓
Pass ResultRef to next step (tiny JSON pointer)
    ↓
Next step resolves ResultRef → Get original data
    ↓
Automatic cleanup when scope ends (or never for 'permanent')
```

## ResultRef Structure

```json
{
  "kind": "result_ref",
  "ref": "noetl://execution/123456/result/fetch_data/abc123",
  "store": "kv",
  "scope": "execution",
  "expires_at": "2026-02-01T13:00:00Z",
  "meta": {
    "content_type": "application/json",
    "bytes": 52480,
    "sha256": "abc123...",
    "compression": "gzip"
  },
  "extracted": {
    "next_cursor": "page2",
    "total_count": 100
  },
  "preview": {
    "_items": 100,
    "_sample": [{"id": 1}, {"id": 2}, {"id": 3}]
  }
}
```

### Fields

| Field | Description |
|-------|-------------|
| `kind` | `"result_ref"` (or `"temp_ref"` for legacy) |
| `ref` | Logical URI: `noetl://execution/<eid>/result/<step>/<id>` |
| `store` | Storage tier: `memory`, `kv`, `object`, `s3`, `gcs`, `db` |
| `scope` | Lifecycle: `step`, `execution`, `workflow`, `permanent` |
| `expires_at` | TTL expiration timestamp (null for permanent) |
| `extracted` | Fields from output.select (available without resolution) |
| `preview` | Truncated sample for UI/debugging |

## Storage Tiers

The system automatically selects the optimal storage tier based on data size:

| Tier | Backend | Max Size | Default TTL | Use Case |
|------|---------|----------|-------------|----------|
| `memory` | In-process | 10KB | step lifetime | Hot path, step-scoped temps |
| `kv` | NATS KV | 1MB | 1 hour | Small state, tokens, cursors |
| `object` | NATS Object Store | 10MB | 30 min | Medium artifacts, page results |
| `s3` | AWS S3 / MinIO | unlimited | 2 hours | Large blobs, reports |
| `gcs` | Google Cloud Storage | unlimited | 2 hours | Large blobs, reports |
| `db` | PostgreSQL | - | 2 hours | Queryable intermediate data |

### Auto-Selection Logic

```
if size < 10KB and scope == step:
    use memory
elif size < 1MB:
    use kv
elif size < 10MB:
    use object
else:
    use s3/gcs
```

## Scopes and Lifecycle

| Scope | Description | When Cleaned |
|-------|-------------|--------------|
| `step` | Cleaned when step completes | Immediate after step |
| `execution` | Cleaned when playbook completes | End of playbook |
| `workflow` | Cleaned when root playbook completes | End of parent |
| `permanent` | Never auto-cleaned | Manual cleanup only |

### TTL Values

- Duration: `"30m"`, `"1h"`, `"2h"`, `"1d"`, `"7d"`, `"30d"`, `"1y"`
- Forever: `"permanent"` or omit TTL with scope `permanent`

## DSL Configuration

### Output at Tool Level

The `output:` block is configured inside the `tool:` block:

```yaml
- step: fetch_data
  tool:
    kind: http
    method: GET
    endpoint: https://api.example.com/data
    output:                           # Inside tool block
      store:
        kind: auto                    # Auto-select tier based on size
        ttl: "1h"                     # Time-to-live
        compression: gzip             # Compress stored data
      select:                         # Extract fields for fast access
        - path: "$.pagination.next"
          as: next_cursor
        - path: "$.data.count"
          as: total_count
      inline_max_bytes: 65536         # Store inline if smaller (64KB)
      scope: execution                # Cleanup when playbook completes
```

### Output Store Configuration

```yaml
output:
  store:
    kind: auto|memory|kv|object|s3|gcs|db
    driver: minio             # Optional: specific driver
    bucket: my-bucket         # For s3/gcs/object
    prefix: temp/             # Key prefix
    ttl: "2h"                 # Duration: 30m, 1h, 2h, 1d, permanent
    compression: none|gzip|lz4
    credential: s3_creds      # Keychain credential name
```

### Output Select (Extract Fields)

Extract specific fields without resolving the full result:

```yaml
output:
  select:
    - path: "$.pagination.nextCursor"
      as: next_cursor
    - path: "$.meta.totalItems"
      as: total
    - path: "$.data[0].id"
      as: first_id
```

These extracted values are available immediately via `{{ step_name.field_name }}`.

### Output Accumulate (For Pagination/Loops)

Automatically accumulate results during pagination or retry loops:

```yaml
- step: fetch_all_pages
  tool:
    kind: http
    endpoint: "{{ workload.api_url }}?cursor={{ vars.cursor }}"
    output:
      store:
        kind: object
        ttl: "30m"
      select:
        - path: "$.pagination.nextCursor"
          as: next_cursor
        - path: "$.pagination.hasMore"
          as: has_more
      accumulate:
        enabled: true
        strategy: concat          # append, merge, concat
        merge_path: "$.data"      # For concat: extract this array
        manifest_as: all_pages    # Access via {{ fetch_all_pages.all_pages }}
  case:
    # Continue pagination
    - when: "{{ event.name == 'call.done' and fetch_all_pages.has_more }}"
      then:
        - set:
            vars.cursor: "{{ fetch_all_pages.next_cursor }}"
        - retry:
            reason: pagination
    # Done
    - when: "{{ event.name == 'call.done' and not fetch_all_pages.has_more }}"
      then:
        - next:
            - step: process_all_data
```

### Accumulate Strategies

| Strategy | Behavior |
|----------|----------|
| `append` | Parts as a list: `[part1, part2, part3]` |
| `replace` | Each part overwrites previous |
| `merge` | Deep merge parts as objects |
| `concat` | Flatten arrays at `merge_path`: `[...part1.data, ...part2.data]` |

## Template Usage

### Access Results in Templates

```yaml
# Full result (triggers resolution)
"{{ step_name.result }}"
"{{ step_name.result.data.items }}"

# Extracted fields (no resolution needed - fast!)
"{{ step_name.next_cursor }}"
"{{ step_name.total_count }}"

# Accumulated results
"{{ step_name.accumulated }}"
"{{ step_name.all_pages }}"          # Custom manifest name

# Metadata
"{{ step_name._meta.bytes }}"
"{{ step_name._meta.store }}"
"{{ step_name._ref }}"               # Raw reference URI
```

### Tool Chains in then: Blocks

When chaining tools in a `then:` block, use `_prev` to access the previous tool's result:

```yaml
- step: api_call
  tool:
    kind: http
    endpoint: https://api.example.com/data
  case:
    - when: "{{ event.name == 'call.done' and response.status_code == 200 }}"
      then:
        - tool:
            kind: python
            args:
              data: "{{ _prev.result }}"    # Result from previous tool (http)
            code: |
              result = {"processed": len(data.get('items', []))}
            output:
              as: processed_data            # Name for this interim result
        - tool:
            kind: postgres
            auth: "{{ workload.pg_auth }}"
            command: |
              INSERT INTO results (data) VALUES ($1)
            params:
              - "{{ _prev.result }}"        # Result from previous tool
        - next:
            - step: done
```

The `_prev` context is available for any tool type and always contains the result from the immediately preceding tool in the chain.

## REST API

### Store Result

```bash
PUT /api/result/{execution_id}
Content-Type: application/json

{
  "name": "api_response",
  "data": {"users": [...]},
  "scope": "execution",
  "ttl": "1h"
}
```

Response:
```json
{
  "ref": "noetl://execution/123/result/api_response/abc",
  "store": "kv",
  "scope": "execution",
  "expires_at": "2026-02-01T13:00:00Z",
  "bytes": 52480
}
```

### Retrieve Result

```bash
GET /api/result/{execution_id}/{step_name}
```

### Resolve Any Ref

```bash
GET /api/result/resolve?ref=noetl://execution/123/result/api_response/abc
```

### List Results

```bash
GET /api/result/{execution_id}/list?scope=execution
```

### Cleanup

```bash
DELETE /api/result/{execution_id}?scope=execution
```

## Example: API Integration with Result Storage

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: api_integration_example
  path: examples/api_integration

workload:
  api_url: https://api.example.com
  pg_auth: pg_k8s

workflow:
- step: start
  tool:
    kind: python
    code: |
      result = {"initialized": True}
  next:
    - step: fetch_data

- step: fetch_data
  desc: Fetch data from API
  tool:
    kind: http
    method: GET
    endpoint: "{{ workload.api_url }}/data"
    output:
      store:
        kind: auto
        ttl: "1h"
        compression: gzip
      select:
        - path: "$.meta.total_records"
          as: total_records
        - path: "$.pagination.hasMore"
          as: has_more
      inline_max_bytes: 10240
  next:
    - step: process_results

- step: process_results
  desc: Process the results
  tool:
    kind: python
    args:
      # Full result (triggers resolution)
      data: "{{ fetch_data.result }}"
      # Extracted field (no resolution)
      total: "{{ fetch_data.total_records }}"
    code: |
      result = {
          "processed": len(data.get('records', [])),
          "total_expected": total
      }
  next:
    - step: store_results

- step: store_results
  desc: Store results in database
  tool:
    kind: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      INSERT INTO processed_data (execution_id, result)
      VALUES ('{{ job.uuid }}', $1::jsonb)
    params:
      - "{{ process_results | tojson }}"
    output:
      scope: permanent              # Permanent storage
      ttl: "permanent"
  next:
    - step: end

- step: end
  tool:
    kind: python
    code: |
      result = {"status": "COMPLETED"}
```

## Migration from Sink

If you have playbooks using the deprecated `sink:` mechanism:

1. Move `sink:` logic into `tool:` with `output:` configuration
2. Use `ttl: "permanent"` for permanent storage
3. Use `accumulate:` for pagination instead of manual manifest building

Before (deprecated):
```yaml
- step: fetch_data
  tool:
    kind: http
    endpoint: https://api.example.com/data
  sink:
    kind: postgres
    ...
```

After (recommended):
```yaml
- step: fetch_data
  tool:
    kind: http
    endpoint: https://api.example.com/data
    output:
      store:
        kind: db
        ttl: "permanent"
      select:
        - path: "$.data"
          as: data
```

## Worker-Side Result Handling (output_select Pattern)

For horizontal scaling with multiple workers, results are processed on the worker side using the `output_select` pattern. This allows large results to be stored externally while keeping small extracted fields available for templating in subsequent steps.

> **Note**: This pattern is the foundation of the [Rendering Optimization Architecture](#rendering-optimization-architecture), which ensures full result data never flows through the server's render context.

### Step-Level Result Configuration

Use `result:` at the step level (alongside `tool:`) to configure result storage:

```yaml
- step: fetch_large_data
  tool:
    kind: python
    args:
      count: 1000
    code: |
      items = [{"id": i, "data": "x" * 1000} for i in range(count)]
      result = {
          "status": "ok",
          "count": len(items),
          "total_bytes": count * 1000,
          "items": items
      }
  result:
    # Storage configuration
    store:
      kind: auto          # auto, kv, object, s3, gcs
    # Fields to extract for templating (available without loading full data)
    output_select:
      - status
      - count
      - total_bytes
  next:
    - step: use_extracted_fields
```

### How It Works

1. **Tool executes** and produces a result
2. **Size check**: If result > 64KB (configurable), it's externalized
3. **Storage**: Data stored in selected tier (NATS KV, Object Store, GCS, etc.)
4. **Extraction**: Fields from `output_select` are extracted and kept inline
5. **Reference**: A `_ref` pointer is created for lazy loading
6. **Next step**: Can access extracted fields directly, load full data via `artifact.get`

### Accessing Externalized Results

```yaml
# In the next step - extracted fields are available directly
- step: use_extracted_fields
  tool:
    kind: python
    args:
      # These come from output_select - no full data load needed!
      status: "{{ fetch_large_data.status }}"
      count: "{{ fetch_large_data.count }}"
      # Check if result was externalized
      was_externalized: "{{ fetch_large_data._ref is defined }}"
      # Access the storage tier used
      storage_tier: "{{ fetch_large_data._store | default('inline') }}"
    code: |
      result = {
          "status_received": status,
          "count_received": count,
          "externalized": was_externalized,
          "tier": storage_tier
      }
```

### Lazy Loading Full Data

When you need the full data, use the `artifact.get` tool:

```yaml
- step: load_full_data
  tool:
    kind: artifact
    action: get
    args:
      result_ref: "{{ fetch_large_data._ref }}"
  next:
    - step: process_loaded_data

- step: process_loaded_data
  tool:
    kind: python
    args:
      # Now we have full access to items
      items: "{{ load_full_data.items }}"
      count: "{{ load_full_data.count }}"
    code: |
      result = {"processed_items": len(items)}
```

## Cloud Storage Configuration

### Google Cloud Storage (GCS)

#### Environment Variables

Configure in `configmap-worker.yaml`:

```yaml
# GCS configuration
NOETL_GCS_BUCKET: "noetl-demo-output"
NOETL_GCS_PREFIX: "results/"
```

#### Credentials Setup

1. **Create a GCS service account** with Storage Object Admin permissions
2. **Create Kubernetes secret** with the service account key:

```bash
# Extract service account JSON and create secret
kubectl create secret generic gcs-credentials \
  --from-file=gcs-key.json=/path/to/service-account.json \
  -n noetl
```

3. **Mount in worker deployment** (`worker-deployment.yaml`):

```yaml
spec:
  containers:
    - name: worker
      env:
        - name: GOOGLE_APPLICATION_CREDENTIALS
          value: /etc/gcs/gcs-key.json
      volumeMounts:
        - name: gcs-credentials
          mountPath: /etc/gcs
          readOnly: true
  volumes:
    - name: gcs-credentials
      secret:
        secretName: gcs-credentials
```

#### Explicit GCS Storage

Force GCS storage for a step:

```yaml
- step: store_in_gcs
  tool:
    kind: python
    code: |
      # Generate large result
      result = {"items": [{"id": i, "data": "x" * 1000} for i in range(5000)]}
  result:
    store:
      kind: gcs              # Explicitly use GCS
    output_select:
      - status
```

### AWS S3 / MinIO

#### Environment Variables

```yaml
# S3/MinIO configuration
NOETL_S3_BUCKET: "noetl-results"
NOETL_S3_REGION: "us-east-1"
S3_ENDPOINT_URL: ""          # Set for MinIO (e.g., "http://minio:9000")
AWS_ACCESS_KEY_ID: "..."     # Or use IAM roles
AWS_SECRET_ACCESS_KEY: "..."
```

### Storage Tier Configuration

```yaml
# Global settings in configmap
NOETL_INLINE_MAX_BYTES: "65536"     # 64KB threshold for externalization
NOETL_PREVIEW_MAX_BYTES: "1024"     # 1KB preview size
NOETL_DEFAULT_STORAGE_TIER: "kv"    # Default tier: kv, object, s3, gcs
```

## Working Example: Storage Tiers Test

This playbook tests all storage tiers with different data sizes:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test_storage_tiers
  path: tests/storage_tiers_test
  description: Test storage tier auto-selection based on result size

workload:
  inline_items: 100       # ~5KB - stays inline
  kv_items: 500           # ~100KB - NATS KV
  object_items: 2000      # ~2MB - NATS Object Store
  large_items: 5000       # ~15MB - GCS/S3

workflow:
  # Step 1: Inline storage (< 64KB)
  - step: start
    tool:
      kind: python
      args:
        count: "{{ workload.inline_items }}"
      code: |
        items = [{"id": i, "data": "x" * 50} for i in range(count)]
        result = {"status": "ok", "tier": "inline", "count": len(items), "items": items}
    result:
      output_select:
        - status
        - tier
        - count
    next:
      - step: test_kv

  # Step 2: NATS KV (64KB - 1MB)
  - step: test_kv
    tool:
      kind: python
      args:
        count: "{{ workload.kv_items }}"
      code: |
        items = [{"id": i, "data": "K" * 200} for i in range(count)]
        result = {"status": "ok", "tier": "kv_expected", "count": len(items), "items": items}
    result:
      output_select:
        - status
        - tier
        - count
    next:
      - step: test_object

  # Step 3: NATS Object Store (1MB - 10MB)
  - step: test_object
    tool:
      kind: python
      args:
        count: "{{ workload.object_items }}"
      code: |
        items = [{"id": i, "data": "O" * 1000} for i in range(count)]
        result = {"status": "ok", "tier": "object_expected", "count": len(items), "items": items}
    result:
      output_select:
        - status
        - tier
        - count
    next:
      - step: test_gcs

  # Step 4: GCS (> 10MB)
  - step: test_gcs
    tool:
      kind: python
      args:
        count: "{{ workload.large_items }}"
      code: |
        items = [{"id": i, "data": "G" * 3000} for i in range(count)]
        result = {"status": "ok", "tier": "gcs_expected", "count": len(items), "items": items}
    result:
      output_select:
        - status
        - tier
        - count
    next:
      - step: verify

  # Step 5: Verify storage tiers
  - step: verify
    tool:
      kind: python
      args:
        inline_store: "{{ start._store | default('inline') }}"
        kv_store: "{{ test_kv._store }}"
        object_store: "{{ test_object._store }}"
        gcs_store: "{{ test_gcs._store }}"
      code: |
        result = {
            "inline_correct": inline_store == "inline" or "_store" not in dir(),
            "kv_correct": kv_store == "kv",
            "object_correct": object_store == "object",
            "gcs_correct": gcs_store in ("gcs", "s3", "object"),
            "all_passed": True  # Simplified
        }
```

## Inspecting Stored Data

### NATS KV Store

```bash
# List keys
nats --server nats://noetl:noetl@localhost:30422 kv ls noetl_result_store

# View a key (decompressed)
nats --server nats://noetl:noetl@localhost:30422 kv get noetl_result_store <key> --raw | gzip -d | jq .
```

### NATS Object Store

```bash
# List objects
nats --server nats://noetl:noetl@localhost:30422 object ls noetl_result_objects

# Download and view
nats --server nats://noetl:noetl@localhost:30422 object get noetl_result_objects <name> -O /tmp/data.gz
gzip -dc /tmp/data.gz | jq .
```

### Google Cloud Storage

```bash
# List objects
gsutil ls gs://noetl-demo-output/results/

# View object (compressed JSON)
gsutil cat gs://noetl-demo-output/results/<key> | gzip -d | jq .
```

### JetStream Statistics

```bash
# Overall stats via HTTP monitoring
curl -s 'http://localhost:30822/jsz?streams=1' | jq '.account_details[0].stream_detail[] | {name, messages: .state.messages, bytes: .state.bytes}'
```

## Storage Format

All externalized data is stored as **gzip-compressed JSON**:

- **Format**: gzip + JSON (magic bytes: `1f8b`)
- **Compression**: Automatic for data > 10KB
- **Typical ratio**: 10:1 to 100:1 for repetitive data

Example:
```
Original: 2,090,971 bytes (~2 MB)
Compressed: 11,901 bytes (~12 KB)
Ratio: 175:1
```

## Rendering Optimization Architecture

The system is designed to avoid heavy server load during template rendering by ensuring full result data never enters the render context.

### The Problem with Traditional Rendering

Without optimization, each template render would need to load full result data:

```
Step produces 2MB result
    ↓
Worker sends 2MB to server
    ↓
Server stores 2MB in step_results
    ↓
Each render loads 2MB into context
    ↓
Memory bloat + slow rendering
```

### Optimized Data Flow

With the externalization pattern, only small metadata flows through the system:

```
Tool produces 2MB result
    ↓
Worker: ResultHandler detects size > 64KB
    ↓
Worker: Stores full data in GCS/NATS Object Store
    ↓
Worker: Extracts small fields (status, count, etc.)
    ↓
Worker sends ~200 bytes to server: {_ref, _store, status, count}
    ↓
Server stores only metadata in step_results
    ↓
Render context has only lightweight data
    ↓
Fast rendering, no memory bloat
```

### Implementation Details

#### 1. Worker-Side Result Processing

The worker processes results through `ResultHandler` before sending events:

```python
# In v2_worker_nats.py
result_handler = ResultHandler(execution_id=execution_id)
processed_response = await result_handler.process_result(
    step_name=step,
    result=response,
    output_config=tool_config.get("result", {})
)

# If externalized, only metadata is sent
if is_result_ref(processed_response):
    response_for_events = processed_response  # {_ref, _store, status, count}
else:
    response_for_events = response  # Small result, sent inline
```

#### 2. Events Contain Only Metadata

Events sent to the server use the processed (externalized) version:

```python
# call.done event - only metadata
await self._emit_event(..., "call.done", {"response": response_for_events})

# step.exit event - only metadata
await self._emit_event(..., "step.exit", {"result": response_for_events})
```

#### 3. Engine Stores Lightweight Data

The engine receives and stores only the externalized version:

```python
# In engine.py
response_data = event.payload.get("response", event.payload)
state.step_results[step_name] = response_data  # Only {_ref, _store, status, count}
```

#### 4. Render Context Is Lightweight

When building render context, only small metadata is included:

```python
# In engine.py
context = {
    "workload": self.variables,
    "vars": self.variables,
    **self.step_results,  # Only lightweight metadata, not full data
}
```

### Template Access Patterns

| Access Pattern | Data Source | Memory Load | Speed |
|---------------|-------------|-------------|-------|
| `{{ step.status }}` | Extracted field | ~50 bytes | Instant |
| `{{ step.count }}` | Extracted field | ~10 bytes | Instant |
| `{{ step._ref }}` | Metadata | ~200 bytes | Instant |
| `{{ step._store }}` | Metadata | ~10 bytes | Instant |
| `{{ step._preview }}` | Truncated sample | ~1KB | Instant |
| `{{ step.items }}` | **Not available** | N/A | Use `artifact.get` |

### When Full Data Is Needed

For steps that need access to full externalized data, use the `artifact.get` tool:

```yaml
# Step 1: Produces large result (externalized automatically)
- step: fetch_data
  tool:
    kind: python
    code: |
      result = {"items": [{"id": i} for i in range(100000)]}
  result:
    output_select:
      - status
  next:
    - step: process_metadata

# Step 2: Works with extracted fields only (no full data load)
- step: process_metadata
  tool:
    kind: python
    args:
      status: "{{ fetch_data.status }}"    # Available instantly
      ref: "{{ fetch_data._ref }}"          # Pointer to full data
    code: |
      result = {"status_received": status, "has_ref": ref is not None}
  next:
    - step: load_full_data

# Step 3: Explicitly load full data when needed
- step: load_full_data
  tool:
    kind: artifact
    action: get
    args:
      result_ref: "{{ fetch_data._ref }}"
  next:
    - step: process_items

# Step 4: Now has access to full data
- step: process_items
  tool:
    kind: python
    args:
      items: "{{ load_full_data.items }}"  # Full data available
    code: |
      result = {"processed": len(items)}
```

### Performance Benefits

| Metric | Without Optimization | With Optimization |
|--------|---------------------|-------------------|
| Event payload size | 2MB+ per step | ~200 bytes |
| Memory per execution | O(n × result_size) | O(n × metadata_size) |
| Render context build | Load all results | Reference only |
| Template evaluation | Slow (large dicts) | Fast (small dicts) |
| Horizontal scaling | Limited by memory | Scales linearly |

### Thresholds and Configuration

```yaml
# In configmap-worker.yaml
NOETL_INLINE_MAX_BYTES: "65536"     # 64KB - externalize if larger
NOETL_PREVIEW_MAX_BYTES: "1024"     # 1KB preview for UI
```

Results smaller than `INLINE_MAX_BYTES` are passed inline (no externalization).
Results larger are externalized with only extracted fields kept inline.

## Best Practices

1. **Use `output_select` for fields needed in templates** - Extract what you need without resolving full data
2. **Set appropriate TTLs** - Don't keep data longer than needed
3. **Use compression for large JSON** - Automatic when > 10KB
4. **Choose the right scope**:
   - `step` for temporary calculations
   - `execution` for shared between steps (default)
   - `workflow` for cross-playbook data
   - `permanent` for permanent storage
5. **Use `accumulate` for pagination** - Don't merge large datasets in memory
6. **Use step-level `result:` for worker-side processing** - Enables horizontal scaling
7. **Lazy load with `artifact.get`** - Only load full data when actually needed

## Garbage Collection

### Automatic Cleanup

- **TTL-based**: Background sweep every 5 minutes deletes expired refs
- **Step-finalizer**: Step-scoped refs cleaned when step completes
- **Execution-finalizer**: Execution-scoped refs cleaned when playbook completes
- **Workflow-finalizer**: Workflow-scoped refs cleaned when root playbook completes
- **Forever scope**: Never auto-cleaned - delete manually or via API

### Manual Cleanup

```bash
# Clean up specific execution
DELETE /api/result/{execution_id}?scope=execution

# Clean up specific step
DELETE /api/result/{execution_id}/step/{step_name}
```

## Example Playbooks

Working test playbooks are available in the repository:

| Playbook | Path | Description |
|----------|------|-------------|
| `test_storage_tiers.yaml` | `tests/fixtures/playbooks/test_storage_tiers.yaml` | Tests all storage tier auto-selection |
| `test_gcs_storage.yaml` | `tests/fixtures/playbooks/test_gcs_storage.yaml` | Tests explicit GCS storage |
| `test_output_select.yaml` | `tests/fixtures/playbooks/test_output_select.yaml` | Tests output_select pattern with lazy loading |
| `test_large_result_extraction.yaml` | `tests/fixtures/playbooks/test_large_result_extraction.yaml` | Tests large result externalization |

### Running Test Playbooks

```bash
# Register playbook
noetl catalog register tests/fixtures/playbooks/test_storage_tiers.yaml

# Execute
curl -X POST 'http://localhost:8082/api/execute' \
  -H 'Content-Type: application/json' \
  -d '{"path": "tests/storage_tiers_test"}'

# Check status
noetl status <execution_id> --json | jq '.variables.final_summary'
```

## Database Schema

The system uses projection tables for metadata (actual data in NATS/cloud):

```sql
-- ResultRef metadata (renamed from temp_ref)
CREATE TABLE noetl.result_ref (
    ref_id BIGINT PRIMARY KEY,
    ref TEXT UNIQUE NOT NULL,
    execution_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('step', 'execution', 'workflow', 'permanent')),
    store_tier TEXT NOT NULL,
    bytes_size BIGINT,
    expires_at TIMESTAMPTZ,
    extracted JSONB,
    preview JSONB,
    is_accumulated BOOLEAN DEFAULT FALSE,
    accumulation_index INTEGER,
    accumulation_manifest_ref TEXT
);
```
