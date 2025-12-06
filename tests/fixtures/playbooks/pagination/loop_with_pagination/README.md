# Loop with Pagination Test

This folder contains a comprehensive test for combining **iterator loops** with **HTTP pagination** using NoETL's unified retry system.

## Overview

The `test_loop_with_pagination.yaml` playbook demonstrates how to:
- Iterate over multiple API endpoints using `tool: iterator`
- Apply HTTP pagination to each endpoint via success-side retry
- Collect paginated results using append strategy
- Persist per-iteration results to PostgreSQL
- Validate total items across all endpoints

## Test Scenario

**Endpoints Tested:**
1. **Assessments API**: `/api/v1/assessments` (10 items per page, ~35 total)
2. **Users API**: `/api/v1/users` (15 items per page, ~35 total)

**Loop Configuration:**
- Mode: Sequential iteration
- Collection: 2 endpoints
- Element variable: `{{ endpoint }}`

**Pagination Configuration:**
- Type: Response-based (success-side retry)
- Continue condition: `{{ response.data.has_more == true }}`
- Max iterations: 10 per endpoint
- Collection strategy: Append items from `data.users`

**Expected Results:**
- Total endpoints processed: 2
- Total items fetched: 70 (35 + 35)
- Database records: 2 (one per iteration)
- Iteration indices: [0, 1]

## Files

- `test_loop_with_pagination.yaml` - Playbook definition
- `pagination_loop_test.ipynb` - Interactive test notebook
- `README.md` - This file

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

1. **Pagination Test Server** running:
   ```bash
   task pagination-server:test:pagination-server:full
   ```

2. **PostgreSQL** with test schema and table:

   The notebook (cell 3) automatically creates the required table, or you can create it manually:

   ```sql
   CREATE SCHEMA IF NOT EXISTS noetl_test;

   CREATE TABLE IF NOT EXISTS noetl_test.pagination_loop_results (
       id SERIAL PRIMARY KEY,
       execution_id BIGINT,
       endpoint_name TEXT,
       endpoint_path TEXT,
       page_size INTEGER,
       result_count INTEGER,
       result_data JSONB,
       iteration_index INTEGER,
       iteration_count INTEGER,
       created_at TIMESTAMP DEFAULT NOW()
   );

   CREATE INDEX IF NOT EXISTS idx_pagination_loop_execution_id 
   ON noetl_test.pagination_loop_results(execution_id);
   ```

3. **Credentials** registered:
   ```bash
   task register-test-credentials
   ```

### Method 1: Using the Notebook (Recommended)

Open `pagination_loop_test.ipynb` in JupyterLab (http://localhost:30888):

1. **Execute Setup** (Cells 1-2)
   - Loads configuration and database utilities
   - Uses modern stack: psycopg3, Polars, Plotly

2. **Initialize Test Table** (Cell 3)
   - Creates `noetl_test.pagination_loop_results` table
   - Automatically creates schema and index

3. **Start Test** (Cell 4)
   - Executes playbook via NoETL API
   - Captures execution_id

4. **Monitor Progress** (Cell 5)
   - Real-time event tracking
   - Shows step completion counts

5. **Analyze Results** (Cell 6)
   - Queries `pagination_loop_results` table
   - Shows per-endpoint breakdown

6. **Validate** (Cell 7)
   - Runs 5 validation checks
   - Reports pass/fail status

7. **Visualize** (Cells 8-9)
   - Bar chart: items per endpoint
   - Timeline: event progression

8. **Cleanup** (Cell 10)
   - Optional test data removal

### Method 2: Using Task Command

```bash
# Register playbook
kubectl exec -n noetl $(kubectl get pod -n noetl -l app=noetl -o jsonpath='{.items[0].metadata.name}') -- \
  noetl-ctl catalog register \
  /app/tests/fixtures/playbooks/pagination/loop_with_pagination/test_loop_with_pagination.yaml \
  tests/pagination/loop_with_pagination

# Execute test
curl -X POST http://localhost:30082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/loop_with_pagination"}'
```

### Method 3: Using NoETL CLI

```bash
# From NoETL pod
kubectl exec -it -n noetl $(kubectl get pod -n noetl -l app=noetl -o jsonpath='{.items[0].metadata.name}') -- bash

# Inside pod
noetl-ctl catalog register \
  /app/tests/fixtures/playbooks/pagination/loop_with_pagination/test_loop_with_pagination.yaml \
  tests/pagination/loop_with_pagination

noetl-ctl run playbook tests/pagination/loop_with_pagination
```

## Validation Criteria

The notebook performs these checks:

1. ✅ **Endpoint Count**: Exactly 2 endpoints processed
2. ✅ **Assessments Items**: 35 items fetched
3. ✅ **Users Items**: 35 items fetched
4. ✅ **Total Items**: 70 items total
5. ✅ **Iteration Indices**: [0, 1] in correct order

## Key Features Demonstrated

### 1. Iterator with Pagination
```yaml
- step: fetch_all_endpoints
  tool: iterator
  collection: "{{ workload.endpoints }}"
  element: endpoint
  mode: sequential
  action:
    tool: http
    url: "{{ pagination_server_url }}{{ endpoint.path }}"
    params:
      page_size: "{{ endpoint.page_size }}"
      page: 1
    loop:
      pagination:
        type: response_based
        continue_while: "{{ response.data.has_more }}"
        next_page:
          params:
            page: "{{ (response.data.page | int) + 1 }}"
        merge_strategy: append
        merge_path: data.users
        max_iterations: 10
```

### 2. Unified Retry System
```yaml
retry:
  error_side:
    enabled: true
    max_attempts: 3
    backoff_strategy: exponential
    retry_on_status: [429, 500, 502, 503]
  success_side:
    enabled: true
    max_attempts: 10
```

### 3. Per-Iteration Sink
```yaml
sink:
  tool: postgres
  auth:
    type: postgres
    credential: pg_k8s
  table: noetl_test.pagination_loop_results
  data:
    execution_id: "{{ execution_id }}"
    endpoint_name: "{{ endpoint.name }}"
    endpoint_path: "{{ endpoint.path }}"
    page_size: "{{ endpoint.page_size }}"
    result_count: "{{ pages | length }}"
    iteration_index: "{{ __iteration__.index }}"
    iteration_count: "{{ __iteration__.count }}"
```

## Troubleshooting

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

## Database Schema

Results are saved to `noetl_test.pagination_loop_results`:

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

## Success Criteria

A successful test run will:
- ✅ Complete without errors
- ✅ Fetch exactly 70 items (35 per endpoint)
- ✅ Create 2 database records
- ✅ Show correct iteration indices [0, 1]
- ✅ Pass all 5 validation checks in the notebook
