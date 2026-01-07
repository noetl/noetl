# DuckLake Tool - Distributed DuckDB with PostgreSQL Metastore

## Overview

The `ducklake` tool provides distributed DuckDB execution with a PostgreSQL-backed metastore, solving the file locking issues that occur when multiple workers access the same DuckDB files.

## Problem It Solves

**Standard DuckDB** (`tool: duckdb`):
- Uses file-based storage with exclusive locks
- Multiple workers cannot access the same database file simultaneously
- Results in "Conflicting lock is held" errors in distributed environments
- Requires workarounds like non-pooled connections (slower performance)

**DuckLake** (`tool: ducklake`):
- Uses PostgreSQL to store catalog metadata
- Multiple workers can safely read/write concurrently
- Supports connection pooling (better performance)
- Provides ACID transactions and snapshot isolation
- Enables time-travel queries and schema evolution tracking

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    NoETL Workers (K8s Pods)                  │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   Worker 1   │   Worker 2   │   Worker 3   │   Worker N     │
│   DuckDB     │   DuckDB     │   DuckDB     │   DuckDB       │
│   (in-mem)   │   (in-mem)   │   (in-mem)   │   (in-mem)     │
└──────┬───────┴──────┬───────┴──────┬───────┴────────┬────────┘
       │              │              │                │
       │         Catalog Coordination via Postgres    │
       │              │              │                │
       └──────────────┴──────────────┴────────────────┘
                      │
         ┌────────────▼────────────┐
         │    PostgreSQL Server    │
         │                         │
         │  ducklake_catalog DB    │
         │  ┌──────────────────┐   │
         │  │ __ducklake_      │   │
         │  │   metadata_*     │   │
         │  │ (schemas, tables,│   │
         │  │  snapshots, etc) │   │
         │  └──────────────────┘   │
         └────────────┬────────────┘
                      │
       ┌──────────────┴──────────────┐
       │    Shared Storage (RWX)     │
       │  /opt/noetl/data/ducklake   │
       │  ┌──────────┬──────────┐    │
       │  │ Parquet  │ Parquet  │    │
       │  │  Files   │  Files   │    │
       │  └──────────┴──────────┘    │
       └─────────────────────────────┘
```

## Configuration

### Required Fields

```yaml
- step: example
  tool: ducklake
  auth: "{{ my_postgres_credential }}"  # Credential reference for catalog database
  catalog_name: "my_catalog"
  data_path: "/opt/noetl/data/ducklake"
  command: |
    CREATE TABLE example (id INTEGER, name VARCHAR);
```

**Field Descriptions:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `auth` | string | Yes* | Credential reference for PostgreSQL catalog connection |
| `catalog_connection` | string | Yes* | Direct PostgreSQL connection string (alternative to auth) |
| `catalog_name` | string | Yes | Name of the DuckLake catalog (e.g., "analytics") |
| `data_path` | string | Yes | Path to store data files (must be shared across workers) |
| `command` | string | One of | Single SQL command to execute |
| `commands` | list | One of | Multiple SQL commands to execute |

**\*Connection String Resolution:**
- **Preferred**: Use `auth` to reference a registered Postgres credential
- **Alternative**: Use `catalog_connection` for explicit connection string
- Priority: `catalog_connection` > `auth` credential resolution

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `create_catalog` | boolean | true | Auto-create catalog if it doesn't exist |
| `use_catalog` | boolean | true | Run `USE catalog` before executing commands |
| `memory_limit` | string | null | DuckDB memory limit (e.g., "4GB") |
| `threads` | integer | null | Number of threads for DuckDB operations |

## Setup

### 1. Create PostgreSQL Catalog Database

**Note**: If you're using NoETL's Kubernetes deployment, the `ducklake_catalog` database is automatically created during Postgres initialization. You can skip this step.

For standalone or custom Postgres installations:

```sql
-- Connect to Postgres as superuser
CREATE DATABASE ducklake_catalog;

-- Grant access to NoETL user
GRANT ALL PRIVILEGES ON DATABASE ducklake_catalog TO noetl;
```

### 2. Configure Shared Storage (Kubernetes)

Create a ReadWriteMany PVC for data files:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ducklake-data
  namespace: noetl
spec:
  accessModes:
    - ReadWriteMany  # Critical: all workers must access same files
  storageClassName: nfs  # or efs, azurefile, etc.
  resources:
    requests:
      storage: 50Gi
```

Mount in worker deployment:

```yaml
volumes:
  - name: ducklake-data
    persistentVolumeClaim:
      claimName: ducklake-data

volumeMounts:
  - name: ducklake-data
    mountPath: /opt/noetl/data/ducklake
```

### 3. Register Credential (Optional)

If using credential references:

```bash
task register-test-credentials
```

## Usage Examples

### Basic Table Operations

```yaml
- step: create_and_populate
  tool: ducklake
  auth: "{{ postgres_catalog_auth }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  commands:
    - |
      CREATE TABLE sales (
        sale_id INTEGER PRIMARY KEY,
        product VARCHAR,
        amount DECIMAL(10,2),
        sale_date TIMESTAMP
      );
    - |
      INSERT INTO sales VALUES
        (1, 'Widget', 99.99, NOW()),
        (2, 'Gadget', 149.99, NOW());
    - "SELECT * FROM sales ORDER BY sale_id;"
  vars:
    sale_count: "{{ result.data.command_2.row_count }}"
```

### Distributed Loop Processing

```yaml
- step: process_batches
  desc: "Process batches across multiple workers"
  loop:
    collection: "{{ batch_ids }}"
    element: batch_id
    mode: async  # Run in parallel across workers
  tool: ducklake
  auth: "{{ postgres_catalog_auth }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  command: |
    INSERT INTO processed_batches (batch_id, processed_at, worker_id)
    VALUES ({{ loop.element }}, NOW(), current_setting('worker_id'));
  next:
    - when: "{{ event.name == 'loop.done' }}"
      then:
        - step: verify_results
```

### Time Travel Queries

```yaml
- step: query_historical_data
  tool: ducklake
  auth: "{{ postgres_catalog_auth }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  commands:
    # Current data
    - "SELECT COUNT(*) as current_count FROM sales;"
    
    # Data as of specific snapshot
    - "SELECT COUNT(*) as snapshot_count FROM sales FOR SYSTEM_TIME AS OF SNAPSHOT 5;"
    
    # Data as of timestamp
    - "SELECT * FROM sales FOR SYSTEM_TIME AS OF '2025-01-06 10:00:00+00';"
```

### Catalog Introspection

```yaml
- step: inspect_catalog
  tool: ducklake
  auth: "{{ postgres_catalog_auth }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  commands:
    # View snapshots
    - "SELECT * FROM ducklake_snapshots('analytics') ORDER BY snapshot_id DESC LIMIT 10;"
    
    # View tables
    - "SELECT * FROM ducklake_table_info('analytics');"
    
    # View changes between snapshots
    - "SELECT * FROM ducklake_table_changes('analytics', 'main', 'sales', 0, 10);"
```

### Maintenance Operations

```yaml
- step: cleanup_old_data
  tool: ducklake
  auth: "{{ postgres_catalog_auth }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  commands:
    # Expire old snapshots (older than 7 days)
    - "CALL ducklake_expire_snapshots('analytics', older_than => NOW() - INTERVAL 7 DAY);"
    
    # Clean up old files
    - "CALL ducklake_cleanup_old_files('analytics', dry_run => false);"
    
    # Merge adjacent files for better query performance
    - "CALL ducklake_merge_adjacent_files('analytics');"
```

## Response Format

```json
{
  "status": "ok",
  "result": {
    "command_count": 2,
    "commands": [
      {
        "command_index": 0,
        "row_count": 5,
        "columns": ["id", "name", "email"],
        "rows": [
          {"id": 1, "name": "Alice", "email": "alice@example.com"},
          ...
        ]
      },
      {
        "command_index": 1,
        "affected_rows": 10,
        "status": "executed"
      }
    ]
  },
  "catalog_info": {
    "catalog_name": "analytics",
    "snapshot_count": 15,
    "latest_snapshot": {...},
    "table_count": 3,
    "tables": [...]
  }
}
```

## Performance

### Benchmark: Standard DuckDB vs DuckLake

**Test**: Insert 100 rows across 3 workers with connection pooling

| Metric | DuckDB (non-pooled) | DuckLake (pooled) |
|--------|---------------------|-------------------|
| Total time | 44 seconds | 28 seconds |
| Median operation | 440ms | 280ms |
| Errors | "Conflicting lock" | None |
| Connection overhead | High (open/close) | Low (pooled) |

**Conclusion**: DuckLake is ~37% faster and has zero file locking errors.

### Overhead Analysis

- **Single worker**: DuckLake is ~5-10% slower than standalone DuckDB (catalog coordination)
- **Multiple workers**: DuckLake enables true parallelism; standalone DuckDB cannot scale
- **Connection pooling**: DuckLake supports it; standalone DuckDB cannot (file locks)

## Migration from DuckDB Tool

### Before (Standard DuckDB)

```yaml
- step: process_data
  tool: duckdb
  database_path: "/opt/noetl/data/mydb.duckdb"
  command: |
    CREATE TABLE IF NOT EXISTS results (id INTEGER, value VARCHAR);
    INSERT INTO results VALUES (1, 'test');
```

### After (DuckLake)

```yaml
- step: process_data
  tool: ducklake
  catalog_connection: "postgresql://noetl:noetl@postgres:5432/ducklake_catalog"
  catalog_name: "mydb"
  data_path: "/opt/noetl/data/ducklake"
  command: |
    CREATE TABLE IF NOT EXISTS results (id INTEGER, value VARCHAR);
    INSERT INTO results VALUES (1, 'test');
```

**Changes**:
1. `tool: duckdb` → `tool: ducklake`
2. Replace `database_path` with `catalog_connection`, `catalog_name`, `data_path`
3. Create PostgreSQL catalog database
4. Remove any file locking workarounds

## Limitations

1. **PostgreSQL Dependency**: Requires a Postgres server for catalog metadata
2. **Shared Storage**: Still needs shared filesystem (NFS/EFS) or object storage for data files
3. **Slight Overhead**: ~5-10% slower than standalone DuckDB in single-worker scenarios
4. **Network Latency**: Catalog operations involve Postgres network calls

## Troubleshooting

### Catalog Connection Errors

**Error**: `Failed to establish DuckLake connection: could not connect to server`

**Solution**: Verify PostgreSQL connection string and that database exists:
```sql
\l ducklake_catalog  -- Should exist
```

### Shared Storage Issues

**Error**: `No such file or directory: /opt/noetl/data/ducklake`

**Solution**: Verify PVC is mounted:
```bash
kubectl exec -it noetl-worker-0 -n noetl -- ls -la /opt/noetl/data/ducklake
```

### Extension Not Found

**Error**: `Extension 'ducklake' not found`

**Solution**: Ensure DuckDB version >= 1.3.0. Check with:
```python
import duckdb
print(duckdb.__version__)  # Should be >= 1.3.0
```

## See Also

- [DuckLake Official Documentation](https://ducklake.select/)
- [DuckDB Extension Guide](https://duckdb.org/docs/stable/core_extensions/ducklake)
- [NoETL DuckDB Tool](../duckdb/) (standard single-worker DuckDB)
- [Test Playbook](../../tests/fixtures/playbooks/ducklake_test/)
