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

## Best Practices

1. **Use `select` for pagination cursors** - Extract what you need without resolving full data
2. **Set appropriate TTLs** - Don't keep data longer than needed
3. **Use compression for large JSON** - Automatic when > 10KB
4. **Choose the right scope**:
   - `step` for temporary calculations
   - `execution` for shared between steps (default)
   - `workflow` for cross-playbook data
   - `permanent` for permanent storage
5. **Use `accumulate` for pagination** - Don't merge large datasets in memory
6. **Put output in tool block** - Not at step level (deprecated)

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
