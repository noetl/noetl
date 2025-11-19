# Data Transfer Test Playbooks

This directory contains comprehensive test playbooks demonstrating various patterns for transferring data from HTTP APIs to databases (PostgreSQL, Snowflake, DuckDB).

## Quick Reference

| Playbook | Pattern | Complexity | Best For | Details |
|----------|---------|------------|----------|---------|
| [http_to_postgres_transfer](#http_to_postgres_transfer) | Transfer Tool | ⭐ Low | Production ETL, simple mapping | [📁 Folder](./http_to_postgres_transfer/) |
| [http_to_postgres_simple](#http_to_postgres_simple) | Python Batch | ⭐⭐ Medium | Custom transformations | [📁 Folder](./http_to_postgres_simple/) |
| [http_to_postgres_iterator](#http_to_postgres_iterator) | Iterator | ⭐⭐⭐ High | Large datasets, per-record logic | [📁 Folder](./http_to_postgres_iterator/) |
| [http_to_postgres_bulk](#http_to_postgres_bulk) | Native COPY | ⭐⭐ Medium | Maximum performance | [📁 Folder](./http_to_postgres_bulk/) |
| [http_to_postgres_direct](#http_to_postgres_direct) | Direct SQL | ⭐ Low | Quick prototypes | [📁 Folder](./http_to_postgres_direct/) |
| [http_to_databases](#http_to_databases) | Multi-Target | ⭐⭐⭐ High | Parallel DB inserts | [📁 Folder](./http_to_databases/) |
| [http_iterator_save_postgres](#http_iterator_save_postgres) | Iterator + Save | ⭐⭐⭐ High | Per-record storage | [📁 Folder](./http_iterator_save_postgres/) |
| [snowflake_postgres](#snowflake_postgres) | Snowflake Transfer | ⭐⭐ Medium | Snowflake ↔ Postgres | [📁 Folder](./snowflake_postgres/) |

## Overview

These playbooks demonstrate different approaches to HTTP-to-database data transfer, each optimized for specific use cases. All examples fetch data from JSONPlaceholder API (100 posts) and demonstrate:

- Field mapping and transformation
- Error handling patterns
- Performance characteristics
- When to use each approach

## Pattern Overview

### Transfer Tool Pattern
**Best for**: Production ETL pipelines with straightforward field mapping

**Characteristics**:
- Pure configuration (no code)
- Declarative field mapping
- Built-in error handling
- Excellent performance

**Example**: `http_to_postgres_transfer`

### Python Transformation Pattern
**Best for**: Custom business logic and complex transformations

**Characteristics**:
- Full programming flexibility
- Custom validation
- Dynamic SQL generation
- Moderate complexity

**Example**: `http_to_postgres_simple`

### Iterator Pattern
**Best for**: Large datasets and per-record processing

**Characteristics**:
- Record-by-record processing
- Lower memory footprint
- Built-in parallelization
- Higher configuration complexity

**Examples**: `http_to_postgres_iterator`, `http_iterator_save_postgres`

### Native Operations Pattern
**Best for**: Maximum performance with database-native features

**Characteristics**:
- Uses native database operations (COPY, MERGE)
- Fastest performance
- Less flexible
- Database-specific

**Examples**: `http_to_postgres_bulk`, `snowflake_postgres`

## Detailed Playbook Documentation

### http_to_postgres_transfer

**Location**: [`./http_to_postgres_transfer/`](./http_to_postgres_transfer/)

**Pattern**: Transfer Tool (Declarative ETL)

**Description**: Demonstrates the simplest and most efficient pattern using NoETL's transfer tool for direct HTTP → PostgreSQL data movement with field mapping.

**Key Features**:
- Declarative configuration (no Python code)
- Automatic field mapping: `post_id: id`, `user_id: userId`
- Single-step ETL pipeline
- Built-in batch operations

**Configuration**:
```yaml
- tool: transfer
  source:
    type: http
    url: "https://jsonplaceholder.typicode.com/posts"
    method: GET
  target:
    type: postgres
    auth: "{{ workload.pg_auth }}"
    table: public.http_to_postgres_transfer
    mode: insert
    mapping:
      post_id: id
      user_id: userId
      title: title
      body: body
```

**Results**: 100 records with auto-generated ID and timestamp

**When to Use**: 
- ✅ Standard ETL with field mapping
- ✅ No complex transformations needed
- ✅ Production data pipelines

**Learn More**: [Full README](./http_to_postgres_transfer/README.md)

---

### http_to_postgres_simple

**Location**: [`./http_to_postgres_simple/`](./http_to_postgres_simple/)

**Pattern**: Python Batch INSERT with Transformation

**Description**: Uses Python to transform API data and generate batch INSERT statements executed via Jinja2 join filter.

**Key Features**:
- Python transformation logic
- SQL statement generation
- Single-quote escaping
- Batch execution with `{{ sql_statements | join('\n') }}`

**Configuration**:
```yaml
- tool: python
  code: |
    def main(input_data):
        posts = input_data if isinstance(input_data, list) else []
        insert_statements = []
        for post in posts:
            sql = f"INSERT INTO table ..."
            insert_statements.append(sql)
        return {'sql_statements': insert_statements}
  args:
    input_data: "{{ fetch_posts }}"  # Note: NOT .data

- tool: postgres
  command: "{{ transform_and_insert.sql_statements | join('\n') }}"
```

**Results**: 100 records with custom SQL generation

**When to Use**:
- ✅ Custom transformation logic
- ✅ Business rules and validation
- ✅ Dynamic SQL requirements
- ✅ <10K records

**Learn More**: [Full README](./http_to_postgres_simple/README.md)

---

### http_to_postgres_iterator

**Location**: [`./http_to_postgres_iterator/`](./http_to_postgres_iterator/)

**Pattern**: Iterator with Record-by-Record Processing

**Description**: Processes each API record individually using NoETL's iterator tool with nested PostgreSQL inserts.

**Key Features**:
- Per-record processing
- Dollar-quoted strings for SQL safety
- Nested task execution
- Memory-efficient for large datasets

**Configuration**:
```yaml
- tool: iterator
  collection: "{{ fetch_http_data }}"
  element: item
  mode: sequential
  nested_tasks:
    - tool: postgres
      command: |
        INSERT INTO table (id, user_id, title, body)
        VALUES (
          {{ item.id }},
          {{ item.userId }},
          $${{ item.title }}$$,
          $${{ item.body }}$$
        );
```

**Results**: 100 individual INSERT operations

**When to Use**:
- ✅ Very large datasets
- ✅ Per-record validation/processing
- ✅ Streaming data
- ✅ Memory constraints

**Learn More**: [Full README](./http_to_postgres_iterator/README.md)

---

### http_to_postgres_bulk

**Location**: [`./http_to_postgres_bulk/`](./http_to_postgres_bulk/)

**Pattern**: Native PostgreSQL COPY Command

**Description**: Uses PostgreSQL's native COPY command for maximum insert performance via CSV intermediate format.

**Key Features**:
- Maximum performance (10K+ records/sec)
- Native PostgreSQL COPY
- CSV intermediate format
- Python CSV generation

**When to Use**:
- ✅ Bulk data loading (>10K records)
- ✅ Maximum performance required
- ✅ Simple field mapping
- ✅ PostgreSQL-specific

**Learn More**: Check [`http_to_postgres_bulk.yaml`](./http_to_postgres_bulk/http_to_postgres_bulk.yaml)

---

### http_to_postgres_direct

**Location**: [`./http_to_postgres_direct/`](./http_to_postgres_direct/)

**Pattern**: Direct SQL Execution

**Description**: Simplest approach - directly embeds HTTP response data into SQL INSERT statements.

**Key Features**:
- Minimal configuration
- Direct SQL execution
- Quick prototyping
- Limited scalability

**When to Use**:
- ✅ Quick prototypes
- ✅ Small datasets
- ✅ Testing/development
- ❌ Production (use transfer tool instead)

**Learn More**: Check [`http_to_postgres_direct.yaml`](./http_to_postgres_direct/http_to_postgres_direct.yaml)

---

### http_to_databases

**Location**: [`./http_to_databases/`](./http_to_databases/)

**Pattern**: Multi-Target Parallel Distribution

**Description**: Fetches data once from HTTP API and distributes to multiple database types (PostgreSQL, Snowflake, DuckDB) in parallel.

**Key Features**:
- Single HTTP fetch
- Parallel database inserts
- Multiple database types
- Iterator-based distribution

**Configuration**:
```yaml
- tool: iterator
  collection: "{{ databases }}"
  element: db
  mode: async  # Parallel execution
  nested_tasks:
    - tool: "{{ db.type }}"  # postgres, snowflake, or duckdb
      auth: "{{ db.auth }}"
      command: |
        INSERT INTO {{ db.table }} ...
```

**Results**: Data replicated across 3 databases simultaneously

**When to Use**:
- ✅ Multi-database replication
- ✅ Data distribution
- ✅ Parallel processing
- ✅ Heterogeneous environments

**Learn More**: [Full README](./http_to_databases/README.md)

---

### http_iterator_save_postgres

**Location**: [`./http_iterator_save_postgres/`](./http_iterator_save_postgres/)

**Pattern**: Iterator with Inline Save Storage

**Description**: Combines iterator pattern with NoETL's save storage feature for automatic result persistence.

**Key Features**:
- Iterator record processing
- Inline save configuration
- Automatic storage delegation
- Per-iteration result capture

**Configuration**:
```yaml
- tool: iterator
  collection: "{{ fetch_posts }}"
  element: post
  nested_tasks:
    - tool: postgres
      command: "INSERT INTO ..."
      save:
        storage: postgres
        table: results_table
```

**When to Use**:
- ✅ Need to store iteration results
- ✅ Audit trail requirements
- ✅ Result tracking per record

**Learn More**: Check [`http_iterator_save_postgres.yaml`](./http_iterator_save_postgres/http_iterator_save_postgres.yaml)

---

### snowflake_postgres

**Location**: [`./snowflake_postgres/`](./snowflake_postgres/)

**Pattern**: Bidirectional Snowflake ↔ PostgreSQL Transfer

**Description**: Demonstrates complete bidirectional data transfer between Snowflake and PostgreSQL databases with UPSERT/MERGE logic.

**Key Features**:
- Snowflake → PostgreSQL with UPSERT
- PostgreSQL → Snowflake with MERGE
- Custom SQL queries
- Table setup and cleanup

**Configuration**:
```yaml
- tool: transfer
  source:
    type: snowflake
    auth: "{{ sf_auth }}"
    query: "SELECT * FROM sf_table"
  target:
    type: postgres
    auth: "{{ pg_auth }}"
    query: |
      INSERT INTO pg_table ... 
      ON CONFLICT (id) DO UPDATE ...
```

**When to Use**:
- ✅ Snowflake integration
- ✅ Bidirectional sync
- ✅ Cloud data warehouse transfers

**Learn More**: [Full README](./snowflake_postgres/README.md)

---

## Pattern Comparison Matrix

| Feature | Transfer | Python Batch | Iterator | Bulk Copy | Direct SQL |
|---------|----------|--------------|----------|-----------|------------|
| **Code Required** | None | Python | YAML | Python | None |
| **Complexity** | ⭐ Low | ⭐⭐ Medium | ⭐⭐⭐ High | ⭐⭐ Medium | ⭐ Low |
| **Performance** | ⭐⭐⭐⭐ Excellent | ⭐⭐⭐ Good | ⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Best | ⭐⭐ Fair |
| **Memory Usage** | ⭐⭐⭐ Low | ⭐⭐ Medium | ⭐⭐⭐⭐ Lowest | ⭐⭐⭐ Low | ⭐ High |
| **Flexibility** | ⭐⭐ Limited | ⭐⭐⭐⭐⭐ Highest | ⭐⭐⭐ Medium | ⭐⭐ Limited | ⭐ Minimal |
| **Field Mapping** | Declarative | Programmatic | Template | Positional | Hardcoded |
| **Best Dataset Size** | Any | <10K | Any | >10K | <100 |
| **Production Ready** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No |
| **Error Handling** | Built-in | Custom | Per-record | Native | Basic |

## Choosing the Right Pattern

### Use **Transfer Tool** when:
- ✅ Simple field mapping without transformations
- ✅ Production ETL pipeline
- ✅ Want minimal configuration
- ✅ Don't need custom logic
- **Example**: `http_to_postgres_transfer`

### Use **Python Batch** when:
- ✅ Need custom transformation logic
- ✅ Business rules and validation
- ✅ Complex calculations
- ✅ <10K records
- **Example**: `http_to_postgres_simple`

### Use **Iterator** when:
- ✅ Very large datasets (>10K records)
- ✅ Per-record processing needed
- ✅ Memory constraints
- ✅ Want parallelization
- **Example**: `http_to_postgres_iterator`

### Use **Bulk Copy** when:
- ✅ Maximum performance required
- ✅ Large bulk loads (>10K records)
- ✅ Simple field mapping
- ✅ PostgreSQL-specific OK
- **Example**: `http_to_postgres_bulk`

### Use **Multi-Target** when:
- ✅ Need data in multiple databases
- ✅ Want parallel distribution
- ✅ Heterogeneous environments
- **Example**: `http_to_databases`

## Common Patterns and Techniques

### Template Reference Best Practices

**❌ Wrong** - Using `.data` suffix:
```yaml
args:
  input_data: "{{ fetch_posts.data }}"  # Renders as string "[{...}]"
```

**✅ Correct** - Direct step reference:
```yaml
args:
  input_data: "{{ fetch_posts }}"  # Passes actual list object
```

**Why**: NoETL's TaskResultProxy automatically unwraps data when you reference the step name directly.

### Field Mapping Syntax

**Transfer Tool**:
```yaml
mapping:
  db_column_name: json_field_name
  post_id: id
  user_id: userId
```

**Iterator Template**:
```yaml
VALUES (
  {{ item.id }},
  {{ item.userId }},
  $${{ item.title }}$$  # Dollar-quoted for SQL safety
)
```

### Error Handling Patterns

**Transfer Tool**: Built-in error reporting with retry
**Python**: Try-except with custom error returns
**Iterator**: Per-record error isolation with continue-on-error
**Bulk**: Native database error handling

## Running the Playbooks

### Setup

```bash
# Reset environment
task noetl:local:reset

# Register test credentials
task register-test-credentials

# Create test tables
task test:local:create-tables
```

### Execute Individual Playbook

```bash
# Using CLI
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' --merge

# Using API
curl -X POST http://localhost:8083/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer",
    "args": {"pg_auth": "pg_local"},
    "merge": true
  }'
```

### Verification Queries

```sql
-- Transfer tool result
SELECT COUNT(*) FROM public.http_to_postgres_transfer;
-- Expected: 100

-- Python batch result
SELECT COUNT(*) FROM public.http_to_postgres_simple;
-- Expected: 100

-- Iterator result
SELECT COUNT(*) FROM public.http_to_postgres_iterator;
-- Expected: 100

-- Multi-database result
SELECT COUNT(*) FROM public.http_to_databases_pg;
-- Expected: 10 (sample users)
```

## Architecture Notes

### Transfer Tool Architecture

The transfer tool uses a registry pattern to support multiple source/target combinations:

```python
TRANSFER_FUNCTIONS = {
    ('http', 'postgres'): http_to_postgres,
    ('http', 'snowflake'): http_to_snowflake,
    ('postgres', 'snowflake'): postgres_to_snowflake,
    ('snowflake', 'postgres'): snowflake_to_postgres,
    # Add new combinations here
}
```

**Key Components**:
- **Source Plugins**: Fetch data (http, postgres, snowflake)
- **Target Plugins**: Write data (postgres, snowflake, duckdb)
- **Transfer Functions**: Handle type-specific mapping logic
- **Field Mapping**: Declarative column-to-field mapping

### Extending Transfer Tool

To add a new source or target:

1. **Create Plugin** in `noetl/plugin/`:
```python
class NewSourcePlugin(BasePlugin):
    def execute(self, config):
        # Fetch data
        return {'data': records}
```

2. **Register Transfer Function**:
```python
def new_source_to_postgres(source_config, target_config):
    # Implement transfer logic
    pass

TRANSFER_FUNCTIONS[('new_source', 'postgres')] = new_source_to_postgres
```

3. **Use in Playbook**:
```yaml
- tool: transfer
  source:
    type: new_source
    connection: "{{ workload.conn }}"
  target:
    type: postgres
    table: my_table
```

## Configuration Reference

### Authentication Patterns

**v1.0+ Unified Auth** (Recommended):
```yaml
workload:
  pg_auth: "pg_local"  # Credential key

workflow:
  - tool: postgres
    auth: "{{ workload.pg_auth }}"
```

**Multi-Credential Binding**:
```yaml
- tool: transfer
  credentials:
    source_cred:
      key: "{{ workload.sf_auth }}"
    target_cred:
      key: "{{ workload.pg_auth }}"
  source:
    auth: "{{ source_cred }}"
  target:
    auth: "{{ target_cred }}"
```

**Secret Manager Integration**:
```yaml
- tool: postgres
  password: "{{ secret.DB_PASSWORD }}"
```

### Field Mapping Patterns

**Simple Mapping**:
```yaml
mapping:
  target_column: source_field
```

**Nested Field Extraction**:
```yaml
mapping:
  user_id: user.id
  user_name: user.profile.name
```

**Calculated Fields** (use Python tool):
```python
def main(input_data):
    for record in input_data:
        record['full_name'] = f"{record['first']} {record['last']}"
    return input_data
```

### Error Handling Configuration

**Transfer Tool**:
```yaml
- tool: transfer
  retry:
    max_attempts: 3
    backoff_seconds: 5
  on_error: continue  # or 'fail'
```

**Python Tool**:
```python
def main(input_data):
    try:
        # Process data
        return {'status': 'success', 'data': result}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
```

**Iterator**:
```yaml
- tool: iterator
  continue_on_error: true
  error_limit: 10
```

## Testing and Validation

### Unit Testing Patterns

```bash
# Test individual playbook
task test:local:execute PLAYBOOK=http_to_postgres_transfer

# Test with custom payload
.venv/bin/noetl execute playbook "path/to/playbook" \
  --payload '{"pg_auth": "pg_local", "debug": true}' \
  --merge
```

### Integration Testing

```bash
# Full test cycle
task test:local:full PLAYBOOK=http_to_postgres_simple

# Steps:
# 1. Register credentials
# 2. Create test tables
# 3. Execute playbook
# 4. Validate data
# 5. Cleanup
```

### Validation Queries

```sql
-- Check record count
SELECT COUNT(*) FROM schema.table;

-- Verify field mapping
SELECT 
  MIN(post_id) as min_id,
  MAX(post_id) as max_id,
  COUNT(DISTINCT user_id) as unique_users
FROM schema.table;

-- Check for nulls
SELECT 
  COUNT(*) FILTER (WHERE title IS NULL) as null_titles,
  COUNT(*) FILTER (WHERE body IS NULL) as null_bodies
FROM schema.table;

-- Verify timestamps
SELECT 
  MIN(fetched_at) as first_fetch,
  MAX(fetched_at) as last_fetch
FROM schema.table;
```

## Performance Optimization

### Pattern-Specific Tips

**Transfer Tool**:
- Use batch mode for large datasets
- Enable connection pooling
- Configure appropriate timeouts

**Python Batch**:
- Batch INSERT statements (100-1000 records per batch)
- Use prepared statements for security
- Avoid row-by-row execution

**Iterator**:
- Use `mode: async` for parallel processing
- Set appropriate concurrency limits
- Monitor memory usage

**Bulk Copy**:
- Best for >10K records
- Disable indexes during load
- Use COPY with CSV format
- Re-enable indexes after load

### Memory Considerations

| Pattern | Memory Usage | Dataset Size Limit |
|---------|--------------|-------------------|
| Transfer | Low-Medium | Unlimited (batched) |
| Python Batch | Medium | <10K records |
| Iterator | Low | Unlimited (streaming) |
| Bulk Copy | Low | Unlimited (streaming) |
| Direct SQL | High | <1K records |

### Connection Pooling

```yaml
workload:
  postgres_pool:
    min_connections: 2
    max_connections: 10
    connection_timeout: 30

- tool: postgres
  pool: "{{ workload.postgres_pool }}"
```

## Troubleshooting

### Common Issues

**1. Empty Table After Execution**
- Check template reference: Use `{{ step }}` not `{{ step.data }}`
- Verify field mapping matches source data structure
- Check event log for errors: `SELECT * FROM noetl.event WHERE execution_id = 'xxx'`

**2. Transfer Tool Configuration Error**
- Use `type:` not `tool:` in source/target config
- Verify auth credential exists: `SELECT * FROM noetl.credential WHERE key = 'xxx'`
- Check TRANSFER_FUNCTIONS registry supports source→target combination

**3. Iterator Not Processing Records**
- Verify collection reference resolves to array
- Check element variable is accessible in nested tasks
- Use `mode: sequential` for debugging before `mode: async`

**4. Python Tool Args vs Data**
- Use `args:` parameter (preferred)
- Legacy `data:` field only works if no `args` present
- Return dictionary with keys for downstream reference

### Debug Techniques

**Enable Debug Logging**:
```yaml
workload:
  debug: true
  log_level: DEBUG
```

**Add Logging to Python**:
```python
def main(input_data):
    print(f"DEBUG: Received {len(input_data)} records")
    print(f"DEBUG: First record: {input_data[0]}")
    # ... process
```

**Check Execution Events**:
```sql
SELECT 
  step,
  status,
  created_at,
  data->>'error' as error_msg
FROM noetl.event
WHERE execution_id = 'xxx'
ORDER BY created_at;
```

**Test Field Mapping**:
```sql
-- After transfer, check actual vs expected columns
SELECT column_name, data_type 
FROM information_schema.columns
WHERE table_name = 'your_table';
```

## Related Documentation

- [NoETL Core Concepts](../../docs/core_concept.md)
- [DSL Specification](../../docs/dsl_spec.md)
- [Plugin Development](../../docs/action_type.md)
- [Credential Configuration](../../docs/configuration.md)
- [API Usage](../../docs/api_usage.md)

## Examples by Use Case

### Real-time Data Ingestion
→ Use **Iterator** pattern with `mode: async`
→ Example: `http_to_postgres_iterator`

### Bulk Data Migration
→ Use **Bulk Copy** pattern for >10K records
→ Example: `http_to_postgres_bulk`

### Multi-Database Replication
→ Use **Multi-Target** pattern
→ Example: `http_to_databases`

### Custom Business Logic
→ Use **Python Batch** pattern
→ Example: `http_to_postgres_simple`

### Production ETL Pipeline
→ Use **Transfer Tool** pattern
→ Example: `http_to_postgres_transfer`

### Cloud Data Warehouse Integration
→ Use **Snowflake Transfer** pattern
→ Example: `snowflake_postgres`

## Contributing

When adding new data transfer patterns:

1. Create subfolder: `tests/fixtures/playbooks/data_transfer/new_pattern/`
2. Add playbook YAML with descriptive name
3. Create detailed README.md documenting:
   - Pattern description
   - Configuration options
   - Use cases
   - Performance characteristics
   - Example execution
4. Update this main README with quick reference entry
5. Add validation queries
6. Create corresponding task in `ci/taskfile/`

## License

NoETL is licensed under the MIT License. See [LICENSE](../../LICENSE) for details.
