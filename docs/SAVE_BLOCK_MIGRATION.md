# Save Block Migration Guide

## Overview

The save block configuration has been standardized to use `storage:` attribute instead of `type:` to avoid confusion with action types. Additionally, both `data:` and `args:` are supported for specifying save parameters.

## Changes

### Before (Old Format - NOT SUPPORTED)
```yaml
save:
  type: postgres        # ❌ Wrong - conflicts with action type
  data:
    field1: value1
  auth: credential_ref
  table: my_table
```

### After (New Format - CORRECT)
```yaml
save:
  storage: postgres     # ✅ Correct - clearly indicates storage backend
  args:                 # ✅ Preferred - but 'data' also works
    field1: value1
  auth: credential_ref
  table: my_table
```

## Supported Formats

### Option 1: Using `args` (Recommended)
```yaml
save:
  storage: postgres
  args:
    id: "{{ execution_id }}"
    name: "{{ item.name }}"
  auth: "{{ workload.pg_auth }}"
  table: public.my_table
  mode: upsert
  key: id
```

### Option 2: Using `data` (Also Supported)
```yaml
save:
  storage: postgres
  data:
    id: "{{ execution_id }}"
    name: "{{ item.name }}"
  auth: "{{ workload.pg_auth }}"
  table: public.my_table
  mode: upsert
  key: id
```

## Storage Types

The `storage:` attribute can be:

1. **String (Flat Structure)**
   ```yaml
   save:
     storage: postgres
     args: {...}
   ```

2. **Dict (Nested Structure)**
   ```yaml
   save:
     storage:
       type: postgres
       table: my_table
     args: {...}
   ```

Supported storage backends:
- `postgres` - PostgreSQL database
- `duckdb` - DuckDB database  
- `python` - Python function execution
- `http` - HTTP API call
- `event` - Event log (default if not specified)

## Iterator + Save Pattern

When using save blocks inside iterator tasks:

```yaml
- step: process_items
  type: iterator
  collection: "{{ workload.items }}"
  element: item
  mode: sequential
  task:
    type: python
    code: |
      def main(input_data):
          return {'result': input_data}
    save:
      storage: postgres
      args:
        id: "{{ execution_id }}:{{ item.id }}"
        data: "{{ item }}"
      auth: "{{ workload.pg_auth }}"
      table: public.results
      mode: upsert
      key: id
```

**Key Points:**
- Save block is nested inside the `task:` block
- Each iteration saves its result as a **single transaction**
- If save fails, the entire iteration fails
- Access iterator variables via `{{ item.field }}`
- Access task result via `{{ this.field }}`

## Migration Checklist

To migrate existing playbooks:

1. ✅ Change `type:` to `storage:` in all save blocks
2. ✅ Optionally change `data:` to `args:` (both work)
3. ✅ Verify credential references use correct format
4. ✅ Test that data saves correctly
5. ✅ Re-register updated playbooks

## Code Changes

The save configuration parser (`noetl/plugin/save/config.py`) now:
- Looks for `storage:` attribute (line 102)
- Supports both `args:` and `data:` (lines 111-113)
- Defaults to `'event'` storage if not specified
- Handles both flat string and nested dict formats

## Testing

Test your save blocks with:

```bash
# Register updated playbook
.venv/bin/noetl register path/to/playbook.yaml --host localhost --port 8083

# Execute with test data
.venv/bin/noetl execute playbook "path/to/playbook" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' --merge

# Verify data saved
psql -h localhost -p 54321 -U demo -d demo_noetl \
  -c "SELECT * FROM your_table;"
```

## Breaking Changes

⚠️ **BREAKING CHANGE**: Using `type:` in save blocks will cause the save to be interpreted as an `event` save (logging only) instead of database save.

**Migration Required**: All save blocks must use `storage:` instead of `type:`.

## Examples

See working examples in:
- `tests/fixtures/playbooks/iterator_save_test.yaml`
- `tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml`
- `tests/fixtures/playbooks/save_storage_test/`

## Reference

For complete save block specification, see:
- `docs/playbook_specification.md`
- `noetl/plugin/save/config.py` - Configuration extraction logic
- `noetl/plugin/save/executor.py` - Save execution logic
