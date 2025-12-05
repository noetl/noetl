Goal: provide a clear, robust way to reference step/playbook results and persist them to external systems in a consistent way (works with loops and nested playbooks, and integrates credentials securely).

This spec defines:
- Canonical result model and references
- The `sink:` block for steps and playbooks
- Credential references
- Loop and nested playbook behavior

## 1) Canonical Result Model and References

- Each actionable step produces a JSON result recorded in `noetl.event_log.result` with `event_type = action_completed`.
- During template rendering, results are exposed by step name. You can reference:
  - `{{ step_name }}` or `{{ step_name.result }}` → the full result object
  - `{{ step_name.data }}` → when your step returns `{ "data": ... }`, this is a common convenience
  - Any JSON field inside the result: `{{ step_name.field }}`

Required envelope: All step results MUST use the envelope below. This is the only supported structure the engine operates on.

```
{
  "status": "success" | "error",   # required
  "data": { ... },                   # required (object or list)
  "meta": { ... }                    # optional (diagnostics, provenance, counters, etc.)
}
```

The engine expects this envelope everywhere. Always reference payloads via `{{ step_name.data }}`; use `{{ step_name.status }}` to branch on outcomes and `{{ step_name.meta }}` for diagnostics.

### Nested Playbooks

- A child playbook should return its final value explicitly at the end (e.g., via `execution_complete` or a final `save`/`return` block). Parent context sees it as `{{ child_step_name }}` or `{{ child_step_name.data }}` depending on the return envelope.

## 2) Persisting Results: `sink:` Block

Attach `sink:` to any step (or the playbook end) to persist values. If omitted, results are only stored in `event_log`.

Schema (declarative mode):

```
sink:
  when: <expr>                 # optional condition; default true
  on: success|error|always     # default success
  storage: event_log|postgres|duckdb|bigquery|snowflake|s3|gcs|file|kv|vector|graph  # flattened enum
  auth: <name>                 # optional; resolves through credential store (alias: credentialRef deprecated)
  spec:                        # storage-specific parameters (dsn/table/bucket/path/index/namespace/etc.)
    ...
  format: json|csv|parquet     # optional for file/object stores
  mode: append|overwrite|update|upsert  # when supported (DB/object/kv/vector)
  key: [field1, field2]        # for upsert when supported
  table: <table_name>          # for DB stores
  data:                        # object/list/expr; what to persist
    <key>: {{ template }}

Schema (statement mode):

```
sink:
  when: <expr>
  on: success|error|always
  tool: postgres|duckdb|bigquery|snowflake|graph    # flattened enum
  auth: <name>               # alias: credentialRef (deprecated)
  spec:
    dialect: sql|cypher|gremlin|sparql   # graph/triple stores
  statement: |
    INSERT INTO hello_world(execution_id, payload)
    VALUES (:execution_id, :payload)
    ON CONFLICT(execution_id) DO UPDATE SET payload = EXCLUDED.payload
  params:
    execution_id: "{{ execution_id }}"
    payload: "{{ tojson(test_step.data) }}"
```
```

Guidelines:
- If `storage` is omitted, we default to `event_log` and only record in `event_log.result`.
- `data:` can be a mapping or a single template scalar/object.
- For DB stores, prefer `mode: upsert` with `key:` when applicable; otherwise `append`.
- Statement mode supports parameterized operations; prefer `params:` over inlining values to avoid quoting mistakes.

### Example: End Step Persist

```
- step: end
  desc: End simple test
  sink:
    tool: postgres
    auth: pg_main              # points to a credential record by alias
    table: hello_world
    mode: upsert
    key: [execution_id]
    data:
      execution_id: "{{ execution_id }}"
      hello_world_step: "{{ test_step.data }}"
```

## 3) Credentials

Use the `credential` table or an external secret provider. Reference credentials by name anywhere a task or `save.storage` needs them. For readability, prefer `credential:`; `credentialRef:` is a supported alias (reference).

Ways to attach credentials:

```
# Playbook level (shared by steps)
credentials:
  - name: pg_main            # lookup key in credential store
    as: pg                   # optional alias

# Step/task level
type: postgres
auth: pg_main

# Save block
sink:
  storage: s3
  auth: s3_backup
```

Resolution order:
1) Step/task `credential` (alias: credentialRef)
2) save.storage.`credential` (alias: credentialRef)
3) Playbook `credentials` entries (by alias/name)

The engine fetches the credential secret material (DSN/token/keys) securely and injects it only where required. We recommend not to hardcode credentials inside playbooks.

## 4) Loops and Aggregations

Loop steps emit one result per item and may produce an aggregated result for the step. References:

- Per-item context: templates receive `<loop_step>.result_index` and `_loop.current_item`.
- Aggregated result: `{{ loop_step.result }}` (array or object), and often `{{ loop_step.data }}` when using the envelope.

Persisting loop results:
- Use `sink:` on the loop step to persist the aggregated result.
- For per-item saves, attach `sink:` to the inner step(s) executed per iteration (they will receive the iterator context).

Batching options for high‑volume saves:
- `batch: true` and `chunk_size: 1000` (when supported by the engine/driver)
- `concurrency: 4` to parallelize object/kv/vector writes safely

## 5) Nested Playbooks (Calls)

When a step calls another playbook (`type: playbook` or a workbook action that invokes a playbook), propagate results via an explicit return at the child end. Parent references:

```
{{ child_step_name }}           # full child result
{{ child_step_name.data }}      # child result data payload
```

You can `sink:` at the parent end step to persist the composed/aggregated output.

## 6) Example

```
apiVersion: noetl.io/v1
kind: Playbook
name: simple_test
path: examples/test/simple_test

credentials:
  - name: pg_main

workload:
  message: "Hello World"

workflow:
  - step: start
    desc: Start simple test
    next:
      - step: test_step
        args:
          message: "{{ workload.message }}"

  - step: test_step
    desc: Simple test step
    tool: python
    code: |
      def main(message):
          print(f"TEST_STEP: {message}")
          return {"status": "success", "data": {"message": message}}
    next:
      - step: end

  - step: end
    desc: End simple test
    sink:
      tool: postgres
      credentialRef: pg_main
      table: hello_world
      mode: upsert
      key: [execution_id]
      data:
        execution_id: "{{ execution_id }}"
        message: "{{ test_step.data.message }}"
```

### Additional Examples

1) Key‑Value store e.g., Redis/DynamoDB:

```
sink:
  storage: kv
  auth: redis_main
  spec: { driver: redis, namespace: noetl }
  mode: upsert
  data:
    key: "exec:{{ execution_id }}:message"
    value: "{{ test_step.data.message }}"
    ttl: 86400   # seconds, optional
```

2) Vector store (pgvector/Pinecone/Milvus/Weaviate):

```
sink:
  storage: vector
  auth: pg_main
  spec: { driver: pgvector, table: embeddings, id_column: id, vector_column: embedding, meta_column: meta }
  mode: upsert
  data:
    id: "{{ execution_id }}"
    vector: "{{ embedding_from(test_step.data.message) }}"   # your embedding helper
    meta:
      step: test_step
      message: "{{ test_step.data.message }}"
```

3) Graph DB (Neo4j/Cypher):

```
sink:
  storage: graph
  auth: neo4j_main
  spec: { dialect: cypher }
  statement: |
    MERGE (e:Execution {id: $execution_id})
    MERGE (s:Step {name: $step_name})
    MERGE (e)-[:HAS_STEP]->(s)
    SET s.message = $message
  params:
    execution_id: "{{ execution_id }}"
    step_name: test_step
    message: "{{ test_step.data.message }}"
```

4) Raw SQL upsert with params:

```
sink:
  tool: postgres
  auth: pg_main
  statement: |
    INSERT INTO hello_world(execution_id, payload)
    VALUES (:execution_id, :payload)
    ON CONFLICT(execution_id) DO UPDATE SET payload = EXCLUDED.payload
  params:
    execution_id: "{{ execution_id }}"
    payload: "{{ tojson(test_step.data) }}"
```

## 7) Template Context in Sink Execution

When a `sink:` block executes, the worker prepares a special template context with access to the step's result. **Important**: The worker automatically unwraps the result envelope before passing it to sink templates.

### Context Variables Available in Sink Templates

- **`result`** or **`data`**: The unwrapped step result data (recommended: use `{{ result }}` for clarity)
  - If step returns `{status: "success", data: {...}}`, `result` contains the unwrapped `{...}` directly
  - Access fields as `{{ result.field_name }}` not `{{ result.data.field_name }}`
- **`this`**: The full result envelope with `status`, `data`, `error`, and `meta` fields
  - Use `{{ this.status }}` to check execution status
  - Use `{{ this.meta }}` to access metadata
- **`workload`**: Global workflow variables
- **`execution_id`**: Current execution identifier
- **All prior step results**: Reference as `{{ step_name.field }}`

### Correct Usage Examples

✅ **CORRECT** - Reference unwrapped data:
```yaml
sink:
  tool: postgres
  table: results
  args:
    payload: "{{ result }}"              # Full unwrapped data
    field: "{{ result.field_name }}"     # Specific field
    status: "{{ this.status }}"          # Envelope status
```

❌ **INCORRECT** - Double-nesting:
```yaml
sink:
  tool: postgres
  table: results
  args:
    payload: "{{ result.data }}"         # WRONG: result is already unwrapped
    field: "{{ result.data.field }}"     # WRONG: double-access
```

### Why This Design?

The worker unwraps the result envelope (`{status, data, error}`) before sink execution to simplify template access patterns. This means:
1. Most templates can use `{{ result.field }}` directly without the `.data` suffix
2. Advanced cases can access envelope metadata via `{{ this.status }}` or `{{ this.error }}`
3. Templates stay clean and intuitive for the common case

### Implementation Detail

The unwrapping happens in `noetl/worker/job_executor.py`:
```python
# Worker extracts data from result envelope
current_result = result.get("data") if result.get("data") is not None else result
exec_ctx["result"] = current_result  # Unwrapped data
exec_ctx["data"] = current_result    # Alias for compatibility
exec_ctx["this"] = result            # Full envelope
```

## 8) Notes

- Results always land in `noetl.event_log` for lineage and diagnostics.
- `sink:` is an additive persistence directive (to database/object/file) evaluated after the step completes.
- In loops, the same `sink:` schema applies; the engine will render per-item or aggregated contexts accordingly.
- Credential resolution should happen server‑side; workers receive only what is needed for execution.
- For statement mode, the engine should default to parameterized execution (`params:`) and support dialect routing (SQL/Cypher/Gremlin/Sparql) according to `storage` value and `spec`.
