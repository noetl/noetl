# Loop with Pagination Test

This folder contains a test for the **distributed iterator + pagination architecture** combining event-driven loop orchestration with HTTP pagination using NoETL's unified retry system.

## 🎯 Current Status

**✅ PHASE 2 COMPLETE: Server-Side Loop Orchestration**
- Loop detection in publisher (initial steps & transitions)
- Collection template rendering (`{{ workload.endpoints }}` → array)
- `iterator_started` event emission with full metadata
- Server processes event and enqueues N iteration jobs
- Workers execute iteration jobs independently
- All iterations share parent execution_id

**🔮 PHASE 3 DESIGNED: Pagination via Retry**
- HTTP action execution with `retry.on_success`
- Server-side pagination state tracking
- Page continuation logic
- Result aggregation

## Overview

The `loop_with_pagination.yaml` playbook demonstrates the **server-side distributed loop pattern** where:
- Server detects `loop` attribute in step configuration
- Server renders collection template (`{{ workload.endpoints }}`)
- Server emits `iterator_started` event with collection metadata
- Server enqueues N iteration jobs (one per collection item)
- Workers execute iteration jobs independently with pagination support via `retry.on_success`

**Test Scenario:**
- **Collection**: 2 API endpoints (assessments, users)
- **Mode**: Sequential iteration
- **Expected**: 2 iteration jobs created and executed successfully

## Files

- `loop_with_pagination.yaml` - Playbook definition with loop + pagination config
- `pagination_loop_test.ipynb` - **Validation notebook** (shows architecture details)
- `README.md` - This file

## Architecture Validation

The test notebook (`pagination_loop_test.ipynb`) validates the complete architecture:

### What It Shows

**✅ Event Flow Timeline**
- Displays all events: `playbook_started` → `iterator_started` → `action_completed`

**✅ iterator_started Event Details**
- Status, total count, collection size
- Mode (sequential/async), iterator name
- Nested task tool type

**✅ Iterator Metadata**
- Complete collection data (2 endpoints with paths, page_size)
- Nested task configuration (HTTP action with pagination)
- Pagination config: `retry.on_success` with while condition, max_attempts, merge strategy

**✅ Implementation Status**
```
✅ Loop Detection: WORKING (publisher.py)
✅ Collection Rendering: WORKING (Jinja2 templates)
✅ iterator_started Event: EMITTED
✅ Server Orchestrator: WORKING (_process_iterator_started)
✅ Iteration Jobs: ENQUEUED (N jobs per N items)
✅ Worker Execution: WORKING (independent iteration jobs)
```

### Environment Auto-Detection

The notebook supports both environments via `NOETL_ENV` variable:

**Localhost Mode** (default):
```python
# Automatically uses:
# - Server: http://localhost:8082 (NodePort 30082)
# - Database: localhost:54321 (NodePort 30321)
```

**Kubernetes Mode**:
```bash
export NOETL_ENV=kubernetes
# Uses in-cluster service URLs
```

## Deploying the Notebook

The notebook is automatically deployed with JupyterLab:

```bash
# Deploy JupyterLab with both notebooks
noetl run automation/setup/bootstrap.yaml
```

**Quick update** (if notebook already deployed):

```bash
kubectl delete configmap jupyterlab-notebooks -n noetl && \
kubectl create configmap jupyterlab-notebooks \
  --from-file=regression_dashboard.ipynb=tests/fixtures/notebooks/regression_dashboard.ipynb \
  --from-file=pagination_loop_test.ipynb=tests/fixtures/playbooks/pagination/loop_with_pagination/pagination_loop_test.ipynb \
  -n noetl && \
kubectl delete pod -l app=jupyterlab -n noetl --force --grace-period=0
```

**Step-by-step update** (if you prefer to verify each step):

```bash
# Delete existing ConfigMap
kubectl delete configmap jupyterlab-notebooks -n noetl

# Create ConfigMap with both notebooks
kubectl create configmap jupyterlab-notebooks \
  --from-file=regression_dashboard.ipynb=tests/fixtures/notebooks/regression_dashboard.ipynb \
  --from-file=pagination_loop_test.ipynb=tests/fixtures/playbooks/pagination/loop_with_pagination/pagination_loop_test.ipynb \
  -n noetl

# Force restart JupyterLab pod
kubectl delete pod -l app=jupyterlab -n noetl --force --grace-period=0

# Wait for pod to be ready
kubectl wait --for=condition=ready pod -l app=jupyterlab -n noetl --timeout=90s
```

## Running the Test

### Prerequisites

1. **NoETL Server** deployed:
   ```bash
   noetl run automation/setup/bootstrap.yaml
   ```

2. **Pagination Test Server** running (for full end-to-end test when server orchestration is implemented):
   ```bash
   noetl run automation/test/pagination-server.yaml --set action=full
   ```

3. **PostgreSQL** accessible:
   - Localhost: `jdbc:postgresql://localhost:54321/demo_noetl`
   - Kubernetes: `postgres.postgres.svc.cluster.local:5432/demo_noetl`

### Method 1: Using the Notebook (Recommended)

Open `pagination_loop_test.ipynb` in JupyterLab or VS Code:

1. **Execute Setup** (Cell 1)
   - Auto-detects environment (localhost/kubernetes)
   - Configures server and database connections
   - Set `NOETL_ENV=kubernetes` to override

2. **Initialize Test Table** (Cell 2)
   - Creates `noetl_test.pagination_loop_results` table

3. **Load Database Utilities** (Cell 3)
   - Provides query helper functions

4. **Execute Playbook** (Cell 4)
   - Launches test execution
   - Captures execution_id

5. **Monitor Execution** (Cell 5)
   - Polls status (will timeout - this is expected)
   - Shows event counts

6. **Validate Architecture** (Cell 6) **← KEY VALIDATION**
   - ✅ Confirms `iterator_started` event was emitted
   - ✅ Shows collection metadata (2 endpoints)
   - ✅ Displays pagination configuration
   - ✅ Verifies event schema
   - ⚠️ Notes server orchestration not yet implemented

7. **Review Status** (Cells 7-8)
   - Shows implementation phases
   - Documents next steps

### Method 2: Using cURL (Quick Validation)

```bash
# Execute playbook
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/loop_with_pagination/loop_with_pagination"}'

# Get execution_id from response, then check iterator_started event
curl -s -X POST "http://localhost:8082/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT event_type, status FROM noetl.event WHERE execution_id = <EXECUTION_ID> ORDER BY event_id", "schema": "noetl"}' | jq

# Verify iterator_started event with metadata
curl -s -X POST "http://localhost:8082/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT context FROM noetl.event WHERE execution_id = <EXECUTION_ID> AND event_type = '\''iterator_started'\''", "schema": "noetl"}' | jq
```

## Expected Results (Phase 2)

With server orchestration now implemented, you should see:

**✅ Expected Events:**
```
playbook_started          STARTED
workflow_initialized      COMPLETED  
iterator_started          RUNNING      ← Server detects loop
action_started            RUNNING      ← iter_0 execution
action_completed          COMPLETED    ← iter_0 completes
step_result               COMPLETED    ← iter_0 result
action_started            RUNNING      ← iter_1 execution
action_completed          COMPLETED    ← iter_1 completes
step_result               COMPLETED    ← iter_1 result
```

**✅ iterator_started Context:**
```json
{
  "total_count": 2,
  "mode": "sequential",
  "iterator_name": "endpoint",
  "collection": [
    {"name": "assessments", "path": "/api/v1/assessments", "page_size": 10},
    {"name": "users", "path": "/api/v1/users", "page_size": 15}
  ],
  "nested_task": {
    "tool": "http",
    "url": "{{ workload.api_url }}{{ endpoint.path }}",
    "params": {"page": 1, "pageSize": "{{ endpoint.page_size }}"},
    "retry": {
      "on_success": {
        "while": "{{ response.paging.hasMore == true }}",
        "max_attempts": 10,
        "collect": {"strategy": "append", "path": "data"},
        "next_call": {"params": {"page": "{{ (response.paging.page | int) + 1 }}"}}
      }
    }
  }
}
```

**✅ Queue Jobs Created:**
- `fetch_all_endpoints_iter_0` (for assessments endpoint)
- `fetch_all_endpoints_iter_1` (for users endpoint)
- Both jobs share same parent `execution_id`
- Each job has iteration context with `endpoint` element data

## Validation Criteria (Phase 2)

The notebook validates:

1. ✅ **Loop Detection**: Server detects loop in publisher.py (both initial & transition paths)
2. ✅ **Collection Rendering**: Template `{{ workload.endpoints }}` rendered to array of 2 endpoints
3. ✅ **Event Emission**: `iterator_started` event exists in database with rendered collection
4. ✅ **Iteration Jobs**: 2 queue jobs created (fetch_all_endpoints_iter_0, fetch_all_endpoints_iter_1)
5. ✅ **Worker Execution**: Workers lease and execute iteration jobs independently
6. ✅ **Shared Execution ID**: All iteration jobs share same parent execution_id

## Key Features Demonstrated

### 1. Distributed Loop Architecture (Server-Side)

**Phase 2 (✅ Complete):**
- Server detects `loop` in step configuration (publisher.py)
- Server renders collection template with Jinja2 Environment
  - Input: `"{{ workload.endpoints }}"` (string template)
  - Output: `[{...}, {...}]` (array of 2 endpoint objects)
- Server emits `iterator_started` event with rendered collection
- Server calls `_process_iterator_started()` in orchestrator.py:
  - Extracts collection, nested_task, mode from event context
  - Creates iteration context for each element (accessible via iterator variable)
  - Enqueues N queue jobs (one per collection item)
  - Each job has unique node_id: `{step_name}_iter_{index}`
  - All jobs share parent execution_id
- Workers lease iteration jobs from queue independently
- Workers execute nested_task with iteration context injected
- Workers report completion via events

**Implementation Details:**
```python
# publisher.py (lines 350-368, 540-560)
collection_raw = loop_block.get("collection", [])
if isinstance(collection_raw, str):
    env = Environment(loader=BaseLoader())
    collection = render_template(env, collection_raw, context or {})

# orchestrator.py (lines 1678-1785)
async def _process_iterator_started(execution_id, event):
    collection = event_context.get('collection', [])
    for i, elem in enumerate(collection):
        iteration_context = {
            iterator_name: elem,  # e.g., 'endpoint': {...}
            '_iteration_index': i,
            '_total_iterations': len(collection)
        }
        await QueueService.enqueue_job(
            execution_id=execution_id,  # Shared parent ID
            node_id=f"{step_name}_iter_{i}",
            action=json.dumps(nested_task),
            context=iteration_context
        )
```

**Phase 3 (🔮 Designed - Pagination):**
- Retry logic for failed iterations
- Concurrent iteration execution
- Chunk processing for large collections

### 2. HTTP Retry with Pagination (retry.on_success)

**Server-Side Orchestration (✅ Complete):**
- Server renders collection template and creates iteration jobs
- Each iteration job contains nested HTTP task config
- Worker receives job with iteration context injected

**Worker-Side Execution (✅ Working):**
```yaml
retry:
  on_success:                                    # Pagination trigger
    while: "{{ response.paging.hasMore == true }}"  # Continue condition
    max_attempts: 10                                # Max pages
    collect:
      strategy: append                              # Merge strategy
      path: data                                    # Result path
    next_call:
      params:
        page: "{{ (response.paging.page | int) + 1 }}"  # Next page
```

**Execution Flow:**
1. Worker leases iteration job (e.g., `fetch_all_endpoints_iter_0`)
2. Iteration context provides `endpoint` variable with element data
3. Worker renders nested_task templates with iteration context
4. HTTP action executes with pagination via retry.on_success
5. Worker collects paginated results and reports completion

### 3. Jinja2 Templating

**Current Implementation:**
```yaml
loop:
  collection: "{{ workload.endpoints }}"     # Template evaluation
  element: endpoint                           # Iterator variable

workload:
  server_url: "{{ secret.PAGINATED_API_URL }}"  # Secret resolution
  endpoints:
    - name: assessments
      path: /api/v1/assessments
      page_size: 10
```

**Validation:**
- ✅ Collection template rendered (string → array)
- ✅ Secret resolution works (server_url from PAGINATED_API_URL)
- ✅ Element access in iteration context (endpoint.name, endpoint.path, endpoint.page_size)
- ✅ Nested task templates rendered with iteration context

### 4. Collection Processing Patterns

**Supported Modes:**
- `sequential`: Process one element at a time (tested)
- `async`: Process all elements concurrently (not tested yet)
- `chunked`: Process in batches (not tested yet)

**Current Validation:**
```python
mode = iterator_context.get('mode')  # Returns: 'sequential'
total_count = iterator_context.get('total_count')  # Returns: 2
collection_size = len(collection)  # Returns: 2
```

## Troubleshooting

### Iterator Event Not Appearing

**Check event emission:**
```sql
SELECT event_type, status, context->>'iterator_name' as iterator_name
FROM noetl.event
WHERE execution_id = <EXECUTION_ID>
ORDER BY event_id;
```

### Common issues:**
- Collection template not rendering: Check context contains workload data
- Iteration jobs not created: Verify `_process_iterator_started` is called after event emission
- Template errors in nested tasks: Ensure iteration context has iterator variable (e.g., `endpoint`)
- Wrong number of jobs: Check collection rendering produced correct array length

### Environment Detection Issues

**Check environment setting:**
```python
import os
env = os.getenv('NOETL_ENV', 'localhost')
print(f"Environment: {env}")
```

**Kubernetes mode not working:**
```bash
# Set environment variable before notebook
export NOETL_ENV=kubernetes
# Or set in notebook cell:
os.environ['NOETL_ENV'] = 'kubernetes'
```

### Execution Timeout

**Phase 2 behavior:**
- Execution should complete successfully when pagination test server is running
- If test server not running, iterations will fail (expected - validates architecture)
- Use Cell validation to verify iteration jobs were created and executed

### Test Server Not Running

```bash
noetl run automation/test/pagination-server.yaml --set action=status
noetl run automation/test/pagination-server.yaml --set action=logs
```

### Database Connection Issues
```bash
# Check PostgreSQL pod
kubectl get pod -n postgres -l app=postgres

# Test connection
kubectl exec -n noetl $(kubectl get pod -n noetl -l app=noetl -o jsonpath='{.items[0].metadata.name}') -- \
  psql -h postgres.postgres.svc.cluster.local -U demo -d demo_noetl -c "SELECT 1"
```

### Missing Credentials
```bash
noetl run automation/setup/bootstrap.yaml
```

### View Execution Events
```sql
-- From notebook or psql
SELECT event_type, node_name, status, created_at
FROM noetl.event
WHERE execution_id = <your_execution_id>
ORDER BY created_at;
```

## Success Criteria

### Phase 2 Success (Current - Validated ✅)

The test is successful when validation shows:

1. ✅ **Event Flow**: `playbook_started` → `iterator_started` → multiple action events per iteration
2. ✅ **Iterator Started Details**:
   - Status: RUNNING
   - Total Count: 2
   - Mode: sequential
   - Iterator Name: endpoint
   - Collection: Array of 2 rendered endpoint objects (not template string)
3. ✅ **Iteration Jobs**:
   - 2 jobs created in queue table
   - Job names: `fetch_all_endpoints_iter_0`, `fetch_all_endpoints_iter_1`
   - Both share same parent execution_id
   - Each has iteration context with endpoint element data
4. ✅ **Worker Execution**:
   - Workers lease iteration jobs independently
   - Jobs execute successfully (when test server running)
   - Action events emitted for each iteration

### Phase 3 Success (When Implemented - Expected Future Behavior)

When full pagination and aggregation are complete, the test should also show:

- 🔮 Multiple pages fetched per endpoint (via retry.on_success)
- 🔮 ~70 total items fetched (35 assessments + 35 users)
- 🔮 Results aggregated across pages per iteration
- 🔮 Final execution status: COMPLETED with aggregated results

## Implementation Summary

### What's Working (Phase 2 ✅)

**Server-Side Loop Orchestration:**
- `noetl/server/api/run/publisher.py` (lines 350-368, 540-560):
  - Loop detection in both `publish_initial_steps` and `publish_step`
  - Collection template rendering with Jinja2 Environment
  - `iterator_started` event emission
  - Direct call to `_process_iterator_started` after event emission

- `noetl/server/api/run/orchestrator.py` (lines 1678-1785):
  - `_process_iterator_started()` function processes iterator_started events
  - Extracts collection, nested_task, mode from event context
  - Creates iteration context for each element
  - Enqueues N queue jobs via `QueueService.enqueue_job()`
  - All jobs share parent execution_id

**Worker Execution:**
- Workers lease iteration jobs from queue independently
- Iteration context injected into nested_task templates
- HTTP actions execute with pagination via retry.on_success
- Workers report completion via events

### Next Steps (Phase 3 - Future Work)

Phase 3 will add full pagination support and result aggregation:

1. **Pagination Tracking**: Track page state across retry attempts
2. **Result Aggregation**: Collect and merge paginated results per iteration
3. **Iterator Completion**: Emit `iterator_completed` event when all iterations done
4. **Sink Integration**: Save aggregated results to database via sink blocks

These features are designed but not yet implemented.

## Database Schema (Phase 2)

When sink is implemented, results will be saved to `noetl_test.pagination_loop_results`:

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| execution_id | INTEGER | NoETL execution ID |
| endpoint_name | TEXT | Endpoint identifier (assessments, users) |
| endpoint_path | TEXT | API path |
| page_size | INTEGER | Items per page |
| result_count | INTEGER | Total items fetched |
| iteration_index | INTEGER | Loop iteration (0-based) |
| iteration_count | INTEGER | Total iterations |
| created_at | TIMESTAMP | Record creation time |

## Related Documentation

- [HTTP Pagination](../../../../docs/http_action_type.md)
- [Iterator Loops](../../../../docs/loop_step_parameter.md)
- [Unified Retry System](../../../../docs/retry_unified_implementation.md)
- [Pagination Tests Overview](../README.md)
- [Token Authentication Implementation](../../../../docs/token_auth_implementation.md) (current work)
- [Event-Driven Architecture](../../../../docs/event_model.md)
