# Loop with Pagination Test

This folder contains a test for the **distributed iterator + pagination architecture** combining event-driven loop orchestration with HTTP pagination using NoETL's unified retry system.

## 🎯 Current Status

**✅ PHASE 1 COMPLETE: Worker-Side Architecture**
- Loop detection and routing to iterator executor
- Collection analysis (filter, sort, limit)
- Event callback integration
- `iterator_started` event emission with full metadata

**⏳ PHASE 2 PENDING: Server-Side Orchestration**
- Process `iterator_started` event
- Enqueue N iteration jobs (one per collection item)
- Track iteration completion
- Emit `iterator_completed` event

**🔮 PHASE 3 DESIGNED: Pagination via Retry**
- HTTP action execution with `retry.on_success`
- Server-side pagination state tracking
- Page continuation logic
- Result aggregation

## Overview

The `loop_with_pagination.yaml` playbook demonstrates the **event-driven distributed loop pattern** where:
- Worker analyzes collection and emits `iterator_started` event
- Server will process event and enqueue iteration jobs (when implemented)
- Each iteration runs independently with pagination support via `retry.on_success`

**Test Scenario:**
- **Collection**: 2 API endpoints (assessments, users)
- **Mode**: Sequential iteration
- **Expected**: `iterator_started` event with collection metadata

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
✅ Worker Event Callback: WORKING
✅ Iterator Executor: WORKING
✅ iterator_started Event: EMITTED
✅ Event Schema: VALID
⏳ Server Orchestrator: NOT YET IMPLEMENTED
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
task jupyterlab:deploy
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
   task deploy-noetl
   ```

2. **Pagination Test Server** running (for full end-to-end test when server orchestration is implemented):
   ```bash
   task pagination-server:test:pagination-server:full
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

## Expected Results (Phase 1)

Since server orchestration is not yet implemented, you should see:

**✅ Expected Events:**
```
playbook_started          STARTED
workflow_initialized      COMPLETED  
step_started              RUNNING
action_started            RUNNING
iterator_started          RUNNING      ← KEY EVENT!
action_completed          COMPLETED
step_result               COMPLETED
```

**✅ iterator_started Context:**
```json
{
  "total_count": 2,
  "collection_size": 2,
  "mode": "sequential",
  "iterator_name": "endpoint",
  "collection": [
    {"name": "assessments", "path": "/api/v1/assessments", "page_size": 10},
    {"name": "users", "path": "/api/v1/users", "page_size": 15}
  ],
  "nested_task": {
    "tool": "http",
    "retry": {
      "on_success": {
        "while": "{{ response.paging.hasMore == true }}",
        "max_attempts": 10,
        "collect": {"strategy": "append", "path": "data"}
      }
    }
  }
}
```

**⚠️ Expected Behavior:**
- Execution will **not complete** automatically
- No `iteration_completed` events (server doesn't enqueue iterations yet)
- Timeout is **expected** - this validates worker-side implementation only

## Validation Criteria (Phase 1)

The notebook validates:

1. ✅ **Loop Detection**: Worker routes to iterator executor
2. ✅ **Event Emission**: `iterator_started` event exists in database
3. ✅ **Collection Analysis**: 2 endpoints with correct metadata
4. ✅ **Event Schema**: Status is RUNNING, context has all required fields
5. ✅ **Pagination Config**: nested_task contains retry.on_success configuration

## Key Features Demonstrated

### 1. Distributed Loop Architecture (Event-Driven)

**Phase 1 (✅ Complete):**
- Worker detects `loop` in step configuration
- Routes to iterator executor for collection analysis
- Emits `iterator_started` event with full metadata:
  - Collection details (2 endpoints with paths, page_size)
  - Iterator configuration (mode, name, total_count)
  - Nested task definition (HTTP action with retry.on_success pagination)
- Event stored in PostgreSQL event table
- Worker reports back via `action_completed`

**Phase 2 (⏳ Pending - Not Yet Implemented):**
- Server orchestrator will receive `iterator_started` event
- Enqueue N iteration jobs (one per collection element)
- Workers execute each iteration with full pagination
- Emit `iteration_completed` events
- Server aggregates results
- Emit `iterator_completed` when all done

**Phase 3 (🔮 Designed - Not Yet Implemented):**
- Retry logic for failed iterations
- Concurrent iteration execution
- Chunk processing for large collections

### 2. HTTP Retry with Pagination (retry.on_success)

**Worker-Side Analysis (✅ Complete):**
```yaml
retry:
  on_success:                                    # Pagination trigger
    while: "{{ response.paging.hasMore == true }}"  # Continue condition
    max_attempts: 10                                # Max pages
    collect:
      strategy: append                              # Merge strategy
      path: data                                    # Result path
```

**Server-Side Execution (⏳ Pending):**
- Worker will execute HTTP request with auto-pagination
- Server will receive paginated results via `iteration_completed` events
- Aggregation across all endpoints happens in server
- Final merged dataset stored in event context

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
- ✅ Collection templating works (2 endpoints extracted)
- ✅ Secret resolution works (server_url from PAGINATED_API_URL)
- ⏳ Element access in nested tasks (will work when iterations execute)

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

**Common issues:**
- Missing `loop` parameter in step configuration
- Invalid collection template (use `{{ workload.field }}` syntax)
- Event callback not passed through execution chain (fixed in Phase 1)
- EventType schema missing iterator types (fixed in Phase 1)
- Status values lowercase instead of uppercase (fixed in Phase 1)

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

**Expected behavior in Phase 1:**
- Execution will timeout waiting for completion
- This is **normal** - server orchestration not implemented yet
- Use Cell 6 validation to verify architecture instead

### Test Server Not Running

```bash
task pagination-server:test:pagination-server:status
task pagination-server:test:pagination-server:logs
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
task register-test-credentials
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

### Phase 1 Success (Current - What to Validate Now)

The test is successful when notebook Cell 6 shows:

1. ✅ **Event Flow**: 7+ events including `iterator_started`
2. ✅ **Iterator Started Details**:
   - Status: RUNNING
   - Total Count: 2
   - Collection Size: 2
   - Mode: sequential
   - Iterator Name: endpoint
   - Nested Tool: http
3. ✅ **Iterator Metadata**:
   - Collection: 2 endpoints with name, path, page_size
   - Nested Task: HTTP action with retry.on_success pagination config
   - Pagination Config: while condition, max_attempts=10, collect strategy
4. ✅ **Implementation Status**:
   - Worker Event Callback: ✅
   - Iterator Executor: ✅
   - iterator_started Event: ✅
   - Event Schema: ✅
   - Server Orchestrator: ⏳ (expected pending)

### Phase 2 Success (When Implemented - Expected Future Behavior)

When server orchestration is complete, the test should also show:

- ⏳ 2 `iteration_completed` events (one per endpoint)
- ⏳ 1 `iterator_completed` event
- ⏳ ~70 total items fetched (35 assessments + 35 users)
- ⏳ 2 records in `noetl_test.pagination_loop_results`
- ⏳ Final execution status: COMPLETED

## Next Steps (Development)

To complete Phase 2, implement in `noetl/server/api/orchestrator/orchestrator.py`:

1. **Add `_process_iterator_started()` handler:**
   ```python
   async def _process_iterator_started(self, execution_id: int, event: Dict[str, Any]):
       """Enqueue iteration jobs from iterator_started event."""
       context = event.get('context', {})
       collection = context.get('collection', [])
       nested_task = context.get('nested_task', {})
       
       for idx, element in enumerate(collection):
           # Create iteration job
           job_data = {
               'execution_id': execution_id,
               'iteration_index': idx,
               'element': element,
               'task_config': nested_task
           }
           # Enqueue via queue API
           await self._enqueue_job(job_data)
   ```

2. **Register handler in event processor:**
   ```python
   event_handlers = {
       'iterator_started': self._process_iterator_started,
       # ... existing handlers
   }
   ```

3. **Test with this playbook** - should see:
   - 2 iteration jobs enqueued
   - Workers execute HTTP requests with pagination
   - ~35 items per endpoint (70 total)
   - `iteration_completed` events emitted
   - `iterator_completed` event when all done

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
