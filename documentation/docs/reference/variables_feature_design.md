# Variables Feature Design

## Overview

Add dynamic variable assignment and access during playbook execution. Variables are execution-scoped, can be set/updated at any point in the workflow, and persist in the database for the duration of the execution.

## Implementation Status

✅ **COMPLETED** - Vars block feature is fully implemented and tested.

**Key Features**:
- Declarative variable extraction from step results via `vars` block
- Template-based value extraction using `{{ result.field }}` syntax
- Automatic storage in `transient` table with `var_type='step_result'`
- Access in subsequent steps via `{{ vars.var_name }}` templates
- Direct step name references (no wrapper objects needed)
- **REST API access** for variable management (no direct worker database access)

## Architecture

**Database Access Pattern**: 
- ✅ **Workers**: Access variables via REST API (`/api/vars/{execution_id}`)
- ✅ **Server**: Direct database access via `TransientVars` service using pool connections
- ❌ **Workers**: NO direct PostgreSQL connections for variables

**Implementation Files**:
- Database schema: `noetl/database/ddl/postgres/schema_ddl.sql`
- Service layer: `noetl/worker/transient.py` (uses `get_pool_connection()`)
- REST API: `noetl/server/api/vars/endpoint.py`
- Pydantic models: `noetl/server/api/vars/schema.py`

## Table Design: `transient`

**Naming Pattern**: Following `auth_cache` pattern for consistency

**Implementation**: Table created as `transient` in schema

**Rationale**:
- Follows `auth_cache` naming convention
- Cache-like behavior (execution-scoped, ephemeral)
- Clear purpose: runtime variable storage
- Consistent with other *_cache tables

## Schema Design

```sql
CREATE TABLE noetl.transient (
  execution_id BIGINT NOT NULL,
  var_name TEXT NOT NULL,
  var_type TEXT NOT NULL DEFAULT 'user_defined',
  var_value JSONB NOT NULL,
  source_step TEXT,
  access_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (execution_id, var_name)
);

CREATE INDEX idx_transient_execution ON noetl.transient(execution_id);
CREATE INDEX idx_transient_source ON noetl.transient(source_step);
CREATE INDEX idx_transient_type ON noetl.transient(var_type);

-- Type constraint
ALTER TABLE noetl.transient 
ADD CONSTRAINT transient_type_check 
CHECK (var_type IN ('user_defined', 'step_result', 'computed', 'iterator_state'));
```

### Column Descriptions

- **execution_id**: Execution isolation (BIGINT for Snowflake ID compatibility)
- **var_name**: Variable identifier (used in templates as `{{ vars.var_name }}`)
- **var_type**: Variable classification:
  - `user_defined`: Explicitly set via API (future)
  - `step_result`: ✅ **IMPLEMENTED** - Extracted from step results via `vars` block
  - `computed`: Calculated from expressions (future)
  - `iterator_state`: Loop iteration metadata (future)
- **var_value**: JSON value (supports strings, numbers, objects, arrays, booleans, null)
- **source_step**: Which step created/updated the variable (for debugging/audit)
- **access_count**: Number of times variable was read (tracking usage)
- **created_at**: First assignment timestamp
- **accessed_at**: Last access timestamp (updated on read)

### Implementation Notes

**Design Decisions**:

1. **Template Syntax**: Use `{{ result.field }}` for current step, not `{{ STEP.step_name.field }}`
   - Simpler and more intuitive
   - Consistent with other template namespaces (`workload`, `vars`)
   - Less typing, cleaner playbook YAML

2. **var_type**: Store extracted variables as `step_result`
   - Aligns with existing database constraint
   - Clear semantic meaning: variable came from step execution result
   - Distinguishes from future `user_defined` (API-set) variables

3. **Processing Location**: Server-side in orchestrator after `step_completed` event
   - Has access to full eval_ctx with all step results
   - Centralized variable storage logic
   - Worker remains stateless

4. **eval_ctx Structure**: Step results stored by step name with `data` field normalized
   - `eval_ctx["step_name"]` contains the step's return value directly
   - `eval_ctx["result"]` points to current step for vars block processing
   - Server extracts `.data` field if present in step result envelope

## DSL Syntax (Implemented)

### 1. Variable Extraction from Step Results

The `vars` block at the step level extracts values from the current step's result **after execution completes**:

```yaml
workflow:
- step: fetch_data
  desc: Query database and extract variables
  tool: postgres
  query: "SELECT user_id, email, created_at FROM users WHERE status = 'active' LIMIT 1"
  vars:
    # Use {{ result.field }} to access current step's output
    user_id: "{{ result[0].user_id }}"
    user_email: "{{ result[0].email }}"
    signup_date: "{{ result[0].created_at }}"
  next:
  - step: process_user

- step: process_user
  desc: Use extracted variables in subsequent step
  tool: python
  code: |
    def main(user_id, user_email):
      return {"status": "processed", "user": user_id}
  args:
    # Access stored variables via {{ vars.var_name }}
    user_id: "{{ vars.user_id }}"
    user_email: "{{ vars.user_email }}"
  next:
  - step: notify
```

### 2. Template Access Patterns

**Within vars block (current step result)**:
- `{{ result.field }}` - Direct access to current step's output
- `{{ result.users[0].name }}` - Array/nested access
- `{{ result.metadata.count }}` - Object navigation

**In subsequent steps (stored variables)**:
```yaml
- step: use_variables
  tool: http
  method: POST
  endpoint: "{{ vars.api_url }}"
  payload:
    user_id: "{{ vars.user_id }}"
    email: "{{ vars.user_email }}"
    last_result: "{{ vars.last_result }}"
  next:
  - when: "{{ vars.counter >= 10 }}"
    then:
    - step: end
    data:
      final_count: "{{ vars.counter }}"
```

### 3. Variables in Iterators

```yaml
- step: process_items
  desc: Track progress in loop
  type: iterator
  collection: "{{ workload.items }}"
  element: item
  mode: sequential
  vars:
    # Auto-populated by iterator
    # vars.process_items_index: current iteration index
    # vars.process_items_item: current item
    # vars.process_items_count: total items processed
    processed_count: 0  # User-defined counter
  task:
    type: python
    code: |
      def main(item):
        return {"id": item["id"], "status": "done"}
    vars:
      # Update counter after each iteration
      processed_count: "{{ vars.processed_count + 1 }}"
      last_item_id: "{{ item.id }}"
```

### 4. Pre-Step and Post-Step Variables (Future Enhancement - NOT IMPLEMENTED)

**Note**: This is a proposed future enhancement. The currently implemented `vars` block only supports post-execution extraction (equivalent to the "after" block below).

```yaml
- step: complex_operation
  desc: Variables before and after execution
  vars:
    # Pre-execution variables (evaluated before step runs)
    before:
      operation_start: "{{ now() }}"
      attempt_number: "{{ vars.attempt_number | default(1) }}"
    
    # Post-execution variables (evaluated after step completes)
    after:
      operation_end: "{{ now() }}"
      operation_duration: "{{ vars.operation_end - vars.operation_start }}"
      operation_result: "{{ result }}"  # Note: Use 'result' not 'this.data'
      attempt_number: "{{ vars.attempt_number + 1 }}"
  
  tool: python
  code: |
    def main():
      # Step execution
      return {"status": "success"}
```

## API Endpoints

Variables are managed through REST API endpoints. Workers access variables via HTTP calls to the server.

### List All Variables (GET)

```http
GET /api/vars/{execution_id}
```

**Response**:
```json
{
  "execution_id": 507861119290048685,
  "variables": {
    "user_id": {
      "value": 12345,
      "type": "step_result",
      "source_step": "fetch_user",
      "created_at": "2025-12-13T10:00:00Z",
      "accessed_at": "2025-12-13T10:01:00Z",
      "access_count": 5
    },
    "email": {
      "value": "user@example.com",
      "type": "step_result",
      "source_step": "fetch_user",
      "created_at": "2025-12-13T10:00:00Z",
      "accessed_at": "2025-12-13T10:00:30Z",
      "access_count": 2
    }
  },
  "count": 2
}
```

### Get Single Variable (GET)

```http
GET /api/vars/{execution_id}/{var_name}
```

**Response**:
```json
{
  "execution_id": 507861119290048685,
  "var_name": "user_id",
  "value": 12345,
  "type": "step_result",
  "source_step": "fetch_user",
  "created_at": "2025-12-13T10:00:00Z",
  "accessed_at": "2025-12-13T10:01:00Z",
  "access_count": 6
}
```

**Note**: Increments `access_count` and updates `accessed_at` timestamp.

### Set Multiple Variables (POST)

```http
POST /api/vars/{execution_id}
Content-Type: application/json

{
  "variables": {
    "config_timeout": 60,
    "retry_enabled": true,
    "admin_email": "admin@example.com"
  },
  "var_type": "user_defined",
  "source_step": "manual_config"
}
```

**Response**:
```json
{
  "execution_id": 507861119290048685,
  "variables_set": 3,
  "var_names": ["config_timeout", "retry_enabled", "admin_email"]
}
```

**Valid var_type values**: `user_defined`, `step_result`, `computed`, `iterator_state`

### Delete Variable (DELETE)

```http
DELETE /api/vars/{execution_id}/{var_name}
```

**Response**:
```json
{
  "execution_id": 507861119290048685,
  "var_name": "obsolete_var",
  "deleted": true
}
```

## Worker Access Pattern

Workers access variables via REST API, never directly via database connections.

**Example worker code**:

```python
import httpx

async def get_execution_variables(execution_id: int, server_url: str) -> dict:
    """
    Fetch all variables for execution from server API.
    
    Args:
        execution_id: Execution identifier
        server_url: NoETL server base URL (e.g., "http://noetl-server:8080")
    
    Returns:
        Dict mapping var_name to value: {var_name: value, ...}
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{server_url}/api/vars/{execution_id}"
        )
        response.raise_for_status()
        data = response.json()
        
        # Extract just the values (strip metadata)
        return {
            var_name: var_data["value"]
            for var_name, var_data in data["variables"].items()
        }

async def set_execution_variable(
    execution_id: int,
    var_name: str,
    var_value: any,
    server_url: str,
    source_step: str = None
) -> bool:
    """
    Set a single variable via server API.
    
    Args:
        execution_id: Execution identifier
        var_name: Variable name
        var_value: Variable value (any JSON-serializable type)
        server_url: NoETL server base URL
        source_step: Optional step name that set the variable
    
    Returns:
        True if successful
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/api/vars/{execution_id}",
            json={
                "variables": {var_name: var_value},
                "var_type": "user_defined",
                "source_step": source_step
            }
        )
        response.raise_for_status()
        return True
```

**Configuration**:
Workers need the server URL configured via environment variable:
```bash
export NOETL_SERVER_URL="http://noetl-server:8080"
# or
export NOETL_SERVER_URL="http://localhost:8080"
```

## Context Integration

### Template Context Structure

Variables accessible via `vars` namespace:

```python
{
  "workload": {...},        # Global playbook variables (read-only after start)
  "vars": {...},            # Dynamic execution variables (read-write)
  "execution_id": "...",
  "job": {...},
  "step_name": {...},       # Prior step results
  "results": {...}          # All step results map
}
```

### Priority Order

1. **vars**: Mutable execution variables (highest priority)
2. **step results**: Immutable step outputs
3. **workload**: Initial playbook variables (immutable)
4. **built-ins**: execution_id, job, etc.

### Example Template Resolution

```yaml
workload:
  base_url: "https://api.example.com"
  timeout: 30

workflow:
- step: setup
  vars:
    timeout: 60  # Overrides workload.timeout in vars namespace

- step: call_api
  tool: http
  endpoint: "{{ workload.base_url }}/users"  # Uses workload
  timeout: "{{ vars.timeout }}"               # Uses vars (60)
```

## Implementation Summary

### ✅ Completed Components

**1. Database Schema** (`noetl/database/ddl/postgres/schema_ddl.sql`)
- Table `noetl.transient` created with:
  - Primary key: `(execution_id, var_name)`
  - Columns: `var_type`, `var_value` (JSONB), `source_step`, `created_at`, `accessed_at`, `access_count`
  - CHECK constraint: `var_type IN ('user_defined', 'step_result', 'computed', 'iterator_state')`
  - Indexes on: `execution_id`, `var_type`, `source_step`

**2. Service Layer** (`noetl/worker/transient.py`)
- `TransientVars` class with methods:
  - `get_cached()` - Retrieve variable with access tracking
  - `set_cached()` - Store/update single variable
  - `get_all_vars()` - Bulk load all variables (flat dict)
  - `get_all_vars_with_metadata()` - Load with full metadata
  - `set_multiple()` - Batch insert/update
  - `delete_var()` - Remove single variable
  - `cleanup_execution()` - Delete all variables for execution
- **Database Access**: Uses `get_pool_connection()` from `noetl.core.db.pool`
- **Parameters**: Dict-based `%(param)s` pattern
- **Row Access**: `row_factory=dict_row` with `row["column"]` access

**3. REST API** (`noetl/server/api/vars/`)
- **Endpoints**:
  - `GET /api/vars/{execution_id}` - List all variables with metadata
  - `GET /api/vars/{execution_id}/{var_name}` - Get single variable
  - `POST /api/vars/{execution_id}` - Set multiple variables
  - `DELETE /api/vars/{execution_id}/{var_name}` - Delete variable
- **Pydantic Models** (`schema.py`):
  - `VariableListResponse`, `VariableValueResponse`
  - `SetVariablesRequest`, `SetVariablesResponse`
  - `DeleteVariableResponse`, `VariableMetadata`
- **Registration**: Router registered in `noetl/server/api/__init__.py`

**4. Orchestrator Integration**
- Variables processed in `noetl/server/api/run/orchestrator.py`
- `_process_step_vars()` function extracts values from step results
- Template rendering uses `{{ result.field }}` syntax
- Stores extracted variables with `var_type='step_result'`

**5. Template Context**
- Variables accessible via `{{ vars.var_name }}` in all Jinja2 templates
- Loaded into `eval_ctx['vars']` during context building
- Available alongside `workload`, step results, and built-ins

### Implementation Standards

**Database Pattern** (enforced):
```python
from noetl.core.db.pool import get_pool_connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

async with get_pool_connection() as conn:
    async with conn.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "INSERT INTO transient (var_name, var_value) VALUES (%(name)s, %(value)s)",
            {"name": "my_var", "value": Json({"data": 123})}
        )
        row = await cursor.fetchone()
        value = row["column_name"]  # Dict access
```

**Key Requirements**:
- ✅ ALL database queries use `get_pool_connection()`
- ✅ Dict parameters: `%(param)s` with `{"param": value}`
- ✅ Dict row access: `row["column"]` via `row_factory=dict_row`
- ✅ JSONB values: Use `Json(value)` adapter
- ❌ NO `get_async_db_connection()` usage
- ❌ NO tuple parameters `%s` with `(value,)`
- ❌ NO manual `commit()` calls (pool handles automatically)
  ```     
       Args:
           execution_id: Execution ID
           vars_config: Variables to set/update
           step_name: Source step name
           step_result: Step result for 'this' context
           jinja_env: Jinja2 environment for template rendering
       """
       from noetl.worker.transient import TransientVars
       from noetl.core.dsl.render import render_template
       
       # Load current vars for template context
       current_vars = await TransientVars.get_all_vars(execution_id)
       
       # Build context with vars + step result
       context = {
           "vars": current_vars,
           "this": step_result,
           "execution_id": execution_id
       }
       
       # Render and update each variable
       for var_name, var_value_template in vars_config.items():
           rendered_value = render_template(jinja_env, var_value_template, context)
           await TransientVars.set_cached(
               var_name=var_name,
               var_value=rendered_value,
               execution_id=execution_id,
               var_type='user_defined',
               source_step=step_name
           )
  ```

Get all variables for execution as flat dict. Returns: `{var_name: var_value, ...}`

  ```python
    @staticmethod
    async def delete_var(
        var_name: str,
        execution_id: int
    ) -> bool:
        """Delete single variable. Returns True if deleted."""
    
    @staticmethod
    async def cleanup_execution(execution_id: int) -> int:
        """Delete all variables for execution. Returns count deleted."""
  ```

**Additional API endpoints** (`noetl/server/api/vars/`):
- `endpoint.py`: REST API for external variable management
- `schema.py`: Pydantic models for API requests/responsesschema.py`: Pydantic models
### Phase 5: Iterator Integration

**Modify `noetl/tools/tools/iterator/executor.py`**:

1. Auto-populate iterator state variables:
   ```python
   from noetl.worker.transient import TransientVars
   
   # Set iterator state variables
   await TransientVars.set_cached(
       var_name=f"{step_name}_index",
       var_value=iteration_index,
       execution_id=execution_id,
       var_type="iterator_state",
       source_step=step_name
   )
   await TransientVars.set_cached(
       var_name=f"{step_name}_item",
       var_value=current_item,
       execution_id=execution_id,
       var_type="iterator_state",
       source_step=step_name
   )
   await TransientVars.set_cached(
       var_name=f"{step_name}_count",
       var_value=items_processed,
       execution_id=execution_id,
       var_type="iterator_state",
       source_step=step_name
   )
   ```

2. Process user-defined vars in each iteration using `update_execution_variables()`ntext()`:
   ```python
   async def build_rendering_context(...):
       base_ctx = {
           "workload": workload,
           "vars": await get_variables(execution_id),  # NEW
           "results": results,
           ...
       }
   ```

2. Create `update_execution_variables()` helper:
   ```python
   async def update_execution_variables(
       execution_id: int,
       vars_config: Dict[str, Any],
       step_name: str,
       step_result: Optional[Dict] = None
   ):
       """Process vars block and update database."""
   ```

### Phase 4: DSL Parser

**Modify `noetl/core/dsl/parse.py`**:

1. Add `vars` field to step schema validation
2. Support two formats:
   - Simple: `vars: {name: value}`
   - Advanced: `vars: {before: {...}, after: {...}}`

**Modify `noetl/server/api/broker/core.py`** (execution orchestrator):

1. Before step execution:
   ```python
   if "vars" in step and "before" in step["vars"]:
       await update_execution_variables(
           execution_id, 
           step["vars"]["before"], 
           step_name,
           None
       )
   ```

2. After step execution:
   ```python
   if "vars" in step:
       vars_config = step["vars"]
       if "after" in vars_config:
           await update_execution_variables(
               execution_id, 
               vars_config["after"], 
               step_name,
               step_result
           )
       elif isinstance(vars_config, dict):
           # Simple format (no before/after split)
           await update_execution_variables(
               execution_id, 
               vars_config, 
               step_name,
               step_result
           )
   ```

### Phase 5: Iterator Integration

**Modify `noetl/tools/tools/iterator/executor.py`**:

1. Auto-populate iterator state variables:
   ```python
   await set_variables_bulk(execution_id, {
       f"{step_name}_index": iteration_index,
       f"{step_name}_item": current_item,
       f"{step_name}_count": items_processed,
       f"{step_name}_total": total_items
   }, var_type="iterator_state", source_step=step_name)
   ```

2. Process user-defined vars in each iteration

### Phase 6: Testing

**Test files to create**:
- `tests/fixtures/playbooks/vars_test/vars_simple.yaml`
- `tests/fixtures/playbooks/vars_test/vars_iterator.yaml`
- `tests/fixtures/playbooks/vars_test/vars_conditional.yaml`
- `tests/unit/test_vars_service.py`
- `tests/integration/test_vars_api.py`

## Usage Examples

### Example 1: Counter and State Tracking

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: batch_processor
  path: examples/vars/batch_processor

workload:
  batch_size: 100
  max_retries: 3

workflow:
- step: start
  desc: Initialize processing state
  vars:
    processed: 0
    failed: 0
    current_batch: 1
    start_time: "{{ now() }}"
  next:
  - step: fetch_batch

- step: fetch_batch
  desc: Get next batch of items
  tool: http
  method: GET
  endpoint: "{{ workload.api_url }}/items"
  params:
    limit: "{{ workload.batch_size }}"
    offset: "{{ (vars.current_batch - 1) * workload.batch_size }}"
  vars:
    last_fetch_time: "{{ now() }}"
    last_batch_size: "{{ this.data.items | length }}"
  next:
  - when: "{{ this.data.items | length > 0 }}"
    then:
    - step: process_batch
  - when: "{{ this.data.items | length == 0 }}"
    then:
    - step: finalize

- step: process_batch
  desc: Process items in batch
  type: iterator
  collection: "{{ fetch_batch.data.items }}"
  element: item
  mode: async
  task:
    type: python
    code: |
      def main(item):
        # Process item
        if item["status"] == "error":
          raise Exception("Processing failed")
        return {"id": item["id"], "result": "success"}
    vars:
      processed: "{{ vars.processed + 1 if this.status == 'success' else vars.processed }}"
      failed: "{{ vars.failed + 1 if this.status == 'error' else vars.failed }}"
  vars:
    current_batch: "{{ vars.current_batch + 1 }}"
  next:
  - step: fetch_batch

- step: finalize
  desc: Compute final statistics
  vars:
    end_time: "{{ now() }}"
    total_duration: "{{ vars.end_time - vars.start_time }}"
    success_rate: "{{ (vars.processed / (vars.processed + vars.failed)) * 100 if (vars.processed + vars.failed) > 0 else 0 }}"
  tool: http
  method: POST
  endpoint: "{{ workload.api_url }}/stats"
  payload:
    processed: "{{ vars.processed }}"
    failed: "{{ vars.failed }}"
    duration_seconds: "{{ vars.total_duration }}"
    success_rate: "{{ vars.success_rate }}"
  next:
  - step: end

- step: end
  desc: End workflow
```

### Example 2: Conditional Logic with Variables

```yaml
workflow:
- step: start
  vars:
    retry_count: 0
    max_retries: 3
    last_error: null
  next:
  - step: attempt_operation

- step: attempt_operation
  tool: http
  endpoint: "{{ workload.api_url }}"
  vars:
    after:
      retry_count: "{{ vars.retry_count + 1 if this.status == 'error' else vars.retry_count }}"
      last_error: "{{ this.error if this.status == 'error' else null }}"
  next:
  - when: "{{ this.status == 'success' }}"
    then:
    - step: success
## Performance Considerations

1. **Caching**: `get_all_vars()` loads all variables once per step, cached in rendering context
2. **Access tracking**: `accessed_at` and `access_count` updated on reads (like `auth_cache`)
3. **Indexing**: Primary key (execution_id, var_name) for O(1) lookups
4. **Cleanup**: `cleanup_execution()` method removes all vars when execution completes
5. **Async I/O**: All operations use async PostgreSQL for non-blocking access

### Cache Behavior (Similar to auth_cache)

- **Read**: Updates `accessed_at` timestamp and increments `access_count`
- **Write**: Upserts on primary key, preserves `created_at`, updates `accessed_at`
- **Cleanup**: Called from execution finalizer to remove execution-scoped vars
  - when: "{{ this.status == 'error' and vars.retry_count >= vars.max_retries }}"
    then:
    - step: failure
## Comparison: transient vs auth_cache

| Feature | auth_cache | transient |
|---------|-----------|-----------|
| **Purpose** | Credential caching | Runtime variables |
| **Scope** | execution_id | execution_id |
| **Primary Key** | (credential_name, execution_id) | (var_name, execution_id) |
| **TTL** | 3600 seconds (1 hour) | No TTL (execution lifetime) |
| **Data Storage** | Encrypted JSON | Plain JSONB |
| **Access Tracking** | access_count, accessed_at | access_count, accessed_at |
| **Cache Type** | secret, token, config | user_defined, step_result, computed, iterator_state |
| **Cleanup** | TTL-based + execution cleanup | Execution cleanup only |
| **Write Pattern** | Write once, read many | Write many, read many |
| **Use Case** | Secret Manager API optimization | Dynamic workflow state |

## Architecture Benefits

1. **Consistency**: Both use same *_cache pattern
2. **Proven**: auth_cache implementation is tested and working
3. **Clear separation**: auth_cache = external secrets, transient = runtime state
4. **Similar API**: TransientVars mirrors AuthCache methods
5. **Unified cleanup**: Both cleaned up on execution completion
```yaml
workload:
  environment: "production"

workflow:
- step: load_config
  desc: Load environment-specific configuration
  tool: http
  endpoint: "{{ workload.config_url }}/{{ workload.environment }}"
  vars:
    # Store configuration in variables
    api_endpoint: "{{ this.data.api.endpoint }}"
    api_timeout: "{{ this.data.api.timeout }}"
    feature_flags: "{{ this.data.features }}"
    db_config: "{{ this.data.database }}"
  next:
  - step: validate_config

- step: validate_config
  tool: python
  code: |
    def main(config):
      # Validate configuration
      required = ["api_endpoint", "api_timeout", "db_config"]
      for key in required:
        if not config.get(key):
          raise ValueError(f"Missing required config: {key}")
      return {"valid": True}
  args:
    config:
      api_endpoint: "{{ vars.api_endpoint }}"
      api_timeout: "{{ vars.api_timeout }}"
      db_config: "{{ vars.db_config }}"
  next:
  - step: execute_with_config

- step: execute_with_config
  tool: http
  endpoint: "{{ vars.api_endpoint }}/data"
  timeout: "{{ vars.api_timeout }}"
  payload:
    query: "{{ workload.query }}"
    features: "{{ vars.feature_flags }}"
```

## Migration Notes

### Backward Compatibility

1. **Workload still works**: Existing `{{ workload.var }}` references unchanged
2. **Step results still work**: `{{ step_name.data }}` patterns unchanged
3. **New `vars` namespace**: Opt-in feature, doesn't break existing playbooks

### Migration Path

For playbooks that manually manage state:

**Before** (using workload):
```yaml
workload:
  counter: 0  # Can't update during execution

workflow:
- step: process
  tool: python
  # Have to pass counter through step results
```

**After** (using vars):
```yaml
workflow:
- step: start
  vars:
    counter: 0

- step: process
  tool: python
  vars:
    counter: "{{ vars.counter + 1 }}"  # Can update!
```

## Performance Considerations

1. **Caching**: Load all vars once per step evaluation, cache in context
2. **Batch updates**: Use `set_variables_bulk()` for multi-var updates
3. **Indexing**: Execution ID index for fast lookups
4. **Cleanup**: Auto-delete when execution completes (add to cleanup job)

## Future Enhancements

1. **Variable history**: Track all updates in separate `exec_vars_history` table
2. **Variable expressions**: Support computed vars with dependencies
3. **Variable scopes**: Add `global` scope for cross-execution sharing
4. **Variable validation**: JSON schema validation for typed variables
5. **Variable encryption**: Encrypt sensitive variable values
6. **Variable watch**: Webhooks/events when variables change

## Questions for User

1. **Naming**: Is `exec_vars` good? Or prefer `runtime_vars`, `execution_vars`, `workflow_vars`?
2. **API scope**: Should variables API be public or internal-only?
3. **Cleanup**: Auto-delete vars when execution completes? Or keep for debugging?
4. **History**: Need full change history or just current values?
5. **Performance**: Expected number of variables per execution? (for optimization)
