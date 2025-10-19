# Snowflake Transfer Plugin - Quick Reference

## What It Does

Enables efficient, memory-friendly data transfer between Snowflake and PostgreSQL using chunked streaming.

## Files Created

```
noetl/plugin/snowflake/
├── transfer.py                          # NEW: Core transfer logic
├── executor.py                          # MODIFIED: Added transfer task executor
└── __init__.py                          # MODIFIED: Export transfer function

tests/fixtures/
├── credentials/
│   ├── sf_test.json                     # NEW: Snowflake test credential
│   └── sf_test.json.template            # NEW: Credential template
└── playbooks/snowflake_transfer/
    ├── snowflake_transfer.yaml          # NEW: Complete test playbook
    ├── README.md                        # NEW: Full documentation
    └── test_validation.sh               # NEW: Validation script

ci/taskfile/
└── test.yml                             # MODIFIED: Added credential registration

docs/
└── snowflake_transfer_implementation.md # NEW: Implementation guide
```

## Quick Start

### 1. Validate Installation

```bash
./tests/fixtures/playbooks/snowflake_transfer/test_validation.sh
```

### 2. Configure Credentials

Edit `tests/fixtures/credentials/sf_test.json`:

```json
{
  "name": "sf_test",
  "type": "snowflake",
  "data": {
    "sf_account": "xy12345.us-east-1",
    "sf_user": "your_username",
    "sf_password": "your_password",
    "sf_warehouse": "COMPUTE_WH",
    "sf_database": "TEST_DB",
    "sf_schema": "PUBLIC"
  }
}
```

### 3. Register Credential

```bash
curl -X POST http://localhost:8082/api/credentials \
  -H "Content-Type: application/json" \
  --data-binary @tests/fixtures/credentials/sf_test.json
```

### 4. Run Test Playbook

```bash
# Register playbook
task noetltest:playbook-register -- \
  tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml

# Execute
task noetltest:playbook-execute -- \
  tests/fixtures/playbooks/snowflake_transfer
```

## Usage in Playbooks

### Snowflake → PostgreSQL

```yaml
- step: transfer_sf_to_pg
  type: python
  code: |
    from noetl.plugin.snowflake import execute_snowflake_transfer_task
    from jinja2 import Environment
    
    def main(input_data):
        task_config = {
            'transfer_direction': 'sf_to_pg',
            'source_query': 'SELECT * FROM my_table',
            'target_table': 'public.my_target',
            'chunk_size': 5000,
            'mode': 'append'
        }
        
        task_with = {
            'sf_account': input_data['sf_account'],
            'sf_user': input_data['sf_user'],
            'sf_password': input_data['sf_password'],
            'sf_warehouse': 'COMPUTE_WH',
            'sf_database': 'MY_DB',
            'pg_host': 'localhost',
            'pg_port': '5432',
            'pg_user': input_data['pg_user'],
            'pg_password': input_data['pg_password'],
            'pg_database': 'mydb'
        }
        
        return execute_snowflake_transfer_task(
            task_config=task_config,
            context={'execution_id': input_data['execution_id']},
            jinja_env=Environment(),
            task_with=task_with
        )
```

### PostgreSQL → Snowflake

```yaml
- step: transfer_pg_to_sf
  type: python
  code: |
    from noetl.plugin.snowflake import execute_snowflake_transfer_task
    from jinja2 import Environment
    
    def main(input_data):
        task_config = {
            'transfer_direction': 'pg_to_sf',
            'source_query': 'SELECT * FROM public.my_source',
            'target_table': 'MY_TARGET',
            'chunk_size': 5000,
            'mode': 'replace'
        }
        
        # ... (similar task_with setup)
        
        return execute_snowflake_transfer_task(...)
```

## Transfer Modes

| Mode | Snowflake → PG | PG → Snowflake | Description |
|------|----------------|----------------|-------------|
| `append` | ✅ | ✅ | Add to existing data |
| `replace` | ✅ | ✅ | Truncate then insert |
| `upsert` | ✅ | ❌ | Insert or update (PG only) |
| `merge` | ❌ | ✅ | Insert or update (SF only) |

## Performance Tuning

### Chunk Size Guidelines

| Data Volume | Recommended Chunk Size | Memory Usage |
|-------------|------------------------|--------------|
| < 100K rows | 1,000 | ~1-10 MB |
| 100K - 1M | 5,000 | ~5-50 MB |
| 1M - 10M | 10,000 | ~10-100 MB |
| > 10M rows | 20,000+ | ~20-200 MB |

### Network Optimization

- **Local Transfer**: Use larger chunks (10K-50K rows)
- **Cross-Region**: Use smaller chunks (1K-5K rows)
- **High Latency**: Reduce chunk size, increase parallelism

### Memory Constraints

```python
# Calculate chunk size based on available memory
avg_row_bytes = 1000  # Estimate from sample
available_memory_mb = 100
chunk_size = int((available_memory_mb * 1024 * 1024) / avg_row_bytes)
```

## Monitoring

### Check Transfer Progress

```bash
# Watch worker logs
tail -f logs/worker.log | grep -i "transfer progress"

# Query events
PGPASSWORD=noetl psql -h localhost -p 54321 -U noetl -d demo_noetl -c \
  "SELECT node_name, status, result 
   FROM noetl.event 
   WHERE execution_id = '<exec_id>' 
   ORDER BY created_at;"
```

### Result Structure

```json
{
  "id": "uuid",
  "status": "success",
  "data": {
    "rows_transferred": 5000,
    "chunks_processed": 5,
    "target_table": "public.my_target",
    "columns": ["id", "name", "value"]
  }
}
```

## Error Handling

### Common Issues

**Connection Timeout**:
```python
# Reduce chunk size
'chunk_size': 1000  # Instead of 10000
```

**Memory Error**:
```python
# Use smaller chunks
'chunk_size': 500
```

**Type Mismatch**:
```sql
-- Cast in source query
SELECT 
  id,
  name,
  value::VARCHAR as value,  -- Explicit cast
  created_at
FROM my_table
```

**Primary Key Conflict** (upsert):
```python
# Ensure first column is primary key
'source_query': 'SELECT pk_column, col1, col2 FROM table'
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    NoETL Worker                         │
│                                                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │  execute_snowflake_transfer_task()              │   │
│  │                                                   │   │
│  │  1. Parse task_config                            │   │
│  │  2. Connect to Snowflake                         │   │
│  │  3. Connect to PostgreSQL                        │   │
│  │  4. Call transfer function                       │   │
│  └─────────────┬───────────────────────────────────┘   │
│                │                                         │
│                ▼                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  transfer_snowflake_to_postgres() OR             │   │
│  │  transfer_postgres_to_snowflake()               │   │
│  │                                                   │   │
│  │  Loop:                                            │   │
│  │    1. Fetch chunk from source cursor             │   │
│  │    2. Convert data types                         │   │
│  │    3. Insert into target                         │   │
│  │    4. Commit transaction                         │   │
│  │    5. Log progress                               │   │
│  │    6. Repeat until done                          │   │
│  └─────────────────────────────────────────────────┘   │
│                                                           │
└─────────────────────────────────────────────────────────┘

         ▲                           ▲
         │                           │
         │ Read Chunks               │ Write Chunks
         │                           │
    ┌────┴────┐               ┌─────┴─────┐
    │Snowflake│               │PostgreSQL │
    │Database │               │ Database  │
    └─────────┘               └───────────┘
```

## API Reference

### execute_snowflake_transfer_task()

```python
def execute_snowflake_transfer_task(
    task_config: Dict,      # Transfer configuration
    context: Dict,          # Execution context
    jinja_env: Environment, # Template environment
    task_with: Dict,        # Connection parameters
    log_event_callback=None # Event logging
) -> Dict:
```

**Returns:**
```python
{
    'id': str,              # Task UUID
    'status': str,          # 'success' or 'error'
    'data': {
        'rows_transferred': int,
        'chunks_processed': int,
        'target_table': str,
        'columns': List[str]
    },
    'error': str            # Only if status == 'error'
}
```

## Testing Checklist

- [ ] Validation script passes
- [ ] Credentials configured
- [ ] Credentials registered
- [ ] Test playbook registered
- [ ] Test execution successful
- [ ] Both transfer directions work
- [ ] All transfer modes tested
- [ ] Error handling verified
- [ ] Cleanup successful

## Documentation Links

- **Full Guide**: `tests/fixtures/playbooks/snowflake_transfer/README.md`
- **Implementation**: `docs/snowflake_transfer_implementation.md`
- **Code**: `noetl/plugin/snowflake/transfer.py`
- **Test Playbook**: `tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml`

## Support

For detailed documentation, see:
```bash
cat tests/fixtures/playbooks/snowflake_transfer/README.md
```

For implementation details:
```bash
cat docs/snowflake_transfer_implementation.md
```
