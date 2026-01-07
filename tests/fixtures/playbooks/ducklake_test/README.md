# DuckLake Test Playbook

This playbook demonstrates the `ducklake` tool for distributed DuckDB operations with a PostgreSQL-backed metastore.

## Overview

**DuckLake** is a DuckDB extension that provides:
- **Shared Catalog**: PostgreSQL stores metadata (schemas, tables, snapshots)
- **Concurrent Access**: Multiple workers can safely read/write without file locking issues
- **ACID Transactions**: Full transaction support across distributed workers
- **Time Travel**: Query historical snapshots of data
- **Schema Evolution**: Track schema changes over time

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Worker 1   │     │  Worker 2   │     │  Worker 3   │
│   DuckDB    │     │   DuckDB    │     │   DuckDB    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │    Catalog Coordination via Postgres  │
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                  ┌────────▼────────┐
                  │   PostgreSQL    │
                  │   Metastore     │
                  │  (ducklake_catalog)
                  └─────────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
  ┌────────┐          ┌────────┐          ┌────────┐
  │ Table  │          │ Table  │          │ Table  │
  │ Files  │          │ Files  │          │ Files  │
  │ (Data  │          │ (Data  │          │ (Data  │
  │  Path) │          │  Path) │          │  Path) │
  └────────┘          └────────┘          └────────┘
```

## Prerequisites

1. **PostgreSQL Database**: Create a dedicated database for DuckLake catalog:
   ```sql
   CREATE DATABASE ducklake_catalog;
   ```

2. **Shared Data Path**: All workers must have access to the same data_path:
   - Kubernetes: Use ReadWriteMany PVC (e.g., NFS, EFS, Azure Files)
   - Local: Use shared filesystem path

## Playbook Configuration

Key fields:

- `catalog_connection`: PostgreSQL connection string for metastore
  ```
  postgresql://user:password@host:port/ducklake_catalog
  ```

- `catalog_name`: Name of the DuckLake catalog (e.g., `analytics`)

- `data_path`: Path to store data files (must be accessible by all workers)
  ```
  /opt/noetl/data/ducklake
  ```

- `command` or `commands`: SQL statements to execute

## Usage Examples

### 1. Create Table and Insert Data

```yaml
- step: create_users_table
  tool: ducklake
  catalog_connection: "postgresql://noetl:noetl@postgres.noetl.svc.cluster.local:5432/ducklake_catalog"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  command: |
    CREATE TABLE users (
      id INTEGER PRIMARY KEY,
      name VARCHAR,
      email VARCHAR,
      created_at TIMESTAMP
    );
    INSERT INTO users VALUES 
      (1, 'Alice', 'alice@example.com', NOW()),
      (2, 'Bob', 'bob@example.com', NOW());
```

### 2. Query Data (Time Travel)

```yaml
- step: query_historical_data
  tool: ducklake
  catalog_connection: "{{ catalog_conn }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  command: |
    -- Query current snapshot
    SELECT * FROM users;
    
    -- Query specific snapshot by ID
    SELECT * FROM users FOR SYSTEM_TIME AS OF SNAPSHOT 5;
    
    -- Query snapshot by timestamp
    SELECT * FROM users FOR SYSTEM_TIME AS OF '2025-01-06 10:00:00+00';
```

### 3. Track Changes

```yaml
- step: view_changes
  tool: ducklake
  catalog_connection: "{{ catalog_conn }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  commands:
    - "SELECT * FROM ducklake_snapshots('analytics');"
    - "SELECT * FROM ducklake_table_info('analytics');"
    - "SELECT * FROM ducklake_table_changes('analytics', 'main', 'users', 0, 10);"
```

### 4. Distributed Loop Example

```yaml
- step: process_data
  loop:
    collection: "{{ user_ids }}"
    element: user_id
    mode: async
  tool: ducklake
  catalog_connection: "{{ catalog_conn }}"
  catalog_name: "analytics"
  data_path: "/opt/noetl/data/ducklake"
  command: |
    INSERT INTO user_events (user_id, event_type, event_time)
    VALUES ({{ user_id }}, 'login', NOW());
  next:
    - when: "{{ event.name == 'loop.done' }}"
      then:
        - step: end
```

## Benefits Over Standard DuckDB

1. **No File Locking**: Multiple workers can operate simultaneously
2. **Connection Pooling**: Can safely use connection pools (catalog handles coordination)
3. **ACID Guarantees**: Transactions work correctly across distributed operations
4. **Snapshot Isolation**: Each operation sees a consistent view of data
5. **Audit Trail**: All schema and data changes tracked in catalog

## Limitations

1. **Postgres Dependency**: Requires PostgreSQL database for catalog
2. **Overhead**: Slightly slower than standalone DuckDB due to catalog coordination
3. **Shared Storage**: Still requires shared filesystem or object storage for data files

## Testing

Execute this playbook:
```bash
curl -X POST "http://localhost:8082/api/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "catalog_id": "tests/fixtures/playbooks/ducklake_test",
    "payload": {}
  }'
```

Check catalog state:
```sql
-- Connect to PostgreSQL
\c ducklake_catalog

-- View catalog metadata (DuckLake creates __ducklake_metadata_<catalog> schema)
\dt __ducklake_metadata_analytics.*

-- Query snapshots
SELECT * FROM ducklake_snapshots('analytics');
```

## Performance

DuckLake adds minimal overhead:
- **Single worker**: ~5-10% slower than standalone DuckDB
- **Multiple workers**: Enables parallelism that standalone DuckDB cannot provide

## Migration from DuckDB

To migrate from existing `tool: duckdb` playbooks:

1. Create PostgreSQL catalog database
2. Change `tool: duckdb` → `tool: ducklake`
3. Add `catalog_connection`, `catalog_name`, `data_path` fields
4. Remove any file locking workarounds (no longer needed)
5. Can safely use connection pooling

## See Also

- [DuckLake Documentation](https://ducklake.select/)
- [DuckDB Extension](https://duckdb.org/docs/stable/core_extensions/ducklake)
- [NoETL DuckDB Tool](../duckdb_gcs_workload_identity/)
