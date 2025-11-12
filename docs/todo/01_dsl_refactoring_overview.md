# DSL Refactoring Overview

**Status:** Planning  
**Date:** November 11, 2025  
**Objective:** Refactor NoETL DSL to a cleaner, more expressive workflow surface with unified sink pattern

---

## 1. Final DSL Surface (Authoring Contract)

### 1.1 Canonical Step Keys

Every step in a workflow is defined by these core keys:

```yaml
step: <string>        # Unique step identifier (required)
desc: <string>        # Human-readable description (optional)
when: <jinja>         # Gate condition (default: true)
loop: <object>        # Iteration controller (optional)
tool: <object>        # Actionable unit (required unless pure router)
result: <object>      # Result collection and binding (optional)
next: <array>         # Ordered list of edges (optional)
```

**Key Principles:**
- **step**: Unique ID for the step (string, required)
- **desc**: Human description (string, optional but recommended)
- **when**: Gate to run this step when called (Jinja expression, default `true`)
- **loop**: Iteration controller for repeated tool execution (object, optional)
- **tool**: Actionable unit to run (object, required unless step is a pure router)
- **result**: Variable name for step output, accessible in subsequent steps (string, optional)
- **next**: Ordered list of edges `[{ step: <id>, when?: <jinja> }]` (array, optional for terminal steps)

### 1.2 Context Structure

The workflow execution context is a dictionary with explicit access patterns:

```python
context = {
  "workload": {...},      # Immutable: assigned during playbook initialization
  "step_result_var": ..., # Step-level result variables
  ...
}
```

**Access Patterns:**

1. **Immutable Workload** (playbook initialization):
   ```python
   context.workload.get('api_key')
   context.workload.get('pg_auth')
   ```

2. **Step Result Variables** (assigned via `result` attribute):
   ```python
   context.get('my_result')       # Returns step result or None
   context.get('user_data', {})   # Returns step result or default
   ```

3. **Jinja Template Access**:
   ```yaml
   args:
     api_key: "{{ context.workload.api_key }}"
     user_data: "{{ context.my_result }}"
     items: "{{ context.items_list }}"
   ```

**Key Rules:**
- `context.workload` is set once at playbook initialization and never modified
- Step-level `result: variable_name` assigns tool output to context variable
- Tool-level `result: variable_name` assigns tool output, accessible within tool sinks
- Python tools receive full `context` object as parameter
- Jinja templates access context via `{{ context.* }}` explicitly
- Loop element variables available directly: `{{ element_name }}`

**Variable Scope:**
```yaml
- step: fetch_data
  result: my_data              # Step-level: accessible in next steps
  tool:
    kind: http
    result: http_response      # Tool-level: accessible in tool sinks
    sink:
      - kind: postgres
        table: items
        args:
          data: "{{ http_response.body }}"  # Tool-level result

- step: process_data
  tool:
    kind: python
    args:
      data: "{{ context.my_data }}"  # Step-level result from previous step
```

---

## 2. Loop (Step-Level Iteration Controller)

Control iteration at the step level with `loop`. When present, the tool executes once per collection element.

```yaml
loop:
  collection: <Jinja iterable>   # Required: iterable expression
  element: <loop_var>            # Required: variable name for current element
  mode: sequential|parallel      # Optional: execution mode (default: sequential)
  until: <Jinja bool>            # Optional: early exit condition (sequential mode only)
```

**Semantics:** "Loop over `<collection>` as `<element>`, execute tool for each"

**Example:**
```yaml
- step: process_users
  loop:
    collection: "{{ context.workload.users }}"
    element: user                  # Available as {{ user }} in tool config
    mode: parallel
    until: "{{ user.status == 'inactive' }}"  # Stop early if condition met
  tool:
    kind: http
    url: "/api/users/{{ user.id }}"
```

**Execution:**
- **Sequential mode**: Execute tool for element 1, complete all sinks, then element 2, etc.
- **Parallel mode**: Execute tool for all elements concurrently
- **Early exit** (`until`): Only applicable in sequential mode; stops when condition becomes true

---

## 3. Tool (Actionable Unit)

The `tool` defines what action to execute. It contains:
1. **kind**: Plugin identifier
2. **Plugin-specific config**: Fields validated by the plugin
3. **result**: Variable name for tool output (optional, accessible in sinks)
4. **sink**: Where to persist tool output (optional)

```yaml
tool:
  kind: <plugin_id>              # Required: http|postgres|python|duckdb|transfer|playbook
  result: <variable_name>        # Optional: variable name for tool output (accessible in sinks)
  # Plugin-specific fields (no 'spec' wrapper needed)
  # Examples: url, query, code, endpoint, etc.
  chunk:                         # Optional: chunked processing
    size: <number>               # Chunk size (records per batch)
    mode: batch|stream           # Processing mode (default: batch)
    path: <jsonpath>             # For extracting array from response (optional)
  sink:                          # Optional: array of persistence targets
    - kind: <sink_type>          # postgres|duckdb|s3|http
      # Sink-specific config
```

### 3.1 Tool Kinds and Configs

**HTTP:**
```yaml
tool:
  kind: http
  result: http_response          # Tool-level result variable
  url: "{{ context.workload.api_url }}"
  method: GET|POST|PUT|DELETE
  headers:
    Authorization: "Bearer {{ token }}"
  body: "{{ request_data }}"
  chunk:                         # Optional: chunk large responses
    size: 100
    path: "data.items"           # JSONPath to array
  sink:
    - kind: postgres
      table: api_responses
      args:
        response_data: "{{ http_response.body }}"  # Access tool result
```

**Postgres:**
```yaml
tool:
  kind: postgres
  result: query_result           # Tool-level result variable
  auth: "{{ context.workload.pg_auth }}"
  query: "SELECT * FROM users WHERE active = true"
  chunk:                         # Optional: cursor-based chunking
    size: 1000                   # Fetch 1000 rows at a time
  sink:
    - kind: duckdb
      table: users_replica
      args:
        rows: "{{ query_result.data }}"  # Access tool result
```

**Python:**
```yaml
tool:
  kind: python
  result: computed_result        # Tool-level result variable
  code: |
    def main(context):
      # Access immutable workload
      api_key = context.workload.get('api_key')
      
      # Access dynamic context state
      items = context.get('items')
      count = context.get('count', 0)
      
      return transform(items, count)
  args:
    items: "{{ context.my_items }}"      # Pass context variables as args
    count: "{{ context.processed_count }}"
  sink:
    - kind: postgres
      table: computed_results
      args:
        result_data: "{{ computed_result }}"  # Access tool result
```

**Transfer:**
```yaml
tool:
  kind: transfer
  result: transfer_result        # Tool-level result variable
  source:                        # Where to fetch from
    kind: postgres
    auth: "{{ context.workload.source_pg }}"
    query: "SELECT * FROM source_table"
    chunk:
      size: 100
  sink:                          # Where to write to (can be multiple)
    - kind: postgres
      auth: "{{ context.workload.target_pg }}"
      table: target_table
      args:
        rows: "{{ transfer_result.data }}"
    - kind: duckdb
      table: analytics.data
      args:
        rows: "{{ transfer_result.data }}"
```

**Playbook:**
```yaml
tool:
  kind: playbook
  path: playbooks/user_scorer
  entry_step: start              # Optional
  return_step: finalize          # Optional
  args:
    user_id: "{{ user.id }}"
```

---

## 4. Chunking (Tool-Level Data Batching)

Chunking allows tools to process large datasets in batches, with each chunk distributed to sinks.

```yaml
tool:
  kind: postgres
  query: "SELECT * FROM large_table LIMIT 10000"
  chunk:
    size: 100                    # Process 100 records at a time
    mode: batch                  # batch: load chunk into memory; stream: process row-by-row
  sink:
    - kind: postgres
      table: target_table
    - kind: s3
      path: "backup/chunk_{{ chunk.index }}.parquet"
```

**Chunk Metadata** (available in sink templates):
```yaml
chunk.index      # 0, 1, 2, ... (chunk number)
chunk.size       # Actual number of records in this chunk
chunk.total      # Total number of chunks
chunk.first      # Boolean: is this the first chunk?
chunk.last       # Boolean: is this the last chunk?
chunk.data       # The chunk array itself
```

**Execution Flow:**
```
Tool executes → Returns 10,000 records
↓
Chunk 1 (records 1-100) → [All sinks execute in parallel]
Chunk 2 (records 101-200) → [All sinks execute in parallel]
...
Chunk 100 (records 9901-10000) → [All sinks execute in parallel]
```

**Key Points:**
- All sinks receive the same chunk data
- Sinks execute in parallel within each chunk
- Next chunk only starts after all sinks complete current chunk
- Works with loops: each loop iteration can produce chunked data

---

## 5. Sink (Tool Output Persistence)

Sinks define where tool output is persisted. Multiple sinks execute in parallel.

**Note:** Sinks can access tool-level `result` variable if defined. To make results accessible in subsequent steps, use step-level `result` attribute.

```yaml
sink:                            # Array of persistence targets
  - kind: postgres
    auth: "{{ context.workload.pg_auth }}"
    table: output_table
    mode: insert|upsert|replace|append
    key: id                      # Required for upsert mode
    mapping:                     # Column mapping (optional)
      db_column: "{{ tool_result.field }}"
    args:                        # Arguments using tool result
      data: "{{ tool_result.data }}"
  
  - kind: duckdb
    auth: "{{ context.workload.duckdb }}"
    table: analytics.data
    mode: append
    args:
      rows: "{{ tool_result.rows }}"
  
  - kind: s3
    auth: "{{ context.workload.s3 }}"
    path: "backups/{{ execution_id }}/data.parquet"
    format: parquet
```

### 5.1 Sink Kinds

**Postgres/DuckDB:**
```yaml
- kind: postgres
  auth: "{{ context.workload.pg_auth }}"
  table: schema.table_name
  mode: insert|upsert|replace|append
  key: id                        # For upsert
  mapping:                       # Column mapping
    target_col: "{{ tool_result.source_field }}"
  args:
    data: "{{ tool_result }}"
```

**S3:**
```yaml
- kind: s3
  auth: "{{ context.workload.s3 }}"
  path: "bucket/path/file.parquet"
  format: parquet|json|csv
```

**HTTP (Webhook/API):**
```yaml
- kind: http
  url: "{{ context.workload.webhook_url }}"
  method: POST
  body: "{{ tool_result.data }}"
```

### 5.2 Sink Error Handling

```yaml
sink:
  - kind: postgres
    table: critical_data
    on_error: fail               # Default: fail step if sink fails
  
  - kind: s3
    path: backups/
    on_error: warn               # Continue even if fails, log warning
```

---

## 6. Result (Variable Binding)

The `result` attribute assigns tool output to a variable name for access in subsequent steps.

**Two Levels:**
1. **Tool-level `result`**: Variable accessible within tool sinks
2. **Step-level `result`**: Variable accessible in subsequent steps (stored in context)

```yaml
- step: fetch_data
  result: my_data                # Step-level: accessible in next steps via context.my_data
  tool:
    kind: http
    result: http_response        # Tool-level: accessible in sinks
    url: "{{ context.workload.api_url }}"
    sink:
      - kind: postgres
        table: responses
        args:
          body: "{{ http_response.body }}"      # Tool-level result
          status: "{{ http_response.status }}"  # Tool-level result

- step: process_data
  tool:
    kind: python
    args:
      data: "{{ context.my_data }}"  # Step-level result from previous step
```

### 6.1 Step-Level Result

Assigns tool output to context variable, accessible in all subsequent steps:

```yaml
- step: fetch_users
  result: users_data             # Variable name in context
  tool:
    kind: http
    url: /api/users
  next:
    - step: process_users

- step: process_users
  loop:
    collection: "{{ context.users_data.items }}"  # Access step result
    element: user
  tool:
    kind: python
    args:
      user: "{{ user }}"
      all_users: "{{ context.users_data }}"  # Access step result
```

### 6.2 Tool-Level Result

Assigns tool output to temporary variable, accessible only within tool sinks:

```yaml
- step: fetch_and_store
  tool:
    kind: http
    result: api_response         # Tool-level only
    url: /api/data
    sink:
      - kind: postgres
        table: raw_data
        args:
          body: "{{ api_response.body }}"
          headers: "{{ api_response.headers }}"
      - kind: s3
        path: "backup/{{ api_response.timestamp }}.json"
        body: "{{ api_response }}"
```

### 6.3 Combined Usage

Use both levels for different purposes:

```yaml
- step: process_items
  result: item_results           # Step-level: accessible in next steps
  loop:
    collection: "{{ context.workload.items }}"
    element: item
    mode: parallel
  tool:
    kind: http
    result: http_resp            # Tool-level: accessible in sinks
    url: "/api/items/{{ item.id }}"
    sink:
      - kind: postgres
        table: items
        args:
          item_id: "{{ item.id }}"
          response: "{{ http_resp.data }}"  # Tool-level result

- step: summarize
  tool:
    kind: python
    args:
      items: "{{ context.item_results }}"  # Step-level result from previous step
```

### 6.4 Loop Result Collection

When a step has a loop, the step-level `result` collects all loop iteration results into an array:

```yaml
- step: process_batch
  result: all_responses          # Collects array of all iteration results
  loop:
    collection: "{{ context.workload.items }}"
    element: item
    mode: sequential
  tool:
    kind: http
    url: "/api/process/{{ item.id }}"
  next:
    - step: analyze

- step: analyze
  tool:
    kind: python
    args:
      responses: "{{ context.all_responses }}"  # Array of all loop results
```

---

## 7. Complete Examples

### 7.1 HTTP Chunked Data with Parallel Sinks

Fetch large dataset from API, chunk into batches, persist to multiple targets:

```yaml
- step: fetch_and_store
  result: fetch_summary          # Step-level result for summary
  tool:
    kind: http
    result: api_data             # Tool-level result for sinks
    url: "{{ context.workload.api_url }}/large_dataset"
    method: GET
    chunk:
      size: 100
      path: "data.items"         # Extract array from response
    sink:
      - kind: postgres
        auth: "{{ context.workload.pg_auth }}"
        table: api_cache
        mode: append
        args:
          data: "{{ api_data.items }}"
          chunk_index: "{{ chunk.index }}"
      - kind: s3
        auth: "{{ context.workload.s3_auth }}"
        path: "backups/chunk_{{ chunk.index }}.parquet"
        format: parquet
```

**Execution:**
- HTTP plugin fetches full response
- Extracts array at `data.items`
- Chunks into groups of 100 records
- For each chunk:
  - Postgres sink writes to `api_cache` table
  - S3 sink writes parquet file `chunk_0.parquet`, `chunk_1.parquet`, etc.
  - All sinks execute in parallel
- Step result `fetch_summary` contains overall fetch metadata


### 7.2 Loop with Chunking and Result Collection

Process multiple users, fetch their activity logs (chunked), collect results:

```yaml
- step: process_users
  result: user_results           # Step-level: array of all user results
  loop:
    collection: "{{ context.workload.users }}"
    element: user
    mode: sequential
  tool:
    kind: postgres
    result: activity_data        # Tool-level: current user's activity
    auth: "{{ context.workload.pg_auth }}"
    query: "SELECT * FROM activity_logs WHERE user_id = {{ user.id }} LIMIT 10000"
    chunk:
      size: 500                  # Process 500 rows at a time
    sink:
      - kind: duckdb
        auth: "{{ context.workload.duckdb }}"
        table: user_activity_{{ user.id }}
        mode: replace
        args:
          activities: "{{ activity_data.rows }}"
  next:
    - step: summary

- step: summary
  tool:
    kind: python
    code: |
      def main(context):
        # Access step-level result from previous step
        user_results = context.get('user_results', [])
        
        return {
          "users_processed": len(user_results),
          "total_activities": sum(r.get('count', 0) for r in user_results)
        }
    args:
      user_results: "{{ context.user_results }}"
```

**Execution:**
- Loop over each user sequentially
- For each user:
  - Query fetches up to 10,000 activity logs
  - Chunks into batches of 500
  - For each chunk:
    - DuckDB sink writes to user-specific table
- Step result `user_results` collects array of all loop iteration results
- Summary step accesses `context.user_results` to generate report


### 7.3 Transfer with Source Chunking and Multiple Targets

Transfer data from one database to multiple destinations with chunking:

```yaml
- step: bulk_transfer
  result: transfer_summary       # Step-level result
  tool:
    kind: transfer
    result: transfer_data        # Tool-level result for sinks
    source:
      kind: postgres
      auth: "{{ context.workload.source_db }}"
      query: "SELECT * FROM large_table WHERE date > '2024-01-01'"
      chunk:
        size: 1000               # Fetch 1000 rows at a time
    sink:
      - kind: postgres
        auth: "{{ context.workload.target_db }}"
        table: replicated_table
        mode: append
        mapping:
          id: "{{ transfer_data.id }}"
          name: "{{ transfer_data.full_name }}"
          created: "{{ transfer_data.created_at }}"
      - kind: duckdb
        auth: "{{ context.workload.analytics_db }}"
        table: analytics.facts
        mode: append
        args:
          rows: "{{ transfer_data.rows }}"
      - kind: s3
        auth: "{{ context.workload.s3 }}"
        path: "archives/{{ execution_id }}/chunk_{{ chunk.index }}.parquet"
        format: parquet
```

**Execution:**
- Source query fetches data in chunks of 1000 rows
- For each chunk:
  - Postgres sink writes to target database (with column mapping)
  - DuckDB sink writes to analytics table
  - S3 sink writes parquet archive
  - All 3 sinks execute in parallel
- Step result `transfer_summary` contains overall transfer metadata


### 7.4 Parallel Loop with Step Result Collection

Process items asynchronously, store results in database, collect in step result:

```yaml
- step: fetch_all_users
  result: users                  # Step-level result
  tool:
    kind: http
    url: "{{ context.workload.api_url }}/users"

- step: enrich_users
  result: enriched_users         # Step-level: array of all enriched users
  loop:
    collection: "{{ context.users.data }}"
    element: user
    mode: parallel               # Process all users concurrently
  tool:
    kind: http
    result: enrichment           # Tool-level result for sink
    url: "{{ context.workload.enrichment_api }}/enrich"
    method: POST
    body:
      user_id: "{{ user.id }}"
      fields: ["credit_score", "preferences"]
    sink:
      - kind: postgres
        auth: "{{ context.workload.pg_auth }}"
        table: enriched_users
        mode: upsert
        key: user_id
        args:
          user_id: "{{ user.id }}"
          enrichment_data: "{{ enrichment }}"
  next:
    - step: analyze_enriched

- step: analyze_enriched
  when: "{{ context.enriched_users is defined }}"
  tool:
    kind: python
    code: |
      def main(context):
        # Access step-level result from previous step
        enriched_users = context.get('enriched_users', [])
        
        return compute_metrics(enriched_users)
    args:
      enriched_users: "{{ context.enriched_users }}"
```

**Execution:**
- Fetch all users from API, store in `users` step result
- Loop over users in parallel mode (concurrent execution)
- For each user:
  - Call enrichment API
  - Upsert result into postgres using tool-level `enrichment` result
- Step result `enriched_users` collects array of all enrichment results
- `analyze_enriched` accesses `context.enriched_users` to process all results


---

## 8. Execution Semantics

### 8.1 Chunking + Parallel Sinks Flow

```
Tool Execution
    ↓
Returns N records
    ↓
Split into chunks of size C
    ↓
For each chunk (sequential processing):
    ↓
    ┌──────────────────────────────────┐
    │  Sink 1  │  Sink 2  │  Sink 3   │  ← All execute in PARALLEL
    └──────────────────────────────────┘
    ↓
    Wait for all sinks to complete
    ↓
    Proceed to next chunk
```

**Key Properties:**
- Chunks processed sequentially (chunk N+1 waits for chunk N)
- Within each chunk, all sinks execute concurrently
- Chunk metadata available to all sinks via templating
- Failures in any sink can be configured to fail step or warn

### 8.2 Loop + Chunking Interaction

```yaml
loop:
  collection: [1, 2, 3]
  element: item
tool:
  query: "SELECT * FROM table WHERE id = {{ item }}"
  chunk:
    size: 100
  sink:
    - kind: postgres
```

**Execution:**
```
Loop Iteration 1 (item=1):
    ↓
    Tool fetches data for item 1
    ↓
    Chunk 1 (records 1-100) → Sink writes to postgres
    Chunk 2 (records 101-200) → Sink writes to postgres
    ...
    ↓
Loop Iteration 2 (item=2):
    ↓
    Tool fetches data for item 2
    ↓
    Chunk 1 (records 1-100) → Sink writes to postgres
    ...
```

**Order:** Loop iteration → Tool execution → Chunking → Parallel sinks

### 8.3 Result Variable Scope

**Tool-Level Result:**
- Defined: `tool.result: variable_name`
- Scope: Available only within tool sinks
- Purpose: Access tool output in sink configurations
- Lifetime: Exists only during tool execution

**Step-Level Result:**
- Defined: Step-level `result: variable_name`
- Scope: Available in all subsequent steps via `context.variable_name`
- Purpose: Pass data between workflow steps
- Lifetime: Exists for entire workflow execution

**Example:**
```yaml
- step: fetch_and_process
  result: final_data             # Step-level: accessible in next steps
  tool:
    kind: http
    result: http_resp            # Tool-level: accessible in sinks only
    url: /api/data
    sink:
      - kind: postgres
        args:
          raw: "{{ http_resp }}"  # Tool-level result
      - kind: s3
        body: "{{ http_resp }}"   # Tool-level result

- step: use_data
  tool:
    kind: python
    args:
      data: "{{ context.final_data }}"  # Step-level result from previous step
```

---

## 9. Migration from DSL v1

### 9.1 Key Changes

| v1 Concept | v2 Concept | Change |
|------------|------------|--------|
| `tool.spec.<fields>` | `tool.<fields>` | Remove `spec` wrapper |
| `result.as` | `result: variable_name` | Simplified to string |
| `tool.save` | `tool.sink` | Rename save → sink |
| `bind` attribute | Step-level `result` | Variable assignment via result |
| `iterator` type | `loop` at step | Iteration is step concern |
| `data` attribute | `args` in tool | Pass arguments to tool |
| Context sink with `assignment` | Removed | Use step-level `result` instead |

### 9.2 Example Migration

**v1:**
```yaml
- step: fetch_data
  type: workbook
  name: my_task
  data:
    user_id: "{{ workload.user_id }}"
  bind:
    user_data:
      path: "result.data"
  save:
    storage: postgres
    table: user_cache
```

**v2:**
```yaml
- step: fetch_data
  result: user_data              # Step-level result assignment
  tool:
    kind: workbook
    name: my_task
    result: task_output          # Tool-level result for sinks
    args:
      user_id: "{{ context.workload.user_id }}"
    sink:
      - kind: postgres
        auth: "{{ context.workload.pg_auth }}"
        table: user_cache
        args:
          data: "{{ task_output }}"
```

**Key Differences:**
1. `type` → `kind`
2. `data` → `args`
3. `bind` → step-level `result`
4. `save` → `sink` array
5. Added `tool.result` for sink access
6. Explicit `context.workload.*` references

  spec:
    query: "SELECT * FROM users WHERE id = %(user_id)s"
    auth: pg_local              # Optional credential reference
    params:
      user_id: "{{ workload.user_id }}"
```

**Python:**
```yaml
tool:
  kind: python
  spec:
    code: |
      def main(user_data):
          return {"score": user_data["rating"] * 10}
```

Or with module reference:
```yaml
tool:
  kind: python
  spec:
    module: scoring.calculator
    callable: compute_user_score
```

**DuckDB:**
```yaml
tool:
  kind: duckdb
  spec:
    query: "SELECT * FROM read_csv('{{ file_path }}')"
    file: "{{ workload.csv_path }}"  # Optional: DuckDB file path
```

---

## 4. Routing with `next`

Define step transitions with conditional routing:

```yaml
next:
  - when: "<Jinja condition>"   # Optional guard (if/elif)
    step: <target_step_id>
  - step: <else_target>         # Final else (no `when`)
```

**Evaluation Order:**
- Edges are evaluated **in order**
- First matching edge is taken (based on `when` condition)
- If none match → no successor (workflow may stall or complete)

**Example:**
```yaml
next:
  - when: "{{ score > 80 }}"
    step: high_score_path
  - when: "{{ score > 50 }}"
    step: medium_score_path
  - step: low_score_path       # Default fallback
```

---

## 5. Start & Calling Model (Petri-Net Style)

### 5.1 Initial State

- Only a special **start step** is enabled initially (router or no-op)
- Steps run **only when called** by a predecessor via `next`

### 5.2 Step Execution Flow

1. On each call, the engine evaluates the target step's **step-level `when`**
2. If `false`, the call is **parked (pending)**. Subsequent calls re-evaluate until it becomes `true`
3. When `true`, the step executes **once (idempotent)**; later calls are ignored

### 5.3 Execution Semantics

```
start → call(step_a) → evaluate when → park if false
                                     → execute if true (once only)
                                     → subsequent calls ignored
```

---

## 6. Engine Status Namespace + Helpers

### 6.1 Read-Only Status Context

Engine writes read-only status under `step.<id>.status.*` in context:

```yaml
step.<id>.status:
  done: bool              # Step has completed
  ok: bool|null           # Step completed successfully (null if not done)
  running: bool           # Step is currently executing
  started_at: timestamp   # Execution start time
  finished_at: timestamp|null  # Execution end time (null if not done)
  error: string|null      # Error message (null if no error)
  # For loop steps:
  total: int              # Total iterations
  completed: int          # Completed iterations
  succeeded: int          # Successful iterations
  failed: int             # Failed iterations
```

### 6.2 Jinja Global Helpers

Helper functions available in Jinja templates:

```python
done(step_id)           # Returns: bool - step has completed
ok(step_id)             # Returns: bool - step completed successfully
fail(step_id)           # Returns: bool - step failed
running(step_id)        # Returns: bool - step is currently running

loop_done(step_id)      # Returns: bool - loop step fully drained
all_done(list_of_ids)   # Returns: bool - all steps in list completed
any_done(list_of_ids)   # Returns: bool - any step in list completed
```

**Usage Example:**
```yaml
when: "{{ done('fetch_user') and ok('score_user') }}"
```

### 6.3 Reserved Namespace

**IMPORTANT:** `step` is **reserved and read-only**.

The validator **must reject** attempts to:
- Bind to `step` via `bind`
- Write to `step` via `result.as`

---

## 7. Execution Order Inside a Step

When a step is called, execution follows this order:

1. **Evaluate `when`** → Must be truthy to run
2. **Apply `bind`** (if any) to the context
3. **If `loop`**: 
   - Iterate over `collection` (sequential or parallel)
   - Inject `element` into context for each item
   - Run `tool` per item
4. **Else**: Run `tool` once
5. **`tool.result` handling**:
   - `raw = this` (plugin's return value)
   - `out = pick ? eval(pick) : raw`
   - If `as`: set `context[as] = out`
   - If `collect`: append/merge `out` into `context[collect.into]` (per loop)
   - For each `sink` item: emit `out` to that sink
6. **Evaluate `next` edges** (if any) and call the chosen successor

---

## 8. Authoring Examples

### 8.1 Fan-Out → AND-Join (No Dependencies, Pure `when`)

Parallel execution with synchronization at join point:

```yaml
- step: start
  next:
    - step: fetch_user
    - step: score_user

- step: fetch_user
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "{{ api }}/users/{{ workload.user_id }}"
    result:
      as: user_raw
  next:
    - step: join

- step: score_user
  tool:
    kind: playbook
    spec:
      path: playbooks/user_scorer
    args:
      user: "{{ user_raw }}"
    result:
      as: user_score
  next:
    - step: join

- step: join
  when: "{{ done('fetch_user') and ok('score_user') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            u = context["user_raw"]
            s = context["user_score"]
            return {
                "id": u["id"],
                "score": s["value"]
            }
    result:
      as: user_profile
      sink:
        - postgres:
            table: public.user_profiles
            mode: upsert
            key: id
            args:
              id: "{{ user_profile.id }}"
              score: "{{ user_profile.score }}"
```

**Explanation:**
- `start` fans out to both `fetch_user` and `score_user` (parallel execution)
- Both steps call `join` when complete
- `join` waits via `when` until both prerequisites are done and successful
- `join` combines results and sinks to PostgreSQL

---

### 8.2 Loop + Reduce

Parallel iteration with collection and aggregation:

```yaml
- step: proc_users
  desc: "Loop over users as 'user'"
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  tool:
    kind: playbook
    spec:
      path: playbooks/user_profile_scorer
    args:
      user_data: "{{ user }}"
    result:
      pick: "{{ {'name': user.name, 'score': this.profile_score or 0.0} }}"
      as: last_score
      collect:
        into: all_scores
        mode: list
      sink:
        - postgres:
            table: public.user_profile_results
            mode: upsert
            key: id
            args:
              id: "{{ execution_id }}:{{ out.name }}"
              score: "{{ out.score }}"
  next:
    - step: summarize

- step: summarize
  when: "{{ loop_done('proc_users') }}"
  tool:
    kind: workbook
    spec:
      name: summarize_scores
    args:
      scores: "{{ all_scores }}"
    result:
      as: scores_summary
```

**Explanation:**
- `proc_users` loops over `workload.users` in parallel
- Each iteration calls the `user_profile_scorer` sub-playbook
- Results are:
  - Transformed via `pick` (extract name and score)
  - Stored as `last_score` (per iteration)
  - Collected into `all_scores` list
  - Sinked to PostgreSQL (per iteration)
- `summarize` waits for loop completion via `loop_done('proc_users')`
- `summarize` processes all collected scores

---

## Next Steps

This document defines the **final DSL surface**. Next portions will cover:

1. **Migration Strategy**: How to transition from current DSL to new surface
2. **Implementation Plan**: Core engine changes, validator updates, plugin adaptations
3. **Backward Compatibility**: Handling legacy playbooks during transition
4. **Testing Strategy**: Validation suite for new DSL

---

**Ready for next portion of the refactoring plan.**
