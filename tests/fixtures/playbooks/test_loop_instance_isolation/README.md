# Test: Loop Instance Isolation with Event ID

## Overview

This test validates the **event_id-based loop instance isolation** feature in NoETL's distributed execution engine. The implementation allows the same step to be used multiple times in a workflow without loop state collision by using unique event IDs to identify each loop instance.

## Problem Statement

In distributed workflows, when the same step name appears multiple times with different loop configurations, their state must be isolated to prevent collision. Without proper isolation:
- Second loop overwrites first loop's state in NATS K/V cache
- Loop results get mixed between different instances
- Workflows with retries, recursion, or DAG patterns fail

## Solution: Event ID-Based Keys

Each time a step is entered, it receives a unique `event_id` (Snowflake ID). This event_id is:
1. Stored in `loop_state["event_id"]` during loop initialization
2. Included in NATS K/V key format: `exec:{execution_id}:loop:{step_name}:{event_id}`
3. Used consistently across all loop operations (get, set, append)

This ensures each loop instance has isolated state, even if the step name is reused.

## Test Workflow

### Workflow Structure

```
start
  ↓
process_items_users (loop: users collection)
  ├─ Iteration 1: Alice
  └─ Iteration 2: Bob
  ↓
middle
  ↓
process_items_products (loop: products collection)
  ├─ Iteration 1: Laptop
  └─ Iteration 2: Mouse
  ↓
verify_results
  ↓
end
```

### Expected Behavior

- **Users Loop** (event_id: A): Processes 2 users independently
- **Products Loop** (event_id: B): Processes 2 products independently
- Both loops maintain separate NATS K/V state without collision
- Final verification step receives both loop results

## Running the Test

### 1. Register and Execute Playbook

```bash
cd /Users/akuksin/projects/noetl/noetl

# Register the playbook
python3 -c "
import requests
import json

with open('tests/fixtures/playbooks/test_loop_instance_isolation/playbook.yaml', 'r') as f:
    content = f.read()

response = requests.post(
    'http://localhost:8082/api/catalog/register',
    json={'path': 'test/loop_instance_isolation', 'content': content}
)
print(f\"Registered catalog_id: {response.json()['catalog_id']}\")
"

# Execute (use the catalog_id from above)
curl -X POST "http://localhost:8082/api/execute" \
  -H "Content-Type: application/json" \
  -d '{"catalog_id": "<CATALOG_ID>", "payload": {}}'
```

### 2. Monitor Execution

```bash
# Get execution status (replace with your execution_id)
EXEC_ID="<EXECUTION_ID>"

curl -s "http://localhost:8082/api/executions/${EXEC_ID}" | jq '{
  status: .status,
  event_count: (.events | length),
  completed_steps: [.events | map(select(.event_type == "step.exit")) | .[] | .node_name]
}'
```

### 3. Verify Loop Results

```bash
# Check users loop results
curl -s "http://localhost:8082/api/executions/${EXEC_ID}" | \
  jq '[.events | map(select(.event_type == "step.exit" and .node_name == "process_items_users")) | .[] | .result]'

# Expected output: 2 user results (Alice, Bob)

# Check products loop results
curl -s "http://localhost:8082/api/executions/${EXEC_ID}" | \
  jq '[.events | map(select(.event_type == "step.exit" and .node_name == "process_items_products")) | .[] | .result]'

# Expected output: 2 product results (Laptop, Mouse)
```

## Validating NATS K/V State

### Method 1: Query NATS K/V Bucket (Direct Access)

If you have NATS CLI tools installed in the NATS pod:

```bash
# List all keys in the noetl_execution_state bucket
kubectl exec -n nats nats-0 -c nats -- \
  nats kv ls noetl_execution_state

# Get specific loop state by execution and event ID
kubectl exec -n nats nats-0 -c nats -- \
  nats kv get noetl_execution_state "exec:${EXEC_ID}:loop:process_items_users:${EVENT_ID_A}"

kubectl exec -n nats nats-0 -c nats -- \
  nats kv get noetl_execution_state "exec:${EXEC_ID}:loop:process_items_products:${EVENT_ID_B}"
```

**Note**: The NATS pods may not have the `nats` CLI pre-installed. If you get "executable file not found", use Method 2.

### Method 2: Server Logs (Recommended)

Check NoETL server logs for NATS K/V operations:

```bash
# Check loop state operations for your execution
kubectl logs -n noetl deploy/noetl-server --tail=2000 | \
  grep "${EXEC_ID}" | \
  grep -E "LOOP-NATS|event_id|loop_state"

# Look for patterns like:
# - "Initialized loop for process_items_users with 2 items, event_id=123..."
# - "[LOOP-NATS] Got count from NATS K/V: 2"
# - "Stored loop state in NATS K/V: exec:123:loop:process_items_users:456"
```

### Method 3: Install NATS CLI in Pod

To install NATS CLI for direct K/V inspection:

```bash
# Install nats CLI in the NATS pod
kubectl exec -n nats nats-0 -c nats -- sh -c '
  curl -sf https://binaries.nats.dev/nats-io/natscli/nats@latest | sh
'

# Then use Method 1 commands above
```

### Method 4: Python Script for K/V Inspection

Create a Python script to connect to NATS and inspect K/V:

```python
import asyncio
from nats.aio.client import Client as NATS
from nats.js import JetStreamContext

async def inspect_kv():
    nc = NATS()
    await nc.connect("nats://noetl:noetl@localhost:30422")  # NodePort
    js = nc.jetstream()
    
    kv = await js.key_value(bucket="noetl_execution_state")
    
    # List all keys
    keys = await kv.keys()
    print(f"Keys in bucket: {keys}")
    
    # Get specific key
    entry = await kv.get("exec:123:loop:process_items_users:456")
    if entry:
        print(f"Value: {entry.value.decode('utf-8')}")
    
    await nc.close()

asyncio.run(inspect_kv())
```

## Expected Results

### Successful Test Indicators

1. **Event Count**: ~38-40 events total
   - 2 playbook/workflow init events
   - 1 start step (6 events: issued, claimed, started, enter, call.done, exit, completed)
   - 2 process_items_users iterations (12 events)
   - 1 middle step (6 events)
   - 2 process_items_products iterations (12 events)
   - 1 verify_results step (6 events)
   - 1 end step (6 events)

2. **Loop Results**:
   - Users: 2 step.exit events with Alice and Bob data
   - Products: 2 step.exit events with Laptop and Mouse data

3. **NATS K/V Keys** (if accessible):
   ```
   exec:{execution_id}:loop:process_items_users:{event_id_A}
   exec:{execution_id}:loop:process_items_products:{event_id_B}
   ```
   
4. **No State Collision**: Both loops complete with correct iteration counts

### Failure Indicators

- Only 1 product processed (state collision)
- Event count < 30 (incomplete workflow)
- Server logs show "No loop state" warnings
- NATS K/V shows only one key for both loops

## Architecture Details

### Key Components Modified

1. **noetl/core/cache/nats_kv.py**
   - `get_loop_state(execution_id, step_name, event_id=None)`
   - `set_loop_state(execution_id, step_name, state, event_id=None)`
   - `append_loop_result(execution_id, step_name, result, event_id=None)`

2. **noetl/core/dsl/v2/engine.py**
   - `init_loop()` - Stores event_id in loop_state
   - `_create_command_for_step()` - Retrieves event_id from `state.step_event_ids`
   - `handle_event()` - Passes event_id to all NATS K/V operations

### Event ID Flow

```
1. Step Entered → event_id generated (Snowflake ID)
2. state.step_event_ids[step_name] = event_id (tracked per step)
3. Loop Init → loop_state["event_id"] = event_id
4. NATS K/V Operations → Use event_id in key format
5. Loop Completion → Same event_id used for final aggregation
```

## Use Cases Enabled

This feature enables several advanced workflow patterns:

1. **Retry Logic**: Same step executed again after failure gets new event_id
2. **Recursive Workflows**: Step calls itself with isolated state
3. **Multi-Stage Processing**: Repeated step names don't collide
4. **DAG Execution**: Converging paths using shared steps
5. **Parallel Branches**: Multiple parallel paths reusing step definitions

## Troubleshooting

### Issue: Only First Loop Completes

**Symptom**: Only users processed, no products
**Cause**: event_id not being passed or cached incorrectly
**Fix**: Check server logs for "event_id=None" in NATS K/V operations

### Issue: Both Loops Show Same Results

**Symptom**: Products loop returns user data
**Cause**: State collision - both loops using same K/V key
**Fix**: Verify event_id is unique for each loop instance in logs

### Issue: NATS K/V Connection Failed

**Symptom**: Logs show "Failed to get loop state from NATS K/V"
**Cause**: NATS service unavailable or credentials incorrect
**Fix**: Check NATS deployment: `kubectl get pods -n nats`

## Related Documentation

- [NATS K/V Distributed Cache](../../../documentation/docs/features/nats_kv_distributed_cache.md)
- [DSL v2 Loop Patterns](../../../documentation/docs/features/dsl_v2_loops.md)
- [Connection Pooling](../../../documentation/docs/features/connection_pooling.md)
