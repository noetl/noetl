# Variable Management API Test Playbook

This directory contains test fixtures for validating the Variable Management API endpoints.

## Purpose

Tests the complete lifecycle of execution-scoped variables:
- Variable creation via declarative `vars` blocks
- External variable injection via REST API
- Variable retrieval with metadata tracking
- Variable deletion and cleanup

## Files

- **test_vars_api.yaml** - Test playbook that creates initial variables and validates API access

## Test Playbook Structure

The playbook demonstrates:

1. **Variable Extraction** - Uses `vars` block to extract values from step results:
   ```yaml
   vars:
     test_user_id: "{{ result.user_id }}"
     test_username: "{{ result.username }}"
     test_score: "{{ result.score }}"
     test_metadata: "{{ result.metadata }}"
   ```

2. **Execution Pause** - 5-second sleep to allow external API testing during execution

3. **Variable Access** - Verifies extracted variables are accessible via `{{ vars.* }}` templates

## API Endpoints Tested

Test script validates all four Variable Management API endpoints:

- `GET /api/vars/{execution_id}` - List all variables with metadata
- `GET /api/vars/{execution_id}/{var_name}` - Get specific variable (increments access_count)
- `POST /api/vars/{execution_id}` - Inject new variables
- `DELETE /api/vars/{execution_id}/{var_name}` - Delete variable

## Running Tests

Execute the complete test suite:

```bash
./tests/scripts/test_vars_api.sh
```

The test script:
1. Registers the playbook
2. Executes it (creates 4 variables via vars block)
3. Waits 8 seconds for processing
4. Runs 8 validation tests against the API
5. Reports pass/fail for each test

## Expected Variables

**From vars block:**
- `test_user_id` - Integer value 999
- `test_username` - String "api_tester"
- `test_score` - Integer value 85
- `test_metadata` - Dictionary with created/source fields

**From API injection:**
- `api_injected_var` - Test value from external script
- `api_counter` - Counter value (later deleted)
- `api_config` - Configuration object

## Variable Metadata

Each variable tracks:
- `value` - The actual variable value (JSON-serializable)
- `type` - Variable type (user_defined, step_result, computed, iterator_state)
- `source_step` - Step that created/updated the variable
- `created_at` - Creation timestamp (UTC)
- `accessed_at` - Last access timestamp (UTC)
- `access_count` - Number of reads via GET endpoint

## Database Verification

Check stored variables directly:

```bash
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT var_name, var_type, source_step, access_count 
   FROM noetl.vars_cache 
   WHERE execution_id = <EXECUTION_ID> 
   ORDER BY created_at;"
```

## Integration with Playbooks

Variables created via API are immediately accessible in playbook steps:

```yaml
- step: use_injected_var
  tool: python
  args:
    external_value: "{{ vars.api_injected_var }}"
  code: |
    def main(external_value):
      print(f"Using value from API: {external_value}")
```

## Use Cases

This test validates common patterns:
- **CI/CD Integration** - External systems inject configuration via API
- **Manual Intervention** - Operators provide runtime values during execution
- **Debugging** - Inspect variable state without modifying playbook code
- **Dynamic Configuration** - Change behavior mid-execution via API calls
