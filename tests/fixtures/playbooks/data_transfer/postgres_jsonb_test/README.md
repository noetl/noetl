# PostgreSQL JSONB Datatype Test

This test playbook validates PostgreSQL JSONB datatype operations and TRUNCATE command behavior in NoETL.

## What This Test Covers

### 1. JSONB Column Creation
- Creates a table with JSONB datatype columns
- Tests primary JSONB column and default JSONB column
- Creates GIN indexes on JSONB columns for performance
- Creates functional indexes on JSONB properties

### 2. JSONB Data Insertion
- Inserts complex nested JSON structures
- Tests proper JSON escaping and formatting
- Validates JSONB casting with `::jsonb` operator

### 3. JSONB Query Operations
Tests various PostgreSQL JSON operators:
- `->` operator: Get JSON object field
- `->>` operator: Get JSON object field as text
- `@>` operator: Contains operator for JSONB matching
- Nested property access with chained operators
- Filtering by JSONB properties

### 4. JSONB Update Operations
- `jsonb_set()` function: Update nested properties
- `||` operator: Merge/concatenate JSONB objects
- Adding new properties to existing JSONB

### 5. TRUNCATE Command Testing
- Tests TRUNCATE TABLE command execution
- Validates table is properly truncated (count = 0)
- Tests TRUNCATE error handling (non-existent table)
- Verifies error reporting for failed TRUNCATE operations

## Expected Behavior

### Successful Operations
1. Table creation with JSONB columns
2. GIN index creation on JSONB columns
3. Insert 3 rows with complex JSON structures
4. Query JSONB data with various operators
5. Update JSONB nested properties
6. TRUNCATE table successfully
7. Proper error reporting for failed TRUNCATE

### TRUNCATE Command Behavior
The test includes a deliberate failure case (`test_truncate_cascade` step) that attempts to truncate a non-existent table. This tests:
- Whether postgres plugin properly catches TRUNCATE errors
- Whether errors are reported in the result status
- Whether workflow handles postgres command failures correctly

## Known Issues

### Issue: TRUNCATE Command Not Reporting Failures
**Status**: Under Investigation

**Description**: The TRUNCATE TABLE command may not properly report failures when:
- Table doesn't exist
- User lacks permissions
- Table has foreign key constraints without CASCADE

**Expected Behavior**:
- Command should fail with error status
- Error message should be included in result
- Workflow should detect the failure

**Current Behavior**:
- TRUNCATE may execute silently without error
- Result status may show 'success' even when table doesn't exist
- No error message in result

**Root Cause Investigation**:
The postgres plugin's `execution.py` handles command execution in a try-catch block:

```python
async with conn.transaction():
    async with conn.cursor() as cursor:
        await cursor.execute(cmd)
        # ...
except Exception as cmd_error:
    results[f"command_{i}"] = {
        "status": "error",
        "message": str(cmd_error)
    }
```

Possible causes:
1. PostgreSQL may not raise exceptions for some TRUNCATE failures
2. Transaction context may suppress certain errors
3. Cursor rowcount may be 0 for both success and failure cases

**Workaround**:
For critical TRUNCATE operations:
```yaml
command: |
  -- Verify table exists before truncate
  DO $$
  BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables 
               WHERE table_name = 'your_table') THEN
      TRUNCATE TABLE your_table;
    ELSE
      RAISE EXCEPTION 'Table does not exist';
    END IF;
  END $$;
```

## Running the Test

```bash
# Register the playbook
task register-test-playbook NAME=postgres_jsonb_test

# Execute the playbook
task test-playbook NAME=postgres_jsonb_test

# Or run full test
task test-postgres-jsonb-full
```

## Validation Points

The test validates:
1. ✅ JSONB column accepts complex JSON structures
2. ✅ GIN indexes created successfully
3. ✅ JSON operators work correctly
4. ✅ Nested property access works
5. ✅ JSONB update operations work
6. ✅ TRUNCATE command executes
7. ⚠️  TRUNCATE error reporting (under investigation)

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
  }
}
```

## Related Files
- `postgres_jsonb_test.yaml` - Main test playbook
- `/noetl/plugin/tools/postgres/execution.py` - Postgres execution logic
- `/noetl/plugin/tools/postgres/command.py` - SQL command parsing
