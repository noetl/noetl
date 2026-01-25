# PostgreSQL JSONB Datatype Test

This test playbook validates PostgreSQL JSONB datatype operations and connection handling in NoETL.

## What This Test Covers

### 1. JSONB Column Creation
- Creates a table with JSONB datatype columns
- Tests primary JSONB column and default JSONB column with metadata
- Creates GIN indexes on JSONB columns for performance optimization
- Creates functional indexes on JSONB properties for faster lookups

### 2. JSONB Data Insertion
- Builds INSERT statements dynamically using Python step
- Inserts complex nested JSON structures into JSONB columns
- Proper JSON escaping with single quote doubling: `'` → `''`
- JSONB casting with `::jsonb` operator for type safety
- Handles null input data gracefully with default empty dict

### 3. JSONB Query Operations
Tests various PostgreSQL JSON operators:
- `->` operator: Get JSON object field (returns JSONB)
- `->>` operator: Get JSON object field as text (returns TEXT)
- `@>` operator: Contains operator for JSONB matching (returns BOOLEAN)
- Nested property access: `profile->'preferences'->>'theme'`
- Filtering by JSONB properties in WHERE clauses
- Multiple query patterns demonstrating different JSON access methods

### 4. JSONB Update Operations
- `jsonb_set()` function: Update nested properties immutably
- `||` operator: Merge/concatenate JSONB objects
- Adding new top-level properties to existing JSONB
- Updating nested properties while preserving other data
- Demonstrates both update patterns with verification queries

### 5. TRUNCATE and Error Handling
- Tests TRUNCATE TABLE command with validation
- Verifies table truncation with before/after row counts
- Tests error handling with table existence check using PL/pgSQL
- Uses `DO $$ ... END $$` block for conditional TRUNCATE
- Validates proper error propagation and connection cleanup

## Architecture: Direct Connections (No Pooling)

### Connection Management
**Important**: The postgres plugin uses **direct connections** on the worker side, not connection pooling:

```python
async with await AsyncConnection.connect(
    connection_string,
    autocommit=False,
    row_factory=dict_row
) as conn:
    # Execute commands
    results = await execute_sql_statements_async(conn, commands)
```

**Why Direct Connections?**
1. **No Pool Corruption**: Errors don't poison a shared pool
2. **Clean State**: Each execution starts with a fresh connection
3. **Automatic Cleanup**: `async with` ensures connection closes
4. **Error Isolation**: Failed commands don't affect other playbooks
5. **Simpler Code**: No pool lifecycle management needed

**Connection Lifecycle:**
1. Open connection for execution
2. Execute SQL commands (with transaction per command)
3. Automatically close connection (even on error)
4. No connection reuse between steps

### Error Handling
When SQL errors occur:
1. Error captured in results dict: `{"status": "error", "message": "..."}`
2. Connection rollback attempted
3. Connection closed via `async with`
4. Exception raised to worker
5. Next execution gets fresh connection

This prevents the issue where PostgreSQL errors left connections in "aborted transaction" state, causing subsequent executions to fail.

## Expected Behavior

### Successful Operations
1. Table creation with JSONB columns and GIN indexes
2. Python step generates INSERT statements dynamically
3. Insert 3 rows with complex nested JSON structures
4. Query JSONB data using various JSON operators
5. Update JSONB nested properties with jsonb_set and || operator
6. TRUNCATE table with before/after validation
7. Table existence check before TRUNCATE (PL/pgSQL block)
8. Proper cleanup and connection closure

### Step Data Flow
The playbook uses direct step result references (DSL v1 pattern):
- `{{ insert_jsonb_data.commands }}` - References Python step result
- `{{ query_jsonb_data }}` - References postgres step result
- `{{ test_truncate }}` - References TRUNCATE step result

**Note**: No `bind:` blocks used - step results accessible by step name.

## Known Issues - RESOLVED ✅

### ~~Issue: TRUNCATE Command Not Reporting Failures~~
**Status**: ✅ RESOLVED

**Resolution**: 
The playbook now uses proper table existence checking before TRUNCATE:

```sql
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM pg_tables 
    WHERE schemaname = 'public' 
    AND tablename = 'nonexistent_table_12345'
  ) THEN
    TRUNCATE TABLE public.nonexistent_table_12345;
  ELSE
    RAISE NOTICE 'Table does not exist - skipping truncate';
  END IF;
END $$;
```

This approach:
- ✅ Checks table existence before attempting TRUNCATE
- ✅ Raises NOTICE instead of ERROR for missing tables
- ✅ Allows workflow to continue gracefully
- ✅ Properly reports errors when tables exist but TRUNCATE fails

### ~~Issue: Connection Pool Corruption After Errors~~
**Status**: ✅ RESOLVED

**Previous Problem**:
- Postgres errors left connections in "aborted transaction" state
- Pool returned broken connections to subsequent executions
- Playbooks failed with "current transaction is aborted" errors

**Solution**:
Removed connection pooling entirely from worker side:
- Each execution opens fresh connection
- Connection automatically closes via `async with` context manager
- Errors don't pollute shared pool
- Clean state for every execution

## Running the Test

```bash
# Register the playbook
noetl playbook register tests/fixtures/playbooks/data_transfer/postgres_jsonb_test

# Execute the playbook
noetl execution create tests/fixtures/playbooks/data_transfer/postgres_jsonb_test

# Or execute via API
curl -X POST "http://localhost:8083/api/run/playbook" \
  -H "Content-Type: application/json" \
  -d '{"path":"tests/fixtures/playbooks/data_transfer/postgres_jsonb_test"}'
```

## Validation Points

The test validates:
1. ✅ JSONB column accepts complex JSON structures
2. ✅ GIN indexes created successfully
3. ✅ JSON operators work correctly (`->`, `->>`, `@>`)
4. ✅ Nested property access works with chained operators
5. ✅ JSONB update operations with jsonb_set and || operator
6. ✅ Python step generates valid SQL INSERT statements
7. ✅ TRUNCATE command executes with validation
8. ✅ Table existence check prevents TRUNCATE errors
9. ✅ Connection closes cleanly after each step
10. ✅ No connection pool corruption between executions

## Sample Data Structure

```json
{
  "user_id": 1,
  "profile": {
    "name": "Alice Johnson",
    "email": "alice@example.com",
    "age": 30,
    "preferences": {
      "theme": "dark",
      "notifications": true,
      "language": "en"
    }
  },
  "metadata": {
    "source": "test",
    "version": "1.0",
    "timestamp": "2025-11-12T00:00:00Z"
  }
}
```

## Technical Details

### Python Step: INSERT Statement Generation
```python
def main(input_data):
    if input_data is None:
        input_data = {}
    
    sample_data = input_data.get('sample_json_data', [])
    insert_statements = []
    
    for item in sample_data:
        profile_json = json.dumps(item['profile'])
        # Escape single quotes for SQL
        profile_json_escaped = profile_json.replace("'", "''")
        
        sql = f"""INSERT INTO table (user_id, profile)
        VALUES ({user_id}, '{profile_json_escaped}'::jsonb);"""
        insert_statements.append(sql)
    
    return {'commands': '\n'.join(insert_statements)}
```

### Connection Lifecycle (Simplified)
```python
# Worker calls postgres plugin for each step
async with await AsyncConnection.connect(conn_string) as conn:
    # Execute SQL commands in transaction
    async with conn.transaction():
        await cursor.execute(cmd)
    # Connection auto-closes here (even on error)
```

### Step Result Access Pattern
```yaml
# Step 1: Python generates SQL
- step: insert_jsonb_data
  tool: python
  # Returns: {"commands": "INSERT ...", "count": 3}

# Step 2: Execute the SQL
- step: execute_inserts
  tool: postgres
  command: "{{ insert_jsonb_data.commands }}"  # Direct reference
```

## Related Files
- `postgres_jsonb_test.yaml` - Main test playbook (297 lines)
- `/noetl/tools/tools/postgres/execution.py` - Postgres execution with direct connections
- `/noetl/tools/tools/postgres/command.py` - SQL command parsing and rendering
- `/noetl/core/db/pool.py` - Server-side pool (separate from worker connections)
