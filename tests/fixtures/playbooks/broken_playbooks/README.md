# Broken Playbooks - Test Fixtures

This directory contains intentionally broken playbook examples used for testing NoETL's validation and error handling capabilities.

## Overview

These playbooks are designed to fail validation or execution for specific reasons, helping to verify that NoETL properly detects and reports errors. They are used in unit tests and integration tests to ensure robust error handling.

## Playbooks

### should_error_tool_is_required.yaml

**Purpose**: Tests validation of the `tool` field requirement at the step level.

**Expected Error**: The `end` step is missing the required `tool` field, which should trigger a validation error during playbook registration or execution.

**Error Details**:
- **Step**: `end`
- **Issue**: No `tool` field defined
- **Expected Behavior**: NoETL should reject this playbook with a validation error indicating that the `tool` field is required for all workflow steps

**Workflow Structure**:
1. **start** - Initialize with python tool (valid)
2. **insert_report** - Postgres insert operation with intentionally misplaced `command` field (invalid - indentation error)
3. **end** - Missing tool definition entirely (invalid - tool is required)

**Additional Issues**:
- Line 30: `command:` is indented outside the `tool` block, making it a sibling of `tool` rather than a child
- Line 32: **YAML syntax error**: `-step:` should be `- step:` (missing space after dash)
  - This causes YAML parser to treat it as a dict `{'-step': 'end'}` instead of a list item
  - Results in 3 Pydantic validation errors (str, list[str], list[dict]) when trying to parse the `next` field

**Validation Errors** (actual):
1. `workflow.1.next` - Multiple type validation errors due to YAML parsing `{'-step': 'end'}` as dict instead of list
2. `workflow.2.tool` - Missing required field `tool` in the `end` step

**Use Cases**:
- Testing DSL validation logic
- Verifying error message clarity
- Integration testing of playbook registration endpoint
- CI/CD validation pipeline testing

## Test Usage

### Integration Testing

```python
def test_playbook_validation_tool_required():
    """Test that playbook validation rejects steps without tool field."""
    with pytest.raises(ValidationError) as exc_info:
        register_playbook("tests/fixtures/playbooks/broken_playbooks/should_error_tool_is_required.yaml")
    
    assert "tool is required" in str(exc_info.value).lower()
    assert "end" in str(exc_info.value)  # Should mention the problematic step
```

### CLI Testing

```bash
# Attempt to register the broken playbook (should fail)
noetlctl catalog register tests/fixtures/playbooks/broken_playbooks/should_error_tool_is_required.yaml

# Expected output (actual Pydantic validation errors):
# Failed to execute playbook. 4 validation errors for Playbook
# workflow.1.next.str
#   Input should be a valid string [type=string_type, input_value={'-step': 'end'}, input_type=dict]
# workflow.1.next.list[str]
#   Input should be a valid list [type=list_type, input_value={'-step': 'end'}, input_type=dict]
# workflow.1.next.list[dict[str,any]]
#   Input should be a valid list [type=list_type, input_value={'-step': 'end'}, input_type=dict]
# workflow.2.tool
#   Field required [type=missing, input_value={'step': 'end', 'desc': '...'}, input_type=dict]
```

### REST API Testing

```bash
# POST to catalog registration endpoint (should return 422 Unprocessable Entity)
curl -X POST http://localhost:8082/api/catalog/register \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "tests/fixtures/playbooks/broken_playbooks/should_error_tool_is_required.yaml"
  }'

# Expected response (Pydantic validation errors):
{
  "detail": [
    {
      "type": "string_type",
      "loc": ["body", "workflow", 1, "next", "str"],
      "msg": "Input should be a valid string",
      "input": {"-step": "end"}
    },
    {
      "type": "list_type",
      "loc": ["body", "workflow", 1, "next", "list[str]"],
      "msg": "Input should be a valid list",
      "input": {"-step": "end"}
    },
    {
      "type": "list_type",
      "loc": ["body", "workflow", 1, "next", "list[dict[str,any]]"],
      "msg": "Input should be a valid list",
      "input": {"-step": "end"}
    },
    {
      "type": "missing",
      "loc": ["body", "workflow", 2, "tool"],
      "msg": "Field required",
      "input": {"step": "end", "desc": "End data transfer test pipeline"}
    }
  ]
}
```

## Error Categories Tested

### 1. Missing Required Fields
- **Field**: `tool`
- **Level**: Step-level validation
- **Detection**: Pre-execution (during registration/parsing)

### 2. Field Placement Errors
- **Field**: `command`
- **Issue**: Defined outside `tool` block
- **Detection**: YAML parsing/DSL validation

### 3. Syntax Errors
- **Issue**: Malformed YAML list syntax (`-step:` vs `- step:`)
- **Detection**: YAML parser

## Python Tool Pattern (v2)

Even in broken playbooks, valid python tools should follow v2 structure:

```yaml
tool:
  kind: python
  auth: {}      # Optional: authentication references
  libs: {}      # Required: library imports (empty if none needed)
  args: {}      # Required: input arguments (empty if none needed)
  code: |
    # Direct code execution - no def main() wrapper
    result = {"status": "initialized"}
```

The `start` step in this playbook demonstrates correct v2 python tool syntax, while other steps contain intentional errors.

## Validation Rules

NoETL enforces these validation rules that these playbooks help test:

1. **All workflow steps must have a `tool` field**
   - Type: Required field validation
   - Scope: Every step in workflow array

2. **Tool-specific fields must be inside the `tool` block**
   - Fields: `code`, `command`, `query`, `endpoint`, etc.
   - Scope: Step-level structure validation

3. **YAML syntax must be valid**
   - Lists require `- ` prefix with space
   - Indentation must be consistent
   - Keys and values properly formatted

4. **Step references must exist**
   - All `next.step` references must point to valid step names
   - No circular dependencies

## Expected Validation Behavior

When NoETL encounters these playbooks, it should:

1. **Parse YAML**: Detect syntax errors early
2. **Validate Structure**: Check required fields and nesting
3. **Validate References**: Verify step names and paths exist
4. **Report Clearly**: Provide actionable error messages with:
   - Problematic step name
   - Missing/misplaced field
   - Line number (when possible)
   - Suggested fix

## Adding New Broken Playbooks

When adding new broken playbooks to this directory:

1. **Name clearly**: `should_error_<reason>.yaml`
2. **Document intent**: Add to this README with expected error
3. **Add comments**: Inline comments explaining the intentional error
4. **Create test**: Write corresponding test case
5. **Single error**: Each playbook should test one primary error type

## Related Tests

These playbooks are used in:
- `tests/test_playbook_validation.py` - DSL validation tests
- `tests/test_catalog_registration.py` - Registration error handling
- `tests/test_server_api.py` - REST API error responses
- Integration test suites verifying error detection

## References

- [NoETL DSL Specification](../../../../documentation/docs/reference/dsl-spec.md)
- [Playbook Validation Guide](../../../../documentation/docs/features/validation.md)
- [Error Handling Documentation](../../../../documentation/docs/reference/error-handling.md)
- [Python Tool Pattern v2](../postgres_excel_gcs_test/README.md#python-tool-pattern-v2)
