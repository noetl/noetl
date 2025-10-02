# control_flow_workbook

Verifies:
- `next` with `when:` conditions selects the correct branch.
- Multiple `next` targets **without** `when` run in **parallel**.
- `type: workbook` step resolves to a workbook action by `name`.

Tweak `workload.temperature_c` to flip the branch (>=25 → hot).

## Testing

### Static Tests (Default)
```bash
make test-control-flow-workbook
```
Tests playbook parsing, planning, and structural validation without runtime execution.

### Runtime Tests with Kubernetes Cluster

#### Prerequisites
- Kubernetes cluster deployed with NoETL (use `task bring-all` to deploy full stack)
- NoETL API accessible on `localhost:30082` (NodePort)
- PostgreSQL accessible on `localhost:54321` (NodePort)

#### Test Commands
```bash
# Check cluster health and endpoints
task test-cluster-health

# Register control flow workbook playbook
task test-register-control-flow-workbook

# Execute control flow workbook test
task test-execute-control-flow-workbook

# Full integration test (register + execute)
task test-control-flow-workbook-full
```

#### Alias Commands (shorter)
```bash
# Check cluster health
task tch

# Register playbook
task trcfw

# Execute playbook
task tecfw

# Full test workflow
task tcfwf
```

Tests actual execution through the NoETL server API in the Kubernetes cluster, including:
- Real conditional branching evaluation (temperature >= 25 → hot path)
- Parallel step execution (`hot_task_a` and `hot_task_b` run concurrently)
- Workbook action resolution and execution (`compute_flag` action)
- Distributed worker execution across multiple worker pools

### Legacy Runtime Tests (Local Development)
```bash
# With running local server
make test-control-flow-workbook-runtime

# Full integration (reset DB, restart server, run tests)
make test-control-flow-workbook-full
```

## Expected Execution Flow

1. **Registration**: Playbook is registered with version auto-increment
2. **Execution**: Playbook runs with temperature_c=30 (hot path)
3. **Workflow Steps**:
   - `start` → `eval_flag` (calls workbook action `compute_flag`)
   - `compute_flag` determines `is_hot=true` (30°C >= 25°C)
   - Branches to `hot_path`
   - Parallel execution of `hot_task_a` and `hot_task_b`
   - Both tasks complete to `end`

4. **Worker Distribution**: Tasks distributed across available workers:
   - `worker-gpu-01`, `worker-cpu-01`, `worker-cpu-02`