# NATS K/V Distributed Cache

NoETL uses NATS JetStream Key-Value (K/V) store for distributed loop state management, enabling horizontal scaling of server pods.

## Overview

Previously, NoETL used an in-memory cache (`_memory_cache`) in `engine.py` to store execution state, including loop iteration results. This approach worked for single-server deployments but prevented horizontal scaling because each server pod maintained its own isolated state.

**NATS K/V Solution:**
- Stores loop state in a distributed NATS JetStream K/V bucket
- Multiple server pods share the same execution state
- Workers can process loop iterations across any available server
- Atomic updates with optimistic locking prevent race conditions

## Architecture

### Components

**Server (engine.py):**
1. On loop initialization: Store initial state in NATS K/V
2. After each step.exit: Append result to NATS K/V
3. On loop completion check: Read iteration count from NATS K/V

**NATS K/V Cache (nats_kv.py):**
- Connects to NATS server at `nats://nats.nats.svc.cluster.local:4222`
- K/V bucket: `noetl_execution_state` (1hr TTL, 1MB max value)
- Key format: `exec:{execution_id}:loop:{step_name}`
- Atomic append with optimistic locking (5 retries, exponential backoff)

### Data Flow

**Architecture:**
```
Server Pod (uvicorn workers 1-N) → NATS K/V
                                      ↓
                    Worker Pods 1-3 (via server API)
```

**Loop Execution:**
```
1. Loop Init:
   Server → NATS K/V: {collection_size: 100, results: [], iterator: "item", mode: "sequential"}

2. Step Exit (each iteration):
   Worker → Server → NATS K/V: append result to results array (atomic)

3. Loop Completion Check:
   Server → NATS K/V: get completed_count = len(results)
   Server: if completed_count < collection_size → create next command

4. Loop Done:
   Server → NATS K/V: mark loop as completed
   Server → NATS K/V: delete execution state (cleanup)
```

## Configuration

**Environment Variables:**

```bash
# NATS server URL (with credentials in manifest ConfigMaps)
NATS_URL=nats://noetl:noetl@nats.nats.svc.cluster.local:4222

# NATS credentials (default: noetl/noetl)
NATS_USER=noetl
NATS_PASSWORD=noetl
```

**Kubernetes ConfigMaps:**
- `ci/manifests/noetl/configmap-server.yaml` - Server NATS config
- `ci/manifests/noetl/configmap-worker.yaml` - Worker NATS config

## API Reference

### NATSKVCache Class

**File:** `noetl/core/cache/nats_kv.py`

**Methods:**

```python
async def connect(nats_url: Optional[str] = None) -> None:
    """Connect to NATS and create/get K/V bucket."""

async def get_loop_state(execution_id: str, step_name: str) -> Optional[dict]:
    """Retrieve loop state for execution/step."""

async def set_loop_state(execution_id: str, step_name: str, state: dict) -> bool:
    """Store complete loop state."""

async def append_loop_result(execution_id: str, step_name: str, result: Any) -> bool:
    """Atomically append result to loop results array (optimistic locking)."""

async def delete_execution_state(execution_id: str) -> bool:
    """Delete all keys for an execution (cleanup)."""
```

### Singleton Instance

```python
from noetl.core.cache import get_nats_cache

nats_cache = await get_nats_cache()
await nats_cache.append_loop_result("123", "fetch_data", {"id": 1})
```

## Integration Points

### Engine.py Changes

**1. Loop Initialization (lines 877-910):**
```python
# Get completed count from NATS K/V (authoritative)
nats_cache = await get_nats_cache()
nats_loop_state = await nats_cache.get_loop_state(str(state.execution_id), step.step)

if nats_loop_state:
    completed_count = len(nats_loop_state.get("results", []))
else:
    # Initialize and store in NATS K/V
    await nats_cache.set_loop_state(state.execution_id, step.step, {...})
```

**2. Result Storage (lines 1132-1150):**
```python
# Add to local state
state.add_loop_result(event.step, result)

# Sync to NATS K/V (distributed)
nats_cache = await get_nats_cache()
await nats_cache.append_loop_result(state.execution_id, event.step, result)
```

**3. Completion Check (lines 1197-1250):**
```python
# Read from NATS K/V for authoritative count
nats_cache = await get_nats_cache()
nats_loop_state = await nats_cache.get_loop_state(state.execution_id, event.step)

if nats_loop_state:
    completed_count = len(nats_loop_state.get("results", []))
    collection_size = nats_loop_state.get("collection_size", 0)
```

## Atomic Updates

### Optimistic Locking

The `append_loop_result()` method uses NATS K/V revision numbers for atomic updates:

```python
async def append_loop_result(self, execution_id: str, step_name: str, result: Any) -> bool:
    max_retries = 5
    for attempt in range(max_retries):
        try:
            # Get current state with revision
            entry = await self._kv.get(key)
            state = json.loads(entry.value.decode('utf-8'))
            
            # Append result
            state["results"].append(result)
            
            # Update with revision check (optimistic lock)
            value = json.dumps(state).encode('utf-8')
            await self._kv.update(key, value, last=entry.revision)
            return True
            
        except Exception as e:
            if "wrong last sequence" in str(e) and attempt < max_retries - 1:
                await asyncio.sleep(0.01 * (attempt + 1))  # Exponential backoff
                continue
            return False
```

**Retry Strategy:**
- 5 attempts maximum
- Exponential backoff: 10ms, 20ms, 30ms, 40ms, 50ms
- Handles concurrent updates from multiple server pods

## Scaling

### Server Scaling (Uvicorn Workers)

The server uses uvicorn with multiple worker processes (not Kubernetes replicas):

```yaml
# ci/manifests/noetl/configmap-server.yaml
NOETL_SERVER_WORKERS: "4"  # Uvicorn worker processes
```

**Server Architecture:**
- Single Kubernetes pod (1 replica)
- Multiple uvicorn workers inside the pod
- Shared NATS K/V state across uvicorn workers

### Worker Scaling (Kubernetes Pods)

Scale worker pods horizontally for distributed execution:

```yaml
# k8s/worker-deployment.yaml
spec:
  replicas: 3  # Multiple worker pods
```

**Benefits:**
- Load balancing across worker instances
- High availability (failover)
- Workers subscribe to NATS for command notifications
- Query server API for command details

## Testing

### Validate NATS K/V Integration

```bash
# Deploy full environment with NATS
task bring-all

# Test loop execution (http_to_postgres_iterator)
task test-http-to-postgres-iterator-full

# Check NATS K/V bucket
kubectl exec -it nats-0 -n nats -- nats kv ls
kubectl exec -it nats-0 -n nats -- nats kv get noetl_execution_state
```

### Multi-Worker Testing

```bash
# Scale workers to 3 pods
kubectl scale deployment noetl-worker --replicas=3

# Verify worker pods are running
kubectl get pods -n noetl -l app=noetl-worker

# Run loop test and verify distributed execution
task test:regression:full
```

## Performance

### Metrics

**Before (in-memory cache):**
- Single server pod only
- No horizontal scaling
- 360ms+ per iteration (with database queries)

**After (NATS K/V):**
- Horizontal scaling with multiple server pods
- ~10-50ms per NATS K/V operation
- Atomic updates with retry logic

### Optimization

**Collection Rendering:**
- Render collection once during initialization
- Store `collection_size` in NATS K/V (not full collection)
- Reduces template rendering overhead

**Result Count:**
- Use `len(results)` instead of database COUNT(*) queries
- Eliminates 360ms+ database roundtrip per iteration

## Cleanup

Loop state is automatically cleaned up:

**TTL-based:**
- NATS K/V bucket has 1-hour TTL
- Expired keys automatically deleted by NATS

**Manual cleanup:**
```python
nats_cache = await get_nats_cache()
await nats_cache.delete_execution_state(execution_id)
```

Cleanup happens on:
- Execution COMPLETED event
- Execution FAILED event
- Manual cleanup (optional)

## Migration Notes

### Removing In-Memory Cache

Future task: Remove `_memory_cache` from `engine.py` (line 325):

```python
# BEFORE
_memory_cache: dict[str, ExecutionState] = {}

# AFTER (to be implemented)
# Cache removed - use NATS K/V only
```

**Impact:**
- Server becomes fully stateless
- All state reconstructed from events + NATS K/V
- Enables true horizontal scaling

### Backward Compatibility

The current implementation maintains local cache as fallback:

```python
if nats_loop_state:
    # Use NATS K/V (authoritative)
    completed_count = len(nats_loop_state.get("results", []))
else:
    # Fallback to local cache
    loop_state = state.loop_state.get(step.step)
    completed_count = len(loop_state.get("results", []))
```

This ensures gradual migration without breaking existing executions.

## See Also

- [Loop DSL Documentation](../reference/dsl_v2_loop.md)
- [NATS JetStream Documentation](https://docs.nats.io/nats-concepts/jetstream)
- [Observability Services](../reference/observability_services.md)
