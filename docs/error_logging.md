# Error Logging in NoETL

This document describes the error logging functionality in NoETL, which allows for capturing and storing detailed information about errors that occur during template rendering and other operations.

## Overview

NoETL includes a dedicated `error_log` table in the NoETL meta schema that stores comprehensive information about errors, including:

- Error type and message
- Execution context (execution_id, step_id, step_name)
- Template information (template string, context data)
- Stack trace
- Input and output data
- Severity
- Resolution status and notes

This functionality is particularly useful for debugging template rendering errors, which can be difficult to diagnose without detailed context information.

## Error Log Table Schema

The `error_log` table has the following schema:

```sql
CREATE TABLE IF NOT EXISTS noetl.error_log (
    error_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_type VARCHAR(50),
    error_message TEXT,
    execution_id VARCHAR,
    step_id VARCHAR,
    step_name VARCHAR,
    template_string TEXT,
    context_data JSONB,
    stack_trace TEXT,
    input_data JSONB,
    output_data JSONB,
    severity VARCHAR(20) DEFAULT 'error',
    resolved BOOLEAN DEFAULT FALSE,
    resolution_notes TEXT,
    resolution_timestamp TIMESTAMP
)
```

Indexes are created on `timestamp`, `error_type`, `execution_id`, and `resolved` columns for efficient querying.

## Logging Errors

Errors are automatically logged to the `error_log` table when they occur during template rendering. The following error types are currently logged:

- `template_rendering`: Errors that occur when rendering Jinja2 templates
- `sql_template_rendering`: Errors that occur when rendering SQL templates

You can also log errors manually using the `log_error` method of the `DatabaseSchema` class:

```python
from noetl.schema import DatabaseSchema

db_schema = DatabaseSchema()
db_schema.log_error(
    error_type="custom_error",
    error_message="An error occurred",
    execution_id="execution_123",
    step_id="step_456",
    step_name="my_step",
    template_string="Template that caused the error",
    context_data={"key": "value"},
    stack_trace="Stack trace of the error",
    input_data={"input": "data"},
    output_data={"output": "data"},
    severity="error"
)
```

## Querying Errors

You can query errors from the `error_log` table using the `get_errors` method of the `DatabaseSchema` class:

```python
from noetl.schema import DatabaseSchema

db_schema = DatabaseSchema()

# Get all errors
all_errors = db_schema.get_errors()

# Get errors of a specific type
template_errors = db_schema.get_errors(error_type="template_rendering")

# Get errors for a specific execution
execution_errors = db_schema.get_errors(execution_id="execution_123")

# Get unresolved errors
unresolved_errors = db_schema.get_errors(resolved=False)

# Get errors with pagination
paginated_errors = db_schema.get_errors(limit=10, offset=20)
```

You can also query the `error_log` table directly using SQL:

```sql
-- Get all errors
SELECT * FROM noetl.error_log ORDER BY timestamp DESC;

-- Get errors of a specific type
SELECT * FROM noetl.error_log WHERE error_type = 'template_rendering' ORDER BY timestamp DESC;

-- Get errors for a specific execution
SELECT * FROM noetl.error_log WHERE execution_id = 'execution_123' ORDER BY timestamp DESC;

-- Get unresolved errors
SELECT * FROM noetl.error_log WHERE resolved = FALSE ORDER BY timestamp DESC;
```

