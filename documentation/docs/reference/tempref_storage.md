---
sidebar_position: 15
title: TempRef Storage System
description: Zero-copy data passing between playbook steps using MCP-compatible references
---

# TempRef Storage System

The TempRef storage system provides efficient, zero-copy data passing between playbook steps. Instead of embedding large results directly in the event log, data is stored externally and only lightweight pointers (TempRefs) are passed through the workflow.

## Overview

### The Problem

Traditional result handling embeds all step outputs in the event log:
- Large API responses bloat the event table
- Copying data between steps is expensive
- Memory usage grows with result size
- Database queries slow down with large JSONB columns

### The Solution

TempRef uses a pointer-based architecture inspired by Rust's borrow semantics:
- **Store data externally** in the optimal backend (NATS KV, Object Store, S3, etc.)
- **Pass lightweight pointers** between steps
- **Resolve on demand** when data is actually needed
- **Automatic cleanup** based on scope (step, execution, workflow)

```
Step A produces large result
    ↓
Store in NATS KV → Get TempRef pointer
    ↓
Pass TempRef to Step B (tiny JSON pointer)
    ↓
Step B resolves TempRef → Get original data
    ↓
Automatic cleanup when execution completes
```

## TempRef Structure

A TempRef is an MCP-compatible pointer:

```json
{
  "kind": "temp_ref",
  "ref": "noetl://execution/123456/tmp/api_response/abc123",
  "store": "kv",
  "scope": "execution",
  "expires_at": "2026-02-01T13:00:00Z",
  "meta": {
    "content_type": "application/json",
    "bytes": 52480,
    "sha256": "abc123...",
    "compression": "gzip"
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
| `kind` | Always `"temp_ref"` |
| `ref` | Logical URI: `noetl://execution/<eid>/tmp/<name>/<id>` |
| `store` | Storage tier: `memory`, `kv`, `object`, `s3`, `gcs`, `db` |
| `scope` | Lifecycle: `step`, `execution`, `workflow` |
| `expires_at` | TTL expiration timestamp |
| `meta` | Size, hash, compression info |
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

## DSL Configuration

### Step Output Block

Add an `output:` block to any step to configure result storage:

```yaml
- step: fetch_data
  tool:
    kind: http
    endpoint: https://api.example.com/data
  output:
    store:
      kind: auto              # Auto-select tier based on size
      ttl: "1h"               # Time-to-live
      compression: gzip       # Compress stored data
    select:
      - path: "$.pagination.next"
        as: next_cursor       # Extract for immediate use
      - path: "$.data.count"
        as: total_count
    inline_max_bytes: 65536   # Store inline if smaller (64KB)
    scope: execution          # Cleanup when playbook completes
```

### Output Store Configuration

```yaml
output:
  store:
    kind: auto|memory|kv|object|s3|gcs|db
    driver: minio             # Optional: specific driver
    bucket: my-bucket         # For s3/gcs/object
    prefix: temp/             # Key prefix
    ttl: "2h"                 # Duration: 30m, 1h, 2h, 1d
    compression: none|gzip|lz4
    credential: s3_creds      # Keychain credential name
```

### Output Select (Extract Fields)

Extract specific fields without resolving the full TempRef:

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

These extracted values are available immediately in subsequent steps without needing to resolve the full TempRef.

### Output Publish (For Pagination/Loops)

For pagination or loops, publish parts and create a manifest:

```yaml
- step: fetch_all_pages
  tool:
    kind: http
    endpoint: "https://api.example.com/items?page={{ vars.page }}"
  output:
    store:
      kind: object
      ttl: "30m"
    publish:
      parts_as: pages           # Each iteration → TempRef
      combined_as: manifest     # Final manifest with all refs
      strategy: append          # How to combine: append, merge, concat
      merge_path: "$.data"      # For concat: extract this array
    select:
      - path: "$.pagination.next"
        as: has_more
```

## Scopes and Lifecycle

### Step Scope
- Data cleaned up when step completes
- Use for intermediate calculations within a step
- Lowest memory footprint

```yaml
output:
  scope: step
```

### Execution Scope (Default)
- Data cleaned up when playbook completes
- Shared across all steps in the playbook
- Most common use case

```yaml
output:
  scope: execution
```

### Workflow Scope
- Data persists across nested playbook calls
- Cleaned up when root playbook completes
- Use for data shared between parent and child playbooks

```yaml
output:
  scope: workflow
```

## Manifests for Aggregation

Instead of merging large paginated results in memory, use manifests:

```yaml
# Manifest structure
{
  "kind": "manifest",
  "ref": "noetl://execution/123/manifest/all_pages/xyz",
  "strategy": "concat",
  "merge_path": "$.data",
  "parts": [
    {"ref": "noetl://execution/123/tmp/pages/p1", "index": 0, "bytes_size": 10240},
    {"ref": "noetl://execution/123/tmp/pages/p2", "index": 1, "bytes_size": 10180},
    {"ref": "noetl://execution/123/tmp/pages/p3", "index": 2, "bytes_size": 9850}
  ],
  "total_parts": 3,
  "total_bytes": 30270
}
```

### Manifest Strategies

| Strategy | Behavior |
|----------|----------|
| `append` | Parts as a list: `[part1, part2, part3]` |
| `replace` | Each part overwrites previous |
| `merge` | Deep merge parts as objects |
| `concat` | Flatten arrays at `merge_path`: `[...part1.data, ...part2.data]` |

## REST API

### Store Data

```bash
PUT /api/temp/{execution_id}
Content-Type: application/json

{
  "name": "api_response",
  "data": {"users": [...]},
  "scope": "execution",
  "ttl_seconds": 3600
}
```

Response:
```json
{
  "ref": "noetl://execution/123/tmp/api_response/abc",
  "store": "kv",
  "scope": "execution",
  "expires_at": "2026-02-01T13:00:00Z",
  "bytes": 52480
}
```

### Retrieve Data

```bash
GET /api/temp/{execution_id}/{name}
```

### Resolve Any Ref

```bash
GET /api/temp/resolve?ref=noetl://execution/123/tmp/api_response/abc
```

### List Temps

```bash
GET /api/temp/{execution_id}/list?scope=execution
```

### Cleanup

```bash
DELETE /api/temp/{execution_id}?scope=execution
```

## Template Usage

### Access TempRef in Templates

TempRefs can be used directly in templates. They resolve lazily:

```yaml
# Previous step stored result as TempRef
- step: process_data
  args:
    # Accessing .data triggers resolution
    items: "{{ fetch_data.data }}"

    # Accessing extracted fields (no resolution needed)
    cursor: "{{ fetch_data.next_cursor }}"
```

### Check if Result is TempRef

```yaml
case:
  - when: "{{ fetch_data.kind == 'temp_ref' }}"
    then:
      # Handle large result
  - when: "{{ fetch_data.kind != 'temp_ref' }}"
    then:
      # Handle inline result
```

## Example: API Integration with Large Responses

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: large_api_example
  path: examples/large_api

workflow:
- step: start
  tool:
    kind: python
    code: |
      result = {"initialized": True}
  next:
    - step: fetch_large_data

- step: fetch_large_data
  desc: Fetch large dataset from API
  tool:
    kind: http
    endpoint: https://api.example.com/large-dataset
  output:
    store:
      kind: auto              # Will use object store for large response
      ttl: "1h"
      compression: gzip
    select:
      - path: "$.meta.total_records"
        as: total_records
      - path: "$.meta.has_more"
        as: has_more
    inline_max_bytes: 10240   # Only inline if < 10KB
  next:
    - step: process_results

- step: process_results
  desc: Process the results (resolves TempRef automatically)
  tool:
    kind: python
    args:
      # This triggers TempRef resolution
      data: "{{ fetch_large_data.data }}"
      # This uses extracted field (no resolution)
      total: "{{ fetch_large_data.total_records }}"
    code: |
      # data is the full resolved result
      # total is the extracted count
      result = {
          "processed": len(data.get('records', [])),
          "total_expected": total
      }
  next:
    - step: end

- step: end
  tool:
    kind: python
    code: |
      result = {"status": "COMPLETED"}
```

## Garbage Collection

### Automatic Cleanup

- **TTL-based**: Background sweep every 5 minutes deletes expired refs
- **Step-finalizer**: Step-scoped refs cleaned when step completes
- **Execution-finalizer**: Execution-scoped refs cleaned when playbook completes
- **Workflow-finalizer**: Workflow-scoped refs cleaned when root playbook completes

### Manual Cleanup

```bash
# Clean up specific execution
DELETE /api/temp/{execution_id}?scope=execution

# Clean up specific step
DELETE /api/temp/{execution_id}/step/{step_name}
```

## Database Schema

The system uses projection tables for metadata (actual data in NATS/cloud):

```sql
-- TempRef metadata
CREATE TABLE noetl.temp_ref (
    ref_id BIGINT PRIMARY KEY,
    ref TEXT UNIQUE NOT NULL,
    execution_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    store_tier TEXT NOT NULL,
    bytes_size BIGINT,
    expires_at TIMESTAMPTZ,
    preview JSONB
);

-- Manifest metadata
CREATE TABLE noetl.manifest (
    manifest_id BIGINT PRIMARY KEY,
    ref TEXT UNIQUE NOT NULL,
    execution_id BIGINT NOT NULL,
    strategy TEXT NOT NULL,
    total_parts INTEGER,
    total_bytes BIGINT
);
```

## Best Practices

1. **Use `select` for pagination cursors** - Extract what you need without resolving full data
2. **Set appropriate TTLs** - Don't keep data longer than needed
3. **Use compression for large JSON** - Automatic when > 10KB
4. **Choose the right scope** - Step for temporary, execution for shared, workflow for cross-playbook
5. **Use manifests for pagination** - Don't merge large datasets in memory
6. **Monitor storage usage** - Check `/api/temp/stats` for GC statistics
